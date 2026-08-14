// parseGga(NMEA GGAセンテンス解析)のテスト。Arduinoに依存しないのでホストのg++で
// 走る。wire-format.mdの`gnss_fix`フラグに要る「fix quality > 0」の判定が
// 正しいかがここでの眼目。チェックサムは自前で計算するので、既知の実例文字列を
// 記憶に頼って埋め込むより検証として堅い。

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>

#include "NmeaGga.h"

static int gFailures = 0;

static void check(const char* name, bool ok) {
  printf("%s %s\n", ok ? "ok  " : "FAIL", name);
  if (!ok) ++gFailures;
}

// s は "$" で始まり "*" を含まない文字列。正しいチェックサムを付けて返す。
static std::string withChecksum(const std::string& s) {
  uint8_t cs = 0;
  for (size_t i = 1; i < s.size(); ++i) cs ^= static_cast<uint8_t>(s[i]);
  char buf[8];
  std::snprintf(buf, sizeof(buf), "*%02X", cs);
  return s + buf;
}

int main() {
  // --- 1. fixありのGGAを正しく解析するか ---
  {
    const std::string s = withChecksum("$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,");
    gnss::GgaFix fix;
    const bool ok = gnss::parseGga(s.c_str(), s.size(), fix);
    check("解析に成功する", ok);
    check("validになる", fix.valid);
    check("fixQualityが1", fix.fixQuality == 1);
    check("hasFix()がtrue", fix.hasFix());
  }

  // --- 2. fix無し(quality=0)を正しく区別するか ---
  {
    const std::string s = withChecksum("$GPGGA,123519,,,,,0,00,,,,,,,");
    gnss::GgaFix fix;
    const bool ok = gnss::parseGga(s.c_str(), s.size(), fix);
    check("quality=0でも解析自体は成功する", ok);
    check("validになる", fix.valid);
    check("fixQualityが0", fix.fixQuality == 0);
    check("hasFix()がfalse(no fixはfixではない)", !fix.hasFix());
  }

  // --- 3. talker IDが何であっても(GN/GL/GAなど)GGAとして解析できるか ---
  {
    // u-bloxのマルチGNSS既定はGN。
    const std::string s = withChecksum("$GNGGA,235959,4807.038,N,01131.000,E,4,12,0.5,545.4,M,46.9,M,,");
    gnss::GgaFix fix;
    check("GN talker IDでも解析できる", gnss::parseGga(s.c_str(), s.size(), fix));
    check("RTK fixed(4)も拾える", fix.fixQuality == 4);
  }

  // --- 4. チェックサム不一致は弾くか ---
  {
    std::string s = withChecksum("$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,");
    // 末尾2桁(チェックサム値そのもの)を意図的に壊す。
    s[s.size() - 1] = (s[s.size() - 1] == '0') ? '1' : '0';
    gnss::GgaFix fix;
    check("チェックサム不一致はfalseを返す", !gnss::parseGga(s.c_str(), s.size(), fix));
    check("validのままfalse", !fix.valid);
  }

  // --- 5. GGA以外のセンテンスは弾くか ---
  {
    const std::string s = withChecksum("$GNRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W");
    gnss::GgaFix fix;
    check("RMCはGGAとして扱わない", !gnss::parseGga(s.c_str(), s.size(), fix));
  }

  // --- 6. 壊れた入力でクラッシュしないか(短すぎる・'*'が無い) ---
  {
    gnss::GgaFix fix;
    check("短すぎる文字列はfalse", !gnss::parseGga("$G", 2, fix));
    const std::string noStar = "$GPGGA,1,2,3";
    check("'*'が無い文字列はfalse", !gnss::parseGga(noStar.c_str(), noStar.size(), fix));
  }

  if (gFailures == 0) {
    printf("all tests passed\n");
    return 0;
  }
  printf("%d test(s) failed\n", gFailures);
  return 1;
}
