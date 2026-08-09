// cyclesToColor() のテスト。
// 確かめたいのは3点だけ:
// 1. 1サイクルちょうど進んでも(整数増分)色は変わらない
//    (基準周波数ぴったりの時、シンクロスコープが静止するのと同じ挙動)
// 2. 端数が増えるとhueが連続的に回る(=色が変わる)
// 3. 1周(65536)したら元の色に戻る(周期性)

#include <algorithm>
#include <cstdio>

#include "LedStatus.h"

static int gFailures = 0;

static void check(const char* name, bool ok) {
  printf("%s %s\n", ok ? "ok  " : "FAIL", name);
  if (!ok) ++gFailures;
}

static bool sameColor(const ledstatus::Rgb& a, const ledstatus::Rgb& b) {
  return a.r == b.r && a.g == b.g && a.b == b.b;
}

int main() {
  using ledstatus::cyclesToColor;
  using ledstatus::Rgb;

  // --- 整数サイクルぶん進んでも色は変わらない(小数部が同じだから) ---
  {
    const Rgb a = cyclesToColor(0, 100);
    const Rgb bOneCycleLater = cyclesToColor(1ULL << 16, 100);       // +1.0サイクル
    const Rgb bManyCyclesLater = cyclesToColor(12345ULL << 16, 100);  // +12345.0サイクル
    check("整数サイクル進行では色が変わらない(+1)", sameColor(a, bOneCycleLater));
    check("整数サイクル進行では色が変わらない(+12345)", sameColor(a, bManyCyclesLater));
  }

  // --- 端数が増えると色が変わる(回転している) ---
  {
    const Rgb a = cyclesToColor(0, 100);
    const Rgb quarter = cyclesToColor(1ULL << 14, 100);  // +0.25サイクル
    const Rgb half = cyclesToColor(1ULL << 15, 100);     // +0.5サイクル
    check("0.25サイクルで色が変わる", !sameColor(a, quarter));
    check("0.5サイクルで色が変わる", !sameColor(a, half));
    check("0.25と0.5でも違う色", !sameColor(quarter, half));
  }

  // --- 周期性: 端数が同じなら整数部が違っても同じ色 ---
  {
    const Rgb a = cyclesToColor((1ULL << 14), 100);              // 0.25サイクル
    const Rgb b = cyclesToColor((999ULL << 16) + (1ULL << 14), 100);  // 999.25サイクル
    check("端数が同じなら整数部が違っても同じ色", sameColor(a, b));
  }

  // --- gain: 整数部への影響が消え、端数の回転だけがgain倍される ---
  {
    // gain=1で0.1サイクル分の端数を、gain=10した「等価な」端数(=1.0サイクル→
    // mod後は0)と比較。0.1サイクル*10=1.0サイクルなのでmod 1で0に戻るはず。
    const uint64_t tenthCycle = static_cast<uint64_t>(0.1 * 65536.0 + 0.5);
    const Rgb origin = cyclesToColor(0, 100, /*gain=*/1);
    const Rgb gained = cyclesToColor(tenthCycle, 100, /*gain=*/10);
    check("gain=10で0.1サイクルは1周して原点に戻る", sameColor(origin, gained));

    // 整数サイクル分の進行は、gainを掛けても色に影響しない
    // (整数部はgain倍しても65536の倍数のまま)。
    const Rgb a = cyclesToColor(0, 100, /*gain=*/7);
    const Rgb b = cyclesToColor(42ULL << 16, 100, /*gain=*/7);  // +42.0サイクル
    check("gain>1でも整数サイクル進行では色が変わらない", sameColor(a, b));
  }

  // --- brightnessが低いほど暗い(最大成分が小さい) ---
  {
    const Rgb dim = cyclesToColor(0, 20);
    const Rgb bright = cyclesToColor(0, 200);
    const auto maxc = [](const Rgb& c) {
      return std::max({c.r, c.g, c.b});
    };
    check("brightnessが低いほど最大成分が小さい", maxc(dim) < maxc(bright));
  }

  printf(gFailures == 0 ? "PASS\n" : "FAIL (%d)\n", gFailures);
  return gFailures == 0 ? 0 : 1;
}
