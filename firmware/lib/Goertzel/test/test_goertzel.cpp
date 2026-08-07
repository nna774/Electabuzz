// GoertzelEstimator(単一ビンDFTの逐次C++移植)のテスト。
//
// `tools/gridfreq/goertzel.py`の精度は`tools/backtest_gridfreq.py`で既に確認済み
// なので、ここで確かめるのは「2次IIR再帰への書き換えで数学的に同じ答えが出るか」
// ——特に符号の取り違え(周波数が高い方にずれた時に測定値が逆に動く、といった
// バグ)が無いことに絞る。

#include <cmath>
#include <cstdio>
#include <vector>

#include "Goertzel.h"

static int gFailures = 0;

static void check(const char* name, bool ok) {
  printf("%s %s\n", ok ? "ok  " : "FAIL", name);
  if (!ok) ++gFailures;
}

static void checkNear(const char* name, double got, double want, double tol) {
  const bool ok = std::fabs(got - want) <= tol;
  if (ok) {
    printf("ok   %s (got %.6f)\n", name, got);
  } else {
    printf("FAIL %s: want %.6f +-%.6f, got %.6f\n", name, want, tol, got);
    ++gFailures;
  }
}

static std::vector<int32_t> makeTone(double freqHz, double fs, double amplitude,
                                      double phase0, size_t n) {
  std::vector<int32_t> out(n);
  for (size_t i = 0; i < n; ++i) {
    const double t = static_cast<double>(i) / fs;
    out[i] = static_cast<int32_t>(std::lround(amplitude * std::sin(2.0 * M_PI * freqHz * t + phase0)));
  }
  return out;
}

