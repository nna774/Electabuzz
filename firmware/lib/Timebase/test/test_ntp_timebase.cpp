// NtpTimebase（回帰）のテスト。Arduino に依存しないのでホストの g++ で走る。
//
// 眼目は2つ。
//   1. **既知の ppm を食わせて、その ppm が返ってくるか**（回帰そのものの正しさ）
//   2. **測れていないうちに kNtp を名乗らないか**（不変条件の側）
// 2 の方が重い。1 が壊れれば数字がおかしいと気づけるが、2 が壊れると
// 「規正済みに見える規正されていないデータ」が出て、後から区別できない。

#include <cmath>
#include <cstdint>
#include <cstdio>

#include "NtpTimebase.h"

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

// esp_timer 相当のティック源（公称 1MHz = µs 刻み）。
static constexpr uint64_t kNominalUHz = 1000000ULL * 1000000ULL;
static constexpr double kNominalHz = 1e6;

// 決定的な擬似乱数。テストが実行ごとに揺れると「たまに落ちる」になって信用できない。
struct Lcg {
  uint64_t s = 88172645463325252ULL;
  double next() {  // [-1, 1)
    s = s * 6364136223846793005ULL + 1442695040888963407ULL;
    return static_cast<double>(static_cast<int32_t>(s >> 33)) / 2147483648.0;
  }
};

// 実 ppm の水晶に、片道遅延のばらつき noiseUs を乗せた標本列を食わせる。
static void feed(timebase::NtpTimebase& tb, double ppm, int n, uint32_t periodSec,
                 double noiseUs, Lcg& rng, uint64_t rttTicks = 4000) {
  const uint64_t unix0 = 1750000000000000ULL;
  const uint64_t ticks0 = 123456789ULL;
  for (int i = 0; i < n; ++i) {
    const double t = static_cast<double>(i) * periodSec;
    const uint64_t unixUs = unix0 + static_cast<uint64_t>(t * 1e6);
    // ティックは実レートで進む。NTP 時刻の側にノイズが乗ると見なす（等価）。
    const double ticks = kNominalHz * (1.0 + ppm * 1e-6) * t + rng.next() * noiseUs;
    tb.addObservation(ticks0 + static_cast<uint64_t>(ticks + 0.5), unixUs, rttTicks);
  }
}

