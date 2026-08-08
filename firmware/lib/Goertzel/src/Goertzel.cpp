#include "Goertzel.h"

#include <cmath>

namespace gridfreq {

namespace {

// (-pi, pi] へ折り返す。Python の (x+pi)%(2pi)-pi と同じ。
double wrapToPi(double x) {
  double y = std::fmod(x + M_PI, 2.0 * M_PI);
  if (y < 0) y += 2.0 * M_PI;
  return y - M_PI;
}

}  // namespace

GoertzelEstimator::GoertzelEstimator(double fNominalHz, double fs, double windowSec,
                                      uint64_t initialCyclesQ16)
    : fNominalHz_(fNominalHz),
      windowSec_(windowSec),
      cyclesAccum_(static_cast<double>(initialCyclesQ16) / 65536.0),
      cyclesQ16_(initialCyclesQ16) {
  winN_ = static_cast<size_t>(fs * windowSec + 0.5);
  const double theta = 2.0 * M_PI * fNominalHz_ / fs;
  coeff_ = 2.0 * std::cos(theta);
  cosTheta_ = std::cos(theta);
  sinTheta_ = std::sin(theta);
}

bool GoertzelEstimator::addSample(int32_t sample) {
  // 2次IIR再帰: s[n] = x[n] + 2cos(theta)*s[n-1] - s[n-2]。
  // 窓の終端で X = s1 - exp(-j theta)*s2 が Σx[n]exp(-j theta n) と一致する
  // (test/ で直接和との一致を検証済み)。
  const double x = static_cast<double>(sample);
  const double s0 = x + coeff_ * s1_ - s2_;
  s2_ = s1_;
  s1_ = s0;
  ++nInWindow_;
  if (nInWindow_ < winN_) return false;

  const double realPart = s1_ - s2_ * cosTheta_;
  const double imagPart = s2_ * sinTheta_;
  const double phase = std::atan2(imagPart, realPart);
  mag_ = std::sqrt(realPart * realPart + imagPart * imagPart);

  s1_ = 0.0;
  s2_ = 0.0;
  nInWindow_ = 0;

  if (!havePrevPhase_) {
    // 最初の窓は基準点としてのみ使う。cyclesはまだ0のまま、次の窓から積み上げる。
    prevPhase_ = phase;
    havePrevPhase_ = true;
    return false;
  }

  const double dphi = wrapToPi(phase - prevPhase_);
  prevPhase_ = phase;

  cyclesAccum_ += fNominalHz_ * windowSec_ + dphi / (2.0 * M_PI);
  cyclesQ16_ = static_cast<uint64_t>(cyclesAccum_ * 65536.0 + 0.5);
  freqHz_ = fNominalHz_ + dphi / (2.0 * M_PI * windowSec_);

  return true;
}

void GoertzelEstimator::resetWindow() {
  s1_ = 0.0;
  s2_ = 0.0;
  nInWindow_ = 0;
  havePrevPhase_ = false;
}

double detectNominalFreq(const int32_t* samples, size_t n, double fs, double candidateA,
                          double candidateB) {
  auto power = [&](double f) {
    double sumRe = 0.0, sumIm = 0.0;
    for (size_t i = 0; i < n; ++i) {
      const double theta = 2.0 * M_PI * f * static_cast<double>(i) / fs;
      const double x = static_cast<double>(samples[i]);
      sumRe += x * std::cos(theta);
      sumIm -= x * std::sin(theta);  // exp(-j theta) = cos theta - j sin theta
    }
    return std::sqrt(sumRe * sumRe + sumIm * sumIm);
  };
  return power(candidateA) >= power(candidateB) ? candidateA : candidateB;
}

}  // namespace gridfreq
