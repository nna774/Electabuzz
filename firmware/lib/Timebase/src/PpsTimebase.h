#pragma once
// GNSS 1PPS のエッジ列からティック源の実効レートを推定する（方式A）。→ docs/timebase.md
//
// **PPSエッジは(ロック時)厳密に1秒間隔で来る。** NtpTimebaseと違い、回帰のx軸に
// 「原点からの経過エッジ数(=経過秒数)」をそのまま使えるので、外部の絶対時刻
// (NTP/UTC)は要らない。x軸=経過エッジ数・y軸=ティックの公称からの残差、という
// NtpTimebaseと同じ Welford 回帰の型を流用する。
//
// **本クラスが答えるのは実効レート(fsMicroHz)と確度(residualNs)だけ。**
// 絶対時刻(batch_start_us等)への固定は引き続き NtpTimebase が担う——
// timebase_source=PPS+NTP という組み合わせの値はこの役割分担を表している。
//
// エッジのサンプル位置(sub-sample補間)を求める側は別レイヤ(R chのエッジ検出)の
// 役割で、本クラスは「エッジごとのティック位置(小数可)」を受け取るところから始まる。
//
// Arduino に依存しない。ホストの g++ でテストできる（test/run.sh）。アンテナが
// 無くても、エッジ列さえ合成できればここの正しさは実機無しで検証できる。

#include <cstdint>

#include "TimebaseEstimator.h"

namespace timebase {

class PpsTimebase final : public TimebaseEstimator {
 public:
  // 採用に必要な最小の観測数と経過秒数。NtpTimebaseと同じ役割の閾値だが、
  // PPSは1エッジ=1秒とノイズなしで分かるため、桁で小さい値で足りる
  // （NTPの600秒はNTP自体の±5msノイズを均すための時間幅で、PPSにはそれが無い）。
  static constexpr uint32_t kMinObs = 10;
  static constexpr uint32_t kMinSpanSeconds = 30;

  // 1回のaddEdge()呼び出しで許容する最大ギャップ[秒]。これを超えたらreset()する
  // ——長時間の unlocked/holdover を跨いで回帰をつなげると、その区間で
  // 「1エッジ=1秒」という前提そのものが崩れているかもしれないため。
  static constexpr uint32_t kMaxGapSeconds = 300;

  // ギャップを整数エッジ数に丸めたときに許容する誤差(公称ティック数に対する比率)。
  // 実際のfs誤差はppmオーダーなので、5%は十分に緩い安全域
  // （数エッジ分の欠落があっても丸め先を取り違えない）。
  static constexpr double kGapToleranceFraction = 0.05;

  // 回帰が立ってからの外れ値排除。NtpTimebaseと同じ考え方だが、PPSは
  // 桁でノイズが少ないためσ側は厳しめ、floor側も短くしてある。
  static constexpr double kOutlierSigma = 8.0;
  static constexpr double kOutlierFloorSeconds = 0.001;  // 48kHzで約48ティック相当

  // nominalMicroHz: ティック源の**公称**レート [µHz]（例: 48000 * 1e6）。
  explicit PpsTimebase(uint64_t nominalMicroHz);

  // PPSエッジを1つ食わせる。
  //   ticks: そのエッジのサブサンプル補間込みのティック位置(小数可)。
  //          単調増加していること。
  // 採用したら true、捨てたら false。
  //
  // ticks が減っていたら「ティック源が切れた」と見て reset() する
  // （NtpTimebase と同じく、セッション境界で線を繋がない）。
  bool addEdge(double ticks);

  void reset();

  uint64_t fsMicroHz() const override;
  uint32_t residualNs() const override;
  uint32_t obsCount() const override { return n_; }
  Source source() const override { return usable() ? Source::kPps : Source::kNominal; }

  // --- 以下はログ・診断用。ワイヤ形式には載らない ---

  // 採用に足る観測が溜まったか。
  bool usable() const;
  // 捨てた標本の数。増え続けるならエッジ検出かPPS自体の質を疑え。
  uint32_t rejectedCount() const { return rejected_; }
  // 最初のエッジからの経過 [s]（= 累積エッジ数。ロールフォワードで動かない）。
  double spanSeconds() const { return totalEdges_; }
  // 回帰残差の RMS [ns]。NtpTimebase::fitRmsNs() と同じ役回り。
  uint32_t fitRmsNs() const;

 private:
  bool acceptEdge(double ticks, double expectedEdges);
  double predictY(double x) const;
  double residualSumSquares() const;

  // 回帰の原点(ticks0_)を直近の観測点へ付け替える。NtpTimebase::rollForwardOrigin()
  // と同じ理由（unixUsAtに相当する外挿を持たない本クラスでは主に数値安定性のため）。
  void rollForwardOrigin(double xNew);

  uint64_t nominalMicroHz_;
  double nominalHz_;

  bool have0_ = false;
  double ticks0_ = 0.0;      // 回帰原点のティック位置
  double lastTicks_ = 0.0;   // 直近エッジのティック位置（逆行検出用）
  double xCursor_ = 0.0;     // 原点からの経過エッジ数。ロールフォワードのたび0に戻る
  double totalEdges_ = 0.0;  // 起点からの累積エッジ数(=秒)。ロールフォワードで動かない

  uint32_t n_ = 0;
  uint32_t rejected_ = 0;

  // Welford 型の共分散累積。NtpTimebase と同じ理由（長時間走らせても
  // 有効数字が潰れない）。x は経過エッジ数、y は「ティックの公称からのずれ」。
  double meanX_ = 0.0;
  double meanY_ = 0.0;
  double cxx_ = 0.0;
  double cxy_ = 0.0;
  double cyy_ = 0.0;
};

}  // namespace timebase
