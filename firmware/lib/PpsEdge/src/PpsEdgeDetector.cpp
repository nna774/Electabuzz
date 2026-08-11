#include "PpsEdgeDetector.h"

namespace ppsedge {

PpsEdgeDetector::PpsEdgeDetector(double threshold, uint64_t refractorySamples)
    : threshold_(threshold), refractorySamples_(refractorySamples) {}

void PpsEdgeDetector::reset() {
  sampleIndex_ = 0;
  haveLast_ = false;
  lastSample_ = 0.0;
  armed_ = true;
  haveLastEdge_ = false;
  lastEdgeIndex_ = 0;
}

bool PpsEdgeDetector::feed(double sample, double& outTicks) {
  const uint64_t index = sampleIndex_++;

  if (!haveLast_) {
    lastSample_ = sample;
    haveLast_ = true;
    return false;
  }

  // ヒステリシス: 一度閾値を上抜けたら、下抜けるまで再トリガしない
  // (立ち上がり直後にノイズで閾値付近を上下しても多重検出しない)。
  if (!armed_) {
    if (sample < threshold_) armed_ = true;
    lastSample_ = sample;
    return false;
  }

  if (lastSample_ < threshold_ && sample >= threshold_) {
    // 不応期チェック。PPSは1Hzなので、直近のエッジからrefractorySamples_未満
    // であればパルス自体のノイズか反射とみなして捨てる(次を待つ)。
    if (haveLastEdge_ && index - lastEdgeIndex_ < refractorySamples_) {
      lastSample_ = sample;
      return false;
    }

    // 線形補間: lastSample_(index-1) から sample(index) の間で閾値を跨いだ点。
    // 帯域制限されたエッジは滑らかなランプなので、直線近似がそのまま
    // サブサンプル位置になる(→ docs/timebase.md)。
    const double span = sample - lastSample_;
    const double frac = span > 0.0 ? (threshold_ - lastSample_) / span : 0.0;
    outTicks = static_cast<double>(index - 1) + frac;

    lastEdgeIndex_ = index;
    haveLastEdge_ = true;
    armed_ = false;
    lastSample_ = sample;
    return true;
  }

  lastSample_ = sample;
  return false;
}

}  // namespace ppsedge
