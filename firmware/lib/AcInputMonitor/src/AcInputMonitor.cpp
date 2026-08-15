#include "AcInputMonitor.h"

namespace acinput {

AcInputMonitor::AcInputMonitor(uint16_t thresholdMv, uint32_t sustainWindows)
    : thresholdMv_(thresholdMv), sustainWindows_(sustainWindows) {}

bool AcInputMonitor::update(uint16_t vRmsMv) {
  const bool wasFaulted = faulted_;
  if (vRmsMv < thresholdMv_) {
    aboveCount_ = 0;
    if (belowCount_ < sustainWindows_) ++belowCount_;
    if (belowCount_ >= sustainWindows_) faulted_ = true;
  } else {
    belowCount_ = 0;
    if (aboveCount_ < sustainWindows_) ++aboveCount_;
    if (aboveCount_ >= sustainWindows_) faulted_ = false;
  }
  return faulted_ != wasFaulted;
}

void AcInputMonitor::reset() {
  belowCount_ = 0;
  aboveCount_ = 0;
  faulted_ = false;
}

}  // namespace acinput
