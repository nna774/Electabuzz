#pragma once
// NTP を基準にティック源の実効レートを推定する。→ docs/timebase.md
//
// **ティック源が何かを問わない。** 単調増加しさえすれば I2S のサンプル数でも
// esp_timer の µs でもよい。PCM1808 が来る前は後者で走らせ、来たら前者に差し替える。
// 回帰の中身は「単調増加するティック源を NTP 時刻に回帰する」だけなので、
// 差し替えでこのクラスは1行も変わらない。
//
// **システム時刻に回帰してはいけない。** 標本は測定専用の SNTP クライアント
// (MeasuringSntp) から取ること。lwIP の SNTP_SYNC_MODE_SMOOTH はシステム時刻の
// 進む速さ自体を制御対象にしているので、それに回帰したら測っているのは水晶ではなく
// slew ループだ。バッチのタイムスタンプ用のシステム時刻は SMOOTH のままでよい。
// **役割を分ける。**
//
// Arduino に依存しない。ホストの g++ でテストできる（test/run.sh）。

#include <cstdint>

#include "TimebaseEstimator.h"

namespace timebase {

class NtpTimebase final : public TimebaseEstimator {
 public:
  // 採用に必要な最小の観測数と時間幅。これを満たすまで source() は kNominal を返し、
  // fsMicroHz() は公称値をそのまま返す。**測れていないうちは何も主張しない。**
  //
  // 600秒という数字は「NTP の ±5ms ノイズで公称水晶の ±20ppm を有意に下回れる幅」
  // として置いた。σ≈5ms・n=8・T=600s なら傾きの 1σ は約 10ppm で、まだ粗いが
  // 公称値よりはましになる。**どれだけ粗いかは residualNs() が正直に答える**ので、
  // ここは「使ってよいか」の下限であって「十分か」の判定ではない。
  static constexpr uint32_t kMinObs = 8;
  static constexpr uint32_t kMinSpanSeconds = 600;

  // 往復遅延がこれを超える標本は捨てる（絶対値）。
  // 自前実装にした利点がこれで、lwIP の SNTP は RTT を見せてくれない。
  static constexpr uint32_t kMaxRttUs = 150000;
  // かつ、実測の最小往復遅延の kRttRatio 倍を超えるものも捨てる。
  static constexpr uint32_t kRttRatio = 3;
  // 最小往復遅延は観測ごとに 1/64 ずつ上へ緩める。まぐれで小さい値を1回引いた
  // だけで以後すべて弾く、という詰まり方を避けるため（約44標本で倍に戻る）。
  static constexpr uint32_t kMinRttCreepShift = 6;

  // 回帰が立ってからの外れ値排除。予測との差が「RMS 残差の kOutlierSigma 倍」または
  // kOutlierFloorUs のどちらか大きい方を超えたら捨てる。床を置くのは、初期に
  // たまたま綺麗に乗った数点で以後を締め出さないため。
  static constexpr double kOutlierSigma = 5.0;
  static constexpr uint32_t kOutlierFloorUs = 20000;

  // nominalMicroHz: ティック源の**公称**レート [µHz]。回帰の初期値であって真値ではない。
  //   esp_timer(µs) なら 1000000 * 1000000 = 1e12。
  explicit NtpTimebase(uint64_t nominalMicroHz);

  // 標本を1つ食わせる。
  //   ticks:     単調増加するティック（往復の中点に対応するもの）
  //   unixUs:    そのティックに対応するサーバ時刻 [µs]
  //   rttTicks:  往復遅延（ticks と同じ単位）
  // 採用したら true、捨てたら false。
  //
  // ticks が減っていたら「ティック源が切れた」と見て reset() する。
  // **セッション境界で線を繋がない**ための処理で、黙って続けてはいけない。
  bool addObservation(uint64_t ticks, uint64_t unixUs, uint64_t rttTicks);

  void reset();