int main() {
  // --- 1. 既知の ppm が返ってくるか ---
  {
    Lcg rng;
    timebase::NtpTimebase tb(kNominalUHz);
    feed(tb, 37.5, 60, 64, 0.0, rng);  // ノイズ無し・64秒間隔・約1時間
    check("ノイズ無しなら usable", tb.usable());
    const double ppm = (static_cast<double>(tb.fsMicroHz()) / static_cast<double>(kNominalUHz) - 1.0) * 1e6;
    checkNear("実 ppm を復元する", ppm, 37.5, 0.05);
    check("source は NTP", tb.source() == timebase::Source::kNtp);
    check("残差はほぼ 0", tb.residualNs() < 100);
  }

  // --- 2. NTP のノイズが確度の自己申告に出るか ---
  {
    Lcg rng;
    timebase::NtpTimebase tb(kNominalUHz);
    // ±5ms の往復ノイズを 64秒間隔で1時間。docs/timebase.md が「1時間窓で 1.4ppm」と
    // 見積もっている条件に近い。桁で合っていることを見る（分布が違うので係数は合わない）。
    feed(tb, -12.0, 57, 64, 5000.0, rng);
    check("ノイズ有りでも usable", tb.usable());
    const double ppm = (static_cast<double>(tb.fsMicroHz()) / static_cast<double>(kNominalUHz) - 1.0) * 1e6;
    checkNear("ノイズ下でも実 ppm に寄る", ppm, -12.0, 1.0);
    // residualNs は ns/s なので 1ppm = 1000ns/s。
    check("確度の自己申告が ppm 級で出る", tb.residualNs() > 10 && tb.residualNs() < 5000);
    check("経路ノイズは fitRmsNs に出る", tb.fitRmsNs() > 1000000 && tb.fitRmsNs() < 10000000);
  }

  // --- 3. 測れていないうちは何も主張しない ---
  {
    Lcg rng;
    timebase::NtpTimebase tb(kNominalUHz);
    feed(tb, 37.5, 4, 64, 0.0, rng);  // 観測数が足りない
    check("観測数不足では usable でない", !tb.usable());
    check("観測数不足なら source は NOMINAL", tb.source() == timebase::Source::kNominal);
    check("観測数不足なら fs は公称値のまま", tb.fsMicroHz() == kNominalUHz);
    check("観測数不足なら残差は最悪を申告", tb.residualNs() == 0xFFFFFFFFu);
  }
  {
    Lcg rng;
    timebase::NtpTimebase tb(kNominalUHz);
    feed(tb, 37.5, 30, 10, 0.0, rng);  // 数は足りるが 290 秒しか張っていない
    check("時間幅不足では usable でない", !tb.usable());
    check("時間幅不足なら fs は公称値のまま", tb.fsMicroHz() == kNominalUHz);
  }

  // --- 4. 往復遅延の大きい標本を捨てる ---
  {
    timebase::NtpTimebase tb(kNominalUHz);
    const uint64_t unix0 = 1750000000000000ULL;
    check("上限を超える RTT は捨てる",
          !tb.addObservation(1000, unix0, 200000));  // 200ms > kMaxRttUs
    check("捨てても観測数は増えない", tb.obsCount() == 0);
    check("捨てた数が見える", tb.rejectedCount() == 1);

    check("素の RTT は採る", tb.addObservation(1000, unix0, 4000));
    // 最小 4ms の 3倍を超える 20ms は捨てる。
    check("最小の3倍を超える RTT は捨てる",
          !tb.addObservation(64000000 + 1000, unix0 + 64000000, 20000));
  }

  // --- 5. ティック源が切れたら線を繋がない ---
  {
    Lcg rng;
    timebase::NtpTimebase tb(kNominalUHz);
    feed(tb, 37.5, 60, 64, 0.0, rng);
    check("切れる前は usable", tb.usable());
    // ティックが戻る = ティック源のリセット。
    tb.addObservation(1, 1750000010000000ULL, 4000);
    check("ティックが戻ったら積み直し", !tb.usable());
    check("積み直し後の source は NOMINAL", tb.source() == timebase::Source::kNominal);
    check("積み直し後の観測数は1", tb.obsCount() == 1);
  }

  // --- 6. 外れ値ひとつで推定を壊さない ---
  {
    Lcg rng;
    timebase::NtpTimebase tb(kNominalUHz);
    feed(tb, 37.5, 60, 64, 0.0, rng);
    const uint64_t before = tb.fsMicroHz();
    // 1秒ぶんずれた応答（うるう秒の取り違え・経路の詰まり）を1つ混ぜる。
    tb.addObservation(123456789ULL + 61 * 64 * 1000000ULL + 1000000ULL,
                      1750000000000000ULL + 61ULL * 64 * 1000000ULL, 4000);
    check("外れ値は捨てられる", tb.rejectedCount() >= 1);
    check("外れ値で推定が動かない", tb.fsMicroHz() == before);
  }

  // --- 7. 巨大なティック値でも桁落ちしない ---
  {
    // 1週間ぶん（6e11 µs）の位置から積む。生のティックで最小二乗を組むと
    // ここで壊れる。公称ぶんを引いてから積んでいる意味がこれだ。
    timebase::NtpTimebase tb(kNominalUHz);
    const uint64_t unix0 = 1750000000000000ULL;
    const uint64_t ticks0 = 604800ULL * 1000000ULL;
    const double ppm = 21.0;
    for (int i = 0; i < 200; ++i) {
      const double t = static_cast<double>(i) * 64.0;
      tb.addObservation(ticks0 + static_cast<uint64_t>(kNominalHz * (1.0 + ppm * 1e-6) * t + 0.5),
                        unix0 + static_cast<uint64_t>(t * 1e6), 4000);
    }
    const double got = (static_cast<double>(tb.fsMicroHz()) / static_cast<double>(kNominalUHz) - 1.0) * 1e6;
    checkNear("大きなティック起点でも ppm を復元する", got, ppm, 0.05);
  }

  // --- 8. unixUsAt が回帰の逆関数として絶対時刻を復元する ---
  // → バッチ境界の針ノイズ対策（docs/log/2026-08-08-batch-boundary-timestamp-jump.md）。
  // バッチ内のレコード間隔(fsMicroHz)とバッチ起点(unixUsAt)が同じ回帰から出るなら、
  // 両者の間に構造的なズレは原理的に生まれない。
  {
    Lcg rng;
    timebase::NtpTimebase tb(kNominalUHz);
    feed(tb, 37.5, 60, 64, 0.0, rng);  // ノイズ無し・64秒間隔・約1時間
    check("usable", tb.usable());

    // feed() の内部と同じ起点定数（ticks0=123456789, unix0=1750000000000000）。
    const uint64_t ticks0 = 123456789ULL;
    const uint64_t unix0 = 1750000000000000ULL;
    checkNear("起点そのものを復元する", static_cast<double>(tb.unixUsAt(ticks0)),
              static_cast<double>(unix0), 1000.0);  // 1ms 以内

    // 実ppmで100秒進んだ時点のticksを逆算し、対応する絶対時刻が+100秒になっているか。
    const double ppm = 37.5;
    const double dtSec = 100.0;
    const uint64_t ticksAt100s =
        ticks0 + static_cast<uint64_t>(kNominalHz * (1.0 + ppm * 1e-6) * dtSec + 0.5);
    const double gotUs = static_cast<double>(tb.unixUsAt(ticksAt100s));
    checkNear("100秒後のticksは100秒後の絶対時刻に写る", gotUs,
              static_cast<double>(unix0) + dtSec * 1e6, 1000.0);  // 1ms 以内

    check("未規正(usable=false)では0を返す",
          timebase::NtpTimebase(kNominalUHz).unixUsAt(ticks0) == 0);
  }

  printf("\n%s (%d failures)\n", gFailures ? "FAILED" : "PASSED", gFailures);
  return gFailures ? 1 : 0;
}
