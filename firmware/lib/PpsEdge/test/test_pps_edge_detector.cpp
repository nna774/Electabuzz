// PpsEdgeDetector(閾値の上向き交差をサブサンプル線形補間で検出する層)のテスト。
// Arduinoに依存しないのでホストのg++で走る。実際のPPSパルス波形(振幅・時定数)は
// R ch AFEを実配線するまで分からないので、ここで検証するのは「与えられた波形に対して
// 補間の算術・不応期・ヒステリシスが正しく働くか」だけである
// （→ docs/log/2026-08-12-gnss-pps-wiring-plan.md「アンテナが無くても進められる作業」）。

#include <cmath>
#include <cstdint>
#include <cstdio>
#include <vector>

#include "PpsEdgeDetector.h"

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

// 決定的な擬似乱数。ノイズを乗せてもテストが再現可能であるように。
struct Lcg {
  uint64_t s = 88172645463325252ULL;
  double next() {  // [-1, 1)
    s = s * 6364136223846793005ULL + 1442695040888963407ULL;
    return static_cast<double>(static_cast<int32_t>(s >> 33)) / 2147483648.0;
  }
};

// period samples ごとに1発、rampStart から rampSamples かけて 0→amplitude へ
// 直線的に立ち上がり、holdSamples 保持したあと fallSamples かけて 0 へ戻る
// パルス列を作る。それ以外は noiseAmp 以下の小さいノイズ(baseline)。
static std::vector<double> synthesize(int periods, int period, int rampStart, int rampSamples,
                                       int holdSamples, int fallSamples, double amplitude,
                                       double noiseAmp, Lcg& rng) {
  std::vector<double> out(static_cast<size_t>(periods) * period, 0.0);
  for (int p = 0; p < periods; ++p) {
    const int base = p * period;
    for (int i = 0; i < period; ++i) {
      double v = noiseAmp * rng.next();
      const int rel = i - rampStart;
      if (rel >= 0 && rel < rampSamples) {
        v = amplitude * static_cast<double>(rel) / static_cast<double>(rampSamples);
      } else if (rel >= rampSamples && rel < rampSamples + holdSamples) {
        v = amplitude;
      } else if (rel >= rampSamples + holdSamples && rel < rampSamples + holdSamples + fallSamples) {
        const int fi = rel - rampSamples - holdSamples;
        v = amplitude * (1.0 - static_cast<double>(fi) / static_cast<double>(fallSamples));
      }
      out[static_cast<size_t>(base + i)] = v;
    }
  }
  return out;
}

int main() {
  // --- 1. 単発の立ち上がりで、閾値交差点をサブサンプル補間で正しく求めるか ---
  {
    // rampStart=500, 振幅1000を10サンプルで直線的に立ち上げる(1サンプルあたり100)。
    // 閾値450なら、400(i=4)と500(i=5)の間、frac=0.5でindex=504.5になるはず。
    Lcg rng;
    auto wave = synthesize(1, 2000, 500, 10, 200, 10, 1000.0, 0.0, rng);
    ppsedge::PpsEdgeDetector det(450.0, 500);
    int edges = 0;
    double lastTicks = 0.0;
    for (size_t i = 0; i < wave.size(); ++i) {
      double ticks;
      if (det.feed(wave[i], ticks)) {
        ++edges;
        lastTicks = ticks;
      }
    }
    check("単発パルスで1回だけ検出する", edges == 1);
    checkNear("サブサンプル補間の位置が正しい", lastTicks, 504.5, 1e-9);
  }

  // --- 2. 複数周期で、周期どおりの間隔で毎回検出するか ---
  {
    Lcg rng;
    const int period = 1000;
    const int periods = 5;
    auto wave = synthesize(periods, period, 500, 10, 100, 10, 1000.0, 5.0, rng);
    ppsedge::PpsEdgeDetector det(450.0, period / 2);
    std::vector<double> detected;
    for (size_t i = 0; i < wave.size(); ++i) {
      double ticks;
      if (det.feed(wave[i], ticks)) detected.push_back(ticks);
    }
    check("周期数ぶんちょうど検出する", detected.size() == static_cast<size_t>(periods));
    bool spacingOk = true;
    for (size_t i = 1; i < detected.size(); ++i) {
      if (std::fabs((detected[i] - detected[i - 1]) - period) > 1.0) spacingOk = false;
    }
    check("検出間隔が周期どおり(±1サンプル)", spacingOk);
  }

  // --- 3. パルス直後のノイズによる再交差を不応期が抑えるか ---
  {
    Lcg rng;
    auto wave = synthesize(1, 2000, 500, 10, 50, 10, 1000.0, 0.0, rng);
    // 立ち上がり直後(index 520付近、まだhold中)にノイズで閾値をまたぐ
    // ような二重交差を人工的に挿入するのは無意味(hold中はホールド値のまま
    // 閾値を上回り続けるため)。代わりに「立ち下がり後、次のパルスが来るまでの
    // 間」に閾値近くまで戻る小さな跳ねを入れ、不応期が無ければ誤検出しうる状況を作る。
    wave[600] = 460.0;  // 立ち下がり(index 510+10+50+10=580で0に戻った後)のノイズ跳ね
    ppsedge::PpsEdgeDetector det(450.0, 500);
    int edges = 0;
    for (size_t i = 0; i < wave.size(); ++i) {
      double ticks;
      if (det.feed(wave[i], ticks)) ++edges;
    }
    check("不応期内の跳ねは2発目として数えない", edges == 1);
  }

  // --- 4. reset()で状態が完全に初期化されるか ---
  {
    Lcg rng;
    auto wave1 = synthesize(1, 1000, 300, 10, 50, 10, 1000.0, 0.0, rng);
    ppsedge::PpsEdgeDetector det(450.0, 100);
    for (double v : wave1) {
      double ticks;
      det.feed(v, ticks);
    }

    det.reset();

    // reset後は新しいサンプル列の先頭からインデックスが振り直されるはず。
    auto wave2 = synthesize(1, 1000, 100, 10, 50, 10, 1000.0, 0.0, rng);
    double firstEdgeTicks = -1.0;
    for (size_t i = 0; i < wave2.size(); ++i) {
      double ticks;
      if (det.feed(wave2[i], ticks)) {
        firstEdgeTicks = ticks;
        break;
      }
    }
    // rampStart=100, 立ち上がりは104.5付近(1のケースと同じ計算)。
    checkNear("reset後はインデックスが振り直される", firstEdgeTicks, 104.5, 1e-9);
  }

  if (gFailures == 0) {
    printf("all tests passed\n");
    return 0;
  }
  printf("%d test(s) failed\n", gFailures);
  return 1;
}
