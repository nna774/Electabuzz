#include "NmeaGga.h"

#include <cstdint>
#include <cstdlib>

namespace gnss {
namespace {

int hexDigit(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  return -1;
}

}  // namespace

bool parseGga(const char* line, size_t len, GgaFix& out) {
  out = GgaFix{};

  // 最短でも "$xxGGA*hh" くらいは要る(フィールドが全部空でも)。
  if (len < 9 || line[0] != '$') return false;

  size_t starIdx = 0;
  bool haveStar = false;
  for (size_t i = 1; i < len; ++i) {
    if (line[i] == '*') { starIdx = i; haveStar = true; break; }
  }
  if (!haveStar || len < starIdx + 3) return false;

  // チェックサム: `$`直後〜`*`直前までのXORが`*`直後2桁の16進と一致すること。
  uint8_t checksum = 0;
  for (size_t i = 1; i < starIdx; ++i) checksum ^= static_cast<uint8_t>(line[i]);

  const int hi = hexDigit(line[starIdx + 1]);
  const int lo = hexDigit(line[starIdx + 2]);
  if (hi < 0 || lo < 0) return false;
  const uint8_t expected = static_cast<uint8_t>((hi << 4) | lo);
  if (checksum != expected) return false;

  // センテンス種別: talker ID(2文字、何でもよい) + "GGA"。
  if (starIdx < 6 || line[3] != 'G' || line[4] != 'G' || line[5] != 'A') return false;

  // フィールドをカンマで数える。0:ID 1:time 2:lat 3:N/S 4:lon 5:E/W 6:quality ...
  int fieldIndex = 0;
  size_t fieldStart = 0;
  for (size_t i = 0; i <= starIdx; ++i) {
    if (i != starIdx && line[i] != ',') continue;

    if (fieldIndex == 6) {
      const size_t fieldLen = i - fieldStart;
      if (fieldLen == 0) return false;  // 空欄 = fix qualityが提供されていない
      char tmp[4] = {};
      if (fieldLen >= sizeof(tmp)) return false;
      for (size_t k = 0; k < fieldLen; ++k) tmp[k] = line[fieldStart + k];
      out.fixQuality = std::atoi(tmp);
      out.valid = true;
      return true;
    }
    ++fieldIndex;
    fieldStart = i + 1;
  }
  return false;  // field 6 に届く前にセンテンスが終わっていた
}

}  // namespace gnss
