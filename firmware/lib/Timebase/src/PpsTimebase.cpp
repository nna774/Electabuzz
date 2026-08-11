#include "PpsTimebase.h"

#include <cmath>

namespace timebase {
namespace {

uint32_t saturate(double v) {
  if (!(v > 0.0)) return 0;  // NaN もここに落ちる
  if (v >= 4294967295.0) return 0xFFFFFFFFu;
  return static_cast<uint32_t>(v);
}

}  // namespace

PpsTimebase::PpsTimebase(uint64_t nominalMicroHz)
    : nominalMicroHz_(nominalMicroHz),
      nominalHz_(static_cast<double>(nominalMicroHz) * 1e-6) {}

void PpsTimebase::reset() {
  have0_ = false;
  ticks0_ = lastTicks_ = xCursor_ = totalEdges_ = 0.0;
  n_ = 0;
  meanX_ = meanY_ = cxx_ = cxy_ = cyy_ = 0.0;
  // rejected_ は残す。捨てた総数は「エッジ検出かPPS自体の質」の指標なので、
  // ティック源が切れるたびに 0 に戻すと見えなくなる。
}

bool PpsTimebase::usable() const {
  return n_ >= kMinObs && totalEdges_ >= static_cast<double>(kMinSpanSeconds) && cxx_ > 0.0;
}

double PpsTimebase::predictY(double x) const {
  if (!(cxx_ > 0.0)) return meanY_;
  return meanY_ + (cxy_ / cxx_) * (x - meanX_);
}

void PpsTimebase::rollForwardOrigin(double xNew) {
  // NtpTimebase::rollForwardOrigin() と同じ考え方。新しい原点は「回帰直線上の
  // xNewでの予測点」であって生の観測点ではない——原点自体にノイズを乗せない。
  const double yPred = predictY(xNew);  // meanX_/meanY_を動かす前に計算すること
  const double ticksDelta = nominalHz_ * xNew + yPred;

  ticks0_ += ticksDelta;
  meanX_ -= xNew;
  meanY_ -= yPred;
  // cxx_/cxy_/cyy_は原点の平行移動で不変(分散・共分散の基本性質)なので、
  // 回帰の精度(=fsMicroHz()の確度)を一切失わずに原点だけ動かせる。
}

double PpsTimebase::residualSumSquares() const {
  if (!(cxx_ > 0.0)) return 0.0;
  const double rss = cyy_ - (cxy_ / cxx_) * cxy_;
  return rss > 0.0 ? rss : 0.0;
}

bool PpsTimebase::acceptEdge(double ticks, double expectedEdges) {
  const double x = xCursor_ + expectedEdges;
  const double y = (ticks - ticks0_) - nominalHz_ * x;

  // 回帰が立っていれば、そこから大きく外れた標本を捨てる。
  if (usable()) {
    const double s2 = residualSumSquares() / static_cast<double>(n_ - 2);
    const double guardTicks = std::sqrt(s2) * kOutlierSigma;
    const double floorTicks = nominalHz_ * kOutlierFloorSeconds;
    const double guard = guardTicks > floorTicks ? guardTicks : floorTicks;
    if (std::fabs(y - predictY(x)) > guard) {
      ++rejected_;
      return false;
    }
  }

  // Welford 型の更新。y は公称ぶんを引いた残差なので、傾きは「公称からのずれ」になる。
  ++n_;
  const double dx = x - meanX_;
  const double dy = y - meanY_;
  meanX_ += dx / static_cast<double>(n_);
  meanY_ += dy / static_cast<double>(n_);
  cxx_ += dx * (x - meanX_);
  cxy_ += dx * (y - meanY_);
  cyy_ += dy * (y - meanY_);

  xCursor_ = x;
  totalEdges_ += expectedEdges;
  lastTicks_ = ticks;

  // 原点を直近の観測点へロールフォワードする。usable()になってから始める
  // ——回帰がまだ不安定なうちにxNewを原点に据えても意味のある基準点にならない。
  if (usable()) {
    rollForwardOrigin(x);
    xCursor_ = 0.0;
  }

  return true;
}

bool PpsTimebase::addEdge(double ticks) {
  // ティックが戻った = ティック源が切れた。**黙って線を繋がない。**
  if (have0_ && ticks < lastTicks_) reset();

  if (have0_) {
    const double deltaTicks = ticks - lastTicks_;
    const double expectedEdges = std::round(deltaTicks / nominalHz_);

    if (expectedEdges < 1.0) {
      // エッジ検出のグリッチ(1秒未満の間隔で連発した)。この1点だけ捨てる。
      ++rejected_;
      return false;
    }

    if (expectedEdges <= static_cast<double>(kMaxGapSeconds)) {
      const double expectedDelta = expectedEdges * nominalHz_;
      const double tolerance = expectedDelta * kGapToleranceFraction;
      if (std::fabs(deltaTicks - expectedDelta) <= tolerance) {
        return acceptEdge(ticks, expectedEdges);
      }
      // 間隔が公称レートから大きく外れている。エッジ検出の誤検出を疑い捨てる。
      ++rejected_;
      return false;
    }

    // ギャップが大きすぎる(> kMaxGapSeconds)。unlocked/holdoverを跨いで
    // 繋げるのは危険なので、その区間の「1エッジ=1秒」は信用せずresetする。
    reset();
  }

  // 原点を打つ（初回、またはギャップ過大でresetした直後）。
  have0_ = true;
  ticks0_ = ticks;
  lastTicks_ = ticks;
  xCursor_ = 0.0;
  totalEdges_ = 0.0;
  return true;
}

uint64_t PpsTimebase::fsMicroHz() const {
  // **規正できていないうちは公称値をそのまま返す。** 中途半端な回帰の結果を
  // 「測った値」として出すと、source() が kNominal でも下流が信じてしまう。
  if (!usable()) return nominalMicroHz_;
  const double fsHz = nominalHz_ + cxy_ / cxx_;
  if (!(fsHz > 0.0)) return nominalMicroHz_;
  return static_cast<uint64_t>(fsHz * 1e6 + 0.5);
}

uint32_t PpsTimebase::residualNs() const {
  if (!usable() || n_ < 3) return 0xFFFFFFFFu;  // 未知は「最悪」で申告する
  const double s2 = residualSumSquares() / static_cast<double>(n_ - 2);
  const double sigmaSlope = std::sqrt(s2 / cxx_);  // [ticks/s] の 1σ
  const double fsHz = nominalHz_ + cxy_ / cxx_;
  if (!(fsHz > 0.0)) return 0xFFFFFFFFu;
  // 相対誤差 = 1秒あたりに積み上がる時刻偏差の割合。ns/s に直す。
  return saturate(sigmaSlope / fsHz * 1e9);
}

uint32_t PpsTimebase::fitRmsNs() const {
  if (n_ < 3 || !(cxx_ > 0.0)) return 0;
  const double s2 = residualSumSquares() / static_cast<double>(n_ - 2);
  return saturate(std::sqrt(s2) / nominalHz_ * 1e9);
}

}  // namespace timebase
