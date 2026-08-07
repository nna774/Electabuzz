#pragma once
// 単一ビンDFT(Goertzel)による周波数・累積位相の推定。
// `tools/gridfreq/goertzel.py`(Python参照実装)のリアルタイム・逐次版。
//
// **Lチャンネルの生サンプルだけで完結する。** PPS(Rチャンネル)にも時間基準の
// 選び方(NominalTimebase/NtpTimebase/PpsTimebase)にも一切触れない
// （→ docs/log/2026-08-07-goertzel-cpp-port.md）。fs は呼び出し側が渡す
// 「測って報告された値」を使うだけで、その出処や確度には無関心。
//
// Python参照実装は窓ぶんのサンプルへ直接 Σx[n]exp(-jθn) を計算するが、
// firmwareでは48000サンプル/秒ぶんのバッファも、96000回/秒のtrig呼び出しも重い。
// 標準的なGoertzelの2次IIR再帰(状態2個・窓ごとにcos/sinを1回だけ計算)に
// 置き換えてある。数学的には同じ和を計算しており、test/ で直接和との一致を検証する。
//
// Arduino に依存しない。ホストの g++ でテストできる（test/run.sh）。

#include <cstddef>
#include <cstdint>

namespace gridfreq {

class GoertzelEstimator {
 public:
  // fNominalHz: 起動時に判別済みの公称周波数(50.0 or 60.0)。
  // fs: 実効サンプルレート[Hz](呼び出し側が用意した推定値。NtpTimebase 等)。
  // windowSec: 窓長[秒]。既定 1.0 で tools/gridfreq/goertzel.py と揃える。
  //
  // **fs はコンストラクタで固定される。** ドリフトを追い続けたいなら
  // 呼び出し側が作り直すこと(Goertzel自体はfsの出処にもドリフトにも無関心という
  // 設計そのものが、フェーズ2を待たずにC++移植してよい根拠になっている)。
  GoertzelEstimator(double fNominalHz, double fs, double windowSec = 1.0);

  // サンプルを1つ流し込む。窓(windowSamples()個)が溜まるたびに内部で1窓確定する。
  // 戻り値: 窓が確定して cyclesQ16()/freqHz()/magnitude() が更新されたら true。
  // **最初の窓は基準点としてのみ使われ、false を返す**
  // (Python参照実装と同じ——AC結合の位相原点は任意なので、1窓目からは差分が取れない)。
  bool addSample(int32_t sample);

  // 進行中の窓と「直前の位相」の参照を捨てる。**cyclesQ16() は巻き戻さない**
  // (絶対累積位相は減らせない——docs/storage.mdの不変条件)。
  // DMA溢れ等でサンプルが欠けた直後に呼ぶ用途を想定していて、次の窓を
  // 「新しい基準点」として扱い直す(コンストラクタ直後と同じ状態に戻る)。
  // 呼び出し側は該当バッチに GfrqFlagDiscontinuity を立てること。
  void resetWindow();

  // 直近確定した窓の値。addSample() が true を返した直後にのみ意味を持つ。
  uint64_t cyclesQ16() const { return cyclesQ16_; }
  double freqHz() const { return freqHz_; }
  double magnitude() const { return mag_; }  // 0 に近いと位相が定義できず信用できない

  size_t windowSamples() const { return winN_; }

 private:
  double fNominalHz_;
  double windowSec_;
  size_t winN_;
  double coeff_;      // 2cos(theta)。再帰の係数
  double cosTheta_;
  double sinTheta_;

  double s1_ = 0.0;
  double s2_ = 0.0;
  size_t nInWindow_ = 0;

  bool havePrevPhase_ = false;
  double prevPhase_ = 0.0;
  double cyclesAccum_ = 0.0;  // 絶対累積位相[サイクル](double)

  uint64_t cyclesQ16_ = 0;
  double freqHz_ = 0.0;
  double mag_ = 0.0;
};

// 起動時の50/60Hz判別。両ビンのパワーを比較するだけ（→ docs/signal-processing.md）。
// 直接和で計算する。起動時の1回きりの呼び出しなのでリアルタイム性能は問題にならない
// (GoertzelEstimator の逐次窓とは別枠)。
double detectNominalFreq(const int32_t* samples, size_t n, double fs,
                          double candidateA = 50.0, double candidateB = 60.0);

}  // namespace gridfreq