  uint64_t fsMicroHz() const override;
  uint32_t residualNs() const override;
  uint32_t obsCount() const override { return n_; }
  Source source() const override { return usable() ? Source::kNtp : Source::kNominal; }

  // 任意の ticks に対応する絶対 UNIX 時刻[µs]を回帰から逆算する。
  // fsMicroHz() と同じ回帰(ticks0_/unixUs0_ + 傾き)を使うので、**バッチ内のレコード
  // 間隔と同じ時刻源でバッチの起点を打てる**ようになる（→ 針ノイズの根本原因の対策。
  // docs/log/2026-08-08-batch-boundary-timestamp-jump.md）。
  // usable() が false のうちは 0 を返す。呼び出し側で source() == kNtp を確認してから
  // 使うこと（未規正の回帰を絶対時刻として申告しない、という不変条件はここでも守る）。
  uint64_t unixUsAt(uint64_t ticks) const;

  // --- 以下はログ・診断用。ワイヤ形式には載らない ---

  // 採用に足る観測が溜まったか。
  bool usable() const;
  // 捨てた標本の数。増え続けるなら経路かサーバを疑え。
  uint32_t rejectedCount() const { return rejected_; }
  // 最初の観測からの経過 [s]。
  double spanSeconds() const { return spanSeconds_; }
  // 実測の最小往復遅延 [µs]。経路の素の速さ。
  uint32_t minRttUs() const { return minRttUs_; }
  // 回帰残差の RMS [ns]。**これは経路のノイズであって推定の確度ではない。**
  // 確度は residualNs() の方で、こちらは n と時間幅で割り算されている。
  uint32_t fitRmsNs() const;

 private:
  double predictY(double x) const;
  double residualSumSquares() const;

  // 回帰の原点(ticks0_/unixUs0_/meanX_/meanY_)を、回帰直線上の直近の点へ
  // 付け替える。分散・共分散(cxx_/cxy_/cyy_)は原点の平行移動で不変なので、
  // 回帰の精度は一切失わない。unixUsAt()の外挿距離(ticks - ticks0_)を
  // 「NTP問い合わせ間隔程度」に有界化し、fsHzの更新1回あたりの絶対時刻への
  // 影響がセッション経過時間に比例して増幅される問題を構造的に断つ
  // (→ docs/log/2026-08-09-batch-boundary-jump-regression-cause.md)。
  void rollForwardOrigin(double xNew);

  uint64_t nominalMicroHz_;
  double nominalHz_;

  bool have0_ = false;
  uint64_t ticks0_ = 0;
  uint64_t unixUs0_ = 0;
  // 最初の観測時刻。ticks0_/unixUs0_と違いロールフォワードで動かさない不変の
  // 基準点で、spanSeconds()(=usable()の「十分な観測期間があるか」判定)専用。
  uint64_t epochUnixUs_ = 0;
  uint64_t lastTicks_ = 0;
  uint64_t lastUnixUs_ = 0;

  uint32_t n_ = 0;
  uint32_t rejected_ = 0;
  uint32_t minRttUs_ = 0xFFFFFFFFu;
  double spanSeconds_ = 0.0;

  // Welford 型の共分散累積。x は初回からの経過秒、y は「ティックの公称からのずれ」。
  //
  // 積む形を2段階で条件よくしてある。
  //   - **Welford（逐次中心化）にする。** Σx·Σy 形の正規方程式は、長時間走らせると
  //     大きな数どうしの引き算で有効数字が消える
  //   - **さらに公称ぶんを引いて y を残差にする。** こうすると傾きが「公称からのずれ」
  //     そのもの（100ppm でも 100 ticks/s 程度）になり、残差平方和も 30日回しても
  //     桁が潰れない。fsMicroHz() が nominal + slope の形で書けるのもこれのおかげ
  double meanX_ = 0.0;
  double meanY_ = 0.0;
  double cxx_ = 0.0;
  double cxy_ = 0.0;
  double cyy_ = 0.0;
};

}  // namespace timebase
