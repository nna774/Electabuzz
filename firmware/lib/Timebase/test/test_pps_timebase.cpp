// PpsTimebase（PPSエッジ列からの回帰）のテスト。Arduinoに依存しないのでホストの
// g++で走る。アンテナも実機も無くても、エッジ列を合成できればここは検証できる
// （→ docs/log/2026-08-12-gnss-pps-wiring-plan.md「アンテナが無くても進められる作業」）。
//
// 眼目はNtpTimebaseのテストと同じく2つ。
//   1. **既知の ppm を食わせて、その ppm が返ってくるか**（回帰そのものの正しさ）
//   2. **測れていないうちに kPps を名乗らないか**（不変条件の側）
// 加えてPPS固有の3つ目を見る。
//   3. **エッジの欠落(ギャップ)を正しく扱うか**——数秒分の欠落は橋渡しし、
//      長時間のギャップはreset()して繋げない

#include <cmath>
#include <cstdint>
#include <cstdio>

#include "PpsTimebase.h"

static int gFailures = 0;

static void check(const char* name, bool ok) {
  printf("%s %s\n", ok ? "ok  " : "FAIL", name);
  if (!ok) ++gFailures;
}

static void checkNear(const char* name, double got, double want, double tol) {
  if (std::fabs(got - want) <= tol) { printf("ok   %s\n", name); return; }
  printf("FAIL %s: want %.6f ± %.6f, got %.6f\n", name, want, tol, got);
  ++gFailures;
}

// PCM1808相当のティック源（公称48kHz）。
static constexpr uint64_t kNominalUHz = 48000ULL * 1000000ULL;
static constexpr double kNominalHz = 48000.0;

// 決定的な擬似乱数。テストが実行ごとに揺れると「たまに落ちる」になって信用できない。
struct Lcg {
  uint64_t s = 88172645463325252ULL;
  double next() {  // [-1, 1)
    s = s * 6364136223846793005ULL + 1442695040888963407ULL;
    return static_cast<double>(static_cast<int32_t>(s >> 33)) / 2147483648.0;
  }
};

// 実ppmの水晶に、エッジ検出のサブサンプル補間誤差 jitterTicks を乗せたPPSエッジ列を
// n個食わせる。実際のfs誤差はppmオーダーなので、公称からの絶対ずれではなく
// 「1秒ごとに真のティック数だけ進む」列にppmを乗せる形にしてある。
static void feed(timebase::PpsTimebase& tb, double ppm, int n, double jitterTicks, Lcg& rng) {
  const double trueHz = kNominalHz * (1.0 + ppm * 1e-6);
  for (int i = 0; i < n; ++i) {
    const double ticks = trueHz * static_cast<double>(i) + rng.next() * jitterTicks;
    tb.addEdge(ticks);
  }
}

int main() {
  // --- 1. 既知の ppm が返ってくるか(ノイズ無し) ---
  {
    Lcg rng;
    timebase::PpsTimebase tb(kNominalUHz);
    feed(tb, 3.8873, 60, 0.0, rng);  // 実機soakで出た+3.8873ppmに寄せた値、60秒
    check("ノイズ無しなら usable", tb.usable());
    const double ppm = (static_cast<double>(tb.fsMicroHz()) / static_cast<double>(kNominalUHz) - 1.0) * 1e6;
    checkNear("実 ppm を復元する", ppm, 3.8873, 0.01);
    check("source は PPS", tb.source() == timebase::Source::kPps);
    check("残差はほぼ 0", tb.residualNs() < 50);
  }

  // --- 2. エッジ検出のサブサンプル誤差が確度の自己申告に出るか ---
  {
    Lcg rng;
    timebase::PpsTimebase tb(kNominalUHz);
    // 48kHzで±0.5サンプル(帯域制限エッジの補間誤差の見積り)相当のジッタを60秒。
    feed(tb, -8.0, 60, 0.5, rng);
    check("ジッタ有りでも usable", tb.usable());
    const double ppm = (static_cast<double>(tb.fsMicroHz()) / static_cast<double>(kNominalUHz) - 1.0) * 1e6;
    checkNear("ジッタ下でも実 ppm に寄る", ppm, -8.0, 0.5);
    // NTP(1ppm級)よりtimebase.mdが要求するppb級に近いことを確認する。
    check("確度の自己申告がNTPより桁で良い(<200ns/s)", tb.residualNs() < 200);
  }

  // --- 3. 測れていないうちに kPps を名乗らないか ---
  {
    Lcg rng;
    timebase::PpsTimebase tb(kNominalUHz);
    check("初期状態はNOMINAL", tb.source() == timebase::Source::kNominal);
    check("初期状態のfsは公称値", tb.fsMicroHz() == kNominalUHz);
    feed(tb, 20.0, 5, 0.0, rng);  // kMinObs(10)未満
    check("観測不足ならNOMINALのまま", tb.source() == timebase::Source::kNominal);
    check("観測不足ならfsは公称値のまま", tb.fsMicroHz() == kNominalUHz);
  }

  // --- 4. 数秒分のギャップは橋渡しできるか ---
  {
    timebase::PpsTimebase tb(kNominalUHz);
    const double trueHz = kNominalHz * (1.0 + 15.0 * 1e-6);
    int edge = 0;
    for (int i = 0; i < 20; ++i) {
      tb.addEdge(trueHz * static_cast<double>(edge));
      ++edge;
    }
    // 5秒ぶん欠落(エッジ検出が一時的に外れた想定)。ticksは真のレートで進み続ける。
    edge += 5;
    for (int i = 0; i < 20; ++i) {
      tb.addEdge(trueHz * static_cast<double>(edge));
      ++edge;
    }
    check("ギャップを跨いでも usable", tb.usable());
    const double ppm = (static_cast<double>(tb.fsMicroHz()) / static_cast<double>(kNominalUHz) - 1.0) * 1e6;
    checkNear("ギャップ橋渡し後もppmを復元する", ppm, 15.0, 0.05);
    checkNear("spanSecondsはギャップぶんも数える", tb.spanSeconds(), 44.0, 0.5);
  }

  // --- 5. 長すぎるギャップは繋げず reset するか ---
  {
    timebase::PpsTimebase tb(kNominalUHz);
    int edge = 0;
    for (int i = 0; i < 40; ++i) {
      tb.addEdge(kNominalHz * static_cast<double>(edge));
      ++edge;
    }
    check("十分な観測でusable", tb.usable());
    const uint32_t obsBefore = tb.obsCount();

    // kMaxGapSeconds(300)を超える無音区間(unlocked/holdover想定)。
    edge += timebase::PpsTimebase::kMaxGapSeconds + 100;
    tb.addEdge(kNominalHz * static_cast<double>(edge));

    check("長いギャップの直後はresetされNOMINALに戻る", tb.source() == timebase::Source::kNominal);
    check("観測数もリセットされる", tb.obsCount() < obsBefore);
  }

  // --- 6. ティックの逆行は reset するか ---
  {
    timebase::PpsTimebase tb(kNominalUHz);
    int edge = 0;
    for (int i = 0; i < 40; ++i) {
      tb.addEdge(kNominalHz * static_cast<double>(edge));
      ++edge;
    }
    check("逆行前はusable", tb.usable());
    tb.addEdge(1000.0);  // 明らかに逆行(ティック源が切れて再起動した想定)
    check("逆行直後はNOMINAL", tb.source() == timebase::Source::kNominal);
  }

  if (gFailures == 0) {
    printf("all tests passed\n");
    return 0;
  }
  printf("%d test(s) failed\n", gFailures);
  return 1;
}