int main() {
  const double fs = 48000.0;
  const double fNom = 50.0;

  // --- 最初の窓は基準点のみ。cyclesを動かさない ---
  {
    gridfreq::GoertzelEstimator est(fNom, fs);
    const auto tone = makeTone(fNom, fs, 1000.0, 0.0, est.windowSamples());
    bool anyTrue = false;
    for (int32_t s : tone) anyTrue = anyTrue || est.addSample(s);
    check("最初の窓はfalseを返す(基準点のみ)", !anyTrue);
    check("最初の窓ではcyclesQ16は0のまま", est.cyclesQ16() == 0);
  }

  // --- ぴったり公称周波数のトーン: dphiはほぼ0、freqHzは公称値に一致する ---
  {
    gridfreq::GoertzelEstimator est(fNom, fs);
    const size_t winN = est.windowSamples();
    const auto tone = makeTone(fNom, fs, 1000.0, 0.3 /* 任意の初期位相 */, winN * 4);
    bool ok = true;
    double lastFreq = 0.0;
    uint64_t lastCycles = 0;
    for (size_t i = 0; i < tone.size(); ++i) {
      if (est.addSample(tone[i])) {
        lastFreq = est.freqHz();
        lastCycles = est.cyclesQ16();
      }
    }
    checkNear("公称ちょうどのトーンはfreqHzが公称値に一致", lastFreq, fNom, 1e-6);
    // 3窓ぶん(基準窓を除く)進んでいるはず: cycles = fNom * windowSec * 3
    const double wantCycles = fNom * 3.0;
    checkNear("公称ちょうどのトーンはcyclesが等速で積み上がる",
              static_cast<double>(lastCycles) / 65536.0, wantCycles, 1e-3);
    (void)ok;
  }

  // --- 公称より高い周波数を入れたら、測定値も高い側に出る(符号の検証) ---
  {
    const double delta = 0.2;  // +0.2Hz
    gridfreq::GoertzelEstimator est(fNom, fs);
    const size_t winN = est.windowSamples();
    const auto tone = makeTone(fNom + delta, fs, 1000.0, 0.0, winN * 3);
    double lastFreq = 0.0;
    for (size_t i = 0; i < tone.size(); ++i) {
      if (est.addSample(tone[i])) lastFreq = est.freqHz();
    }
    checkNear("入力が+0.2Hz高いとfreqHzも+0.2Hz高く出る(符号)", lastFreq, fNom + delta, 5e-3);
  }

  // --- 公称より低い周波数を入れたら、測定値も低い側に出る ---
  {
    const double delta = -0.2;
    gridfreq::GoertzelEstimator est(fNom, fs);
    const size_t winN = est.windowSamples();
    const auto tone = makeTone(fNom + delta, fs, 1000.0, 0.0, winN * 3);
    double lastFreq = 0.0;
    for (size_t i = 0; i < tone.size(); ++i) {
      if (est.addSample(tone[i])) lastFreq = est.freqHz();
    }
    checkNear("入力が-0.2Hz低いとfreqHzも-0.2Hz低く出る(符号)", lastFreq, fNom + delta, 5e-3);
  }

  // --- 振幅の妥当性: 実正弦波1本ならGoertzelの振幅はおよそ A*N/2 になる ---
  {
    const double amplitude = 1000.0;
    gridfreq::GoertzelEstimator est(fNom, fs);
    const size_t winN = est.windowSamples();
    const auto tone = makeTone(fNom, fs, amplitude, 0.1, winN * 2);
    double lastMag = 0.0;
    for (size_t i = 0; i < tone.size(); ++i) {
      if (est.addSample(tone[i])) lastMag = est.magnitude();
    }
    checkNear("振幅は概ねA*N/2", lastMag, amplitude * static_cast<double>(winN) / 2.0,
              amplitude * static_cast<double>(winN) / 2.0 * 0.01 /* 1% */);
  }

  // --- 高調波は直交ビンに落ちて原理的に除去される ---
  // 3倍高調波(150Hz)を基本波と同程度の振幅で混ぜても、公称ちょうどのfreqHzは動かない。
  {
    gridfreq::GoertzelEstimator est(fNom, fs);
    const size_t winN = est.windowSamples();
    std::vector<int32_t> mixed(winN * 3);
    for (size_t i = 0; i < mixed.size(); ++i) {
      const double t = static_cast<double>(i) / fs;
      const double x = 1000.0 * std::sin(2.0 * M_PI * fNom * t) +
                        800.0 * std::sin(2.0 * M_PI * (3.0 * fNom) * t + 0.7);
      mixed[i] = static_cast<int32_t>(std::lround(x));
    }
    double lastFreq = 0.0;
    for (int32_t s : mixed) {
      if (est.addSample(s)) lastFreq = est.freqHz();
    }
    checkNear("3倍高調波を混ぜてもfreqHzは公称値のまま", lastFreq, fNom, 1e-6);
  }

  // --- resetWindow(): cyclesは巻き戻らないが、直後の窓は新しい基準点になる ---
  {
    gridfreq::GoertzelEstimator est(fNom, fs);
    const size_t winN = est.windowSamples();
    const auto tone = makeTone(fNom, fs, 1000.0, 0.0, winN * 2);
    for (int32_t s : tone) est.addSample(s);  // 2窓進める(基準+1回の更新)
    const uint64_t before = est.cyclesQ16();
    check("resetWindow前にcyclesが進んでいる", before > 0);

    est.resetWindow();
    check("resetWindow直後もcyclesは巻き戻らない", est.cyclesQ16() == before);

    // ギャップ相当で位相が飛んだ状態を模す(位相0.9πだけずらして再開)。
    const auto afterGap = makeTone(fNom, fs, 1000.0, 0.9 * M_PI, winN * 2);
    bool firstAfterResetTrue = est.addSample(afterGap[0]);
    for (size_t i = 1; i < winN; ++i) firstAfterResetTrue = est.addSample(afterGap[i]) || firstAfterResetTrue;
    check("resetWindow後の最初の窓は基準点(false)", !firstAfterResetTrue);
  }

  // --- 50/60Hz判別 ---
  {
    const size_t winN = static_cast<size_t>(fs + 0.5);
    const auto tone60 = makeTone(60.0, fs, 1000.0, 0.4, winN);
    checkNear("60Hzのトーンは60と判別される",
              gridfreq::detectNominalFreq(tone60.data(), tone60.size(), fs), 60.0, 0.0);
    const auto tone50 = makeTone(50.0, fs, 1000.0, 0.9, winN);
    checkNear("50Hzのトーンは50と判別される",
              gridfreq::detectNominalFreq(tone50.data(), tone50.size(), fs), 50.0, 0.0);
  }

  printf("\n%s (%d failure%s)\n", gFailures ? "FAILED" : "PASSED", gFailures,
         gFailures == 1 ? "" : "s");
  return gFailures ? 1 : 0;
}
