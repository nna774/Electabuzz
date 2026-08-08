#include "NtpTimebase.h"

#include <cmath>

namespace timebase {
namespace {

uint32_t saturate(double v) {
  if (!(v > 0.0)) return 0;  // NaN もここに落ちる
  if (v >= 4294967295.0) return 0xFFFFFFFFu;
  return static_cast<uint32_t>(v);
}

}  // namespace

NtpTimebase::NtpTimebase(uint64_t nominalMicroHz)
    : nominalMicroHz_(nominalMicroHz),
      nominalHz_(static_cast<double>(nominalMicroHz) * 1e-6) {}

void NtpTimebase::reset() {
  have0_ = false;
  ticks0_ = unixUs0_ = epochUnixUs_ = lastTicks_ = lastUnixUs_ = 0;
  n_ = 0;
  spanSeconds_ = 0.0;
  minRttUs_ = 0xFFFFFFFFu;
  meanX_ = meanY_ = cxx_ = cxy_ = cyy_ = 0.0;
  // rejected_ は残す。捨てた総数は「経路が悪い」の指標なので、
  // ティック源が切れるたびに 0 に戻すと見えなくなる。
}

bool NtpTimebase::usable() const {
  return n_ >= kMinObs && spanSeconds_ >= static_cast<double>(kMinSpanSeconds) && cxx_ > 0.0;
}

double NtpTimebase::predictY(double x) const {
  if (!(cxx_ > 0.0)) return meanY_;
  return meanY_ + (cxy_ / cxx_) * (x - meanX_);
}

void NtpTimebase::rollForwardOrigin(double xNew) {
  // 新しい原点は「回帰直線上のxNewでの予測点」。生の観測点(ノイズを含む)では
  // なく回帰の最良推定を使うことで、原点自体にノイズを乗せない。
  const double yPred = predictY(xNew);  // meanX_/meanY_を動かす前に計算すること
  const double ticksDelta = nominalHz_ * xNew + yPred;
  const double unixUsDelta = xNew * 1e6;

  ticks0_ += static_cast<uint64_t>(ticksDelta + 0.5);
  unixUs0_ += static_cast<uint64_t>(unixUsDelta + 0.5);
  meanX_ -= xNew;
  meanY_ -= yPred;
  // cxx_/cxy_/cyy_は原点の平行移動で不変(分散・共分散の基本性質)なので、
  // 回帰の精度(=fsMicroHz()の確度)を一切失わずに原点だけ動かせる。
}

double NtpTimebase::residualSumSquares() const {
  if (!(cxx_ > 0.0)) return 0.0;
  const double rss = cyy_ - (cxy_ / cxx_) * cxy_;
  return rss > 0.0 ? rss : 0.0;
}

bool NtpTimebase::addObservation(uint64_t ticks, uint64_t unixUs, uint64_t rttTicks) {
  // ティックが戻った = ティック源が切れた。**黙って線を繋がない。**
  if (have0_ && ticks < lastTicks_) reset();

  const double rttUs = static_cast<double>(rttTicks) / nominalHz_ * 1e6;
  if (!(rttUs <= static_cast<double>(kMaxRttUs))) {
    ++rejected_;
    return false;
  }
  if (rttUs > static_cast<double>(static_cast<uint64_t>(minRttUs_) * kRttRatio)) {
    ++rejected_;
    return false;
  }

  if (!have0_) {
    have0_ = true;
    ticks0_ = ticks;
    unixUs0_ = unixUs;
    epochUnixUs_ = unixUs;
  } else if (unixUs <= lastUnixUs_) {
    // サーバ時刻が進んでいない（重複・巻き戻り）。回帰の x にできない。
    ++rejected_;
    return false;
  }

  const double x = static_cast<double>(unixUs - unixUs0_) * 1e-6;
  const double y = static_cast<double>(ticks - ticks0_) - nominalHz_ * x;

  // 回帰が立っていれば、そこから大きく外れた標本を捨てる。
  if (usable()) {
    const double s2 = residualSumSquares() / static_cast<double>(n_ - 2);
    const double guardTicks = std::sqrt(s2) * kOutlierSigma;
    const double floorTicks = nominalHz_ * static_cast<double>(kOutlierFloorUs) * 1e-6;
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

  // spanSeconds_は「最初の観測(epochUnixUs_)からの経過」であって、
  // 原点からの経過(x)ではない。ロールフォワードでticks0_/unixUs0_を動かしても
  // usable()の「十分な観測期間があるか」判定はこの不変の基準点で行う。
  spanSeconds_ = static_cast<double>(unixUs - epochUnixUs_) * 1e-6;
  lastTicks_ = ticks;
  lastUnixUs_ = unixUs;

  const uint32_t rtt = saturate(rttUs);
  if (rtt < minRttUs_) {
    minRttUs_ = rtt;
  } else if (minRttUs_ != 0xFFFFFFFFu) {
    // 少しずつ上へ緩める。まぐれの1点で以後を締め出さないため。
    minRttUs_ += (minRttUs_ >> kMinRttCreepShift) + 1;
  }

  // 原点を直近の観測点へロールフォワードし、unixUsAt()の外挿距離を
  // 「NTP問い合わせ間隔程度」に有界化する(→ rollForwardOrigin()のコメント参照)。
  // usable()になってから始める——回帰がまだ不安定なうちにxNewを原点に据えても
  // 意味のある基準点にならない。
  if (usable()) {
    rollForwardOrigin(x);
  }

  return true;
}

uint64_t NtpTimebase::fsMicroHz() const {
  // **規正できていないうちは公称値をそのまま返す。** 中途半端な回帰の結果を
  // 「測った値」として出すと、source() が kNominal でも下流が信じてしまう。
  if (!usable()) return nominalMicroHz_;
  const double fsHz = nominalHz_ + cxy_ / cxx_;
  if (!(fsHz > 0.0)) return nominalMicroHz_;
  return static_cast<uint64_t>(fsHz * 1e6 + 0.5);
}

uint32_t NtpTimebase::residualNs() const {
  if (!usable() || n_ < 3) return 0xFFFFFFFFu;  // 未知は「最悪」で申告する
  const double s2 = residualSumSquares() / static_cast<double>(n_ - 2);
  const double sigmaSlope = std::sqrt(s2 / cxx_);  // [ticks/s] の 1σ
  const double fsHz = nominalHz_ + cxy_ / cxx_;
  if (!(fsHz > 0.0)) return 0xFFFFFFFFu;
  // 相対誤差 = 1秒あたりに積み上がる時刻偏差の割合。ns/s に直す。
  return saturate(sigmaSlope / fsHz * 1e9);
}

uint64_t NtpTimebase::unixUsAt(uint64_t ticks) const {
  // **fsMicroHz() と同じ回帰式の逆関数。** 回帰は y = ticks - ticks0_ - nominalHz_*x
  // (x = 経過秒) を x に最小二乗で当てているので、fsHz = nominalHz_ + cxy_/cxx_ を使うと
  // ticks - ticks0_ ≈ fsHz * x → x ≈ (ticks - ticks0_) / fsHz で経過秒が復元できる。
  if (!usable()) return 0;
  const double fsHz = nominalHz_ + cxy_ / cxx_;
  if (!(fsHz > 0.0)) return 0;
  const double x = (static_cast<double>(ticks) - static_cast<double>(ticks0_)) / fsHz;
  const double unixUs = static_cast<double>(unixUs0_) + x * 1e6;
  return unixUs > 0.0 ? static_cast<uint64_t>(unixUs + 0.5) : 0;
}

uint32_t NtpTimebase::fitRmsNs() const {
  if (n_ < 3 || !(cxx_ > 0.0)) return 0;
  const double s2 = residualSumSquares() / static_cast<double>(n_ - 2);
  return saturate(std::sqrt(s2) / nominalHz_ * 1e9);
}

}  // namespace timebase
