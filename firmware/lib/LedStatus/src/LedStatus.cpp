#include "LedStatus.h"

#include <algorithm>
#include <cmath>

namespace ledstatus {
namespace {

Rgb hsvToRgb(double hueDeg, double sat, double val) {
  hueDeg = std::fmod(hueDeg, 360.0);
  if (hueDeg < 0.0) hueDeg += 360.0;

  const double c = val * sat;
  const double x = c * (1.0 - std::fabs(std::fmod(hueDeg / 60.0, 2.0) - 1.0));
  const double m = val - c;

  double rp, gp, bp;
  if (hueDeg < 60.0) {
    rp = c; gp = x; bp = 0.0;
  } else if (hueDeg < 120.0) {
    rp = x; gp = c; bp = 0.0;
  } else if (hueDeg < 180.0) {
    rp = 0.0; gp = c; bp = x;
  } else if (hueDeg < 240.0) {
    rp = 0.0; gp = x; bp = c;
  } else if (hueDeg < 300.0) {
    rp = x; gp = 0.0; bp = c;
  } else {
    rp = c; gp = 0.0; bp = x;
  }

  auto to255 = [](double v) {
    return static_cast<uint8_t>(std::lround(std::max(0.0, std::min(1.0, v)) * 255.0));
  };
  return Rgb{to255(rp + m), to255(gp + m), to255(bp + m)};
}

}  // namespace

Rgb cyclesToColor(uint64_t cyclesQ16, uint8_t brightness, uint32_t gain) {
  // gainを掛けてからmod 65536(下位16bit)を取る。掛ける前の整数部は
  // 65536の倍数なのでgain倍しても65536の倍数のまま=mod後は消える。
  // 残るのは端数部分がgain倍された回転だけ。
  const uint64_t scaled = cyclesQ16 * static_cast<uint64_t>(gain);
  const double frac = static_cast<double>(scaled & 0xFFFFULL) / 65536.0;
  const double hue = frac * 360.0;
  const double val = static_cast<double>(brightness) / 255.0;
  return hsvToRgb(hue, 1.0, val);
}

}  // namespace ledstatus
