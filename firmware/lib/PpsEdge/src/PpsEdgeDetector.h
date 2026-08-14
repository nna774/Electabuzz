#pragma once
// R ch(PPS)の生サンプル列からエッジ位置をサブサンプル補間で検出する。→ docs/timebase.md
//
// **本クラスは「閾値を上向きに横切った点」を線形補間で求めるだけの薄い層。**
// timebase.mdが言う「帯域制限されたエッジは滑らかなランプになり、サンプル間補間が
// 数学的にwell-definedになる」を最小構成で実装したもの。出力(サブサンプル補間込みの
// サンプル位置)は `PpsTimebase::addEdge()` にそのまま渡せる形にしてある。
//
// **閾値の絶対値は未校正のプレースホルダである。** R ch AFE(→ docs/hardware.md
// 「GNSS(NEO-M8N) 配線」節)はまだ実配線していないため、実際のPPSパルスの振幅・
// 立ち上がり時定数は測定できていない。閾値は実データが取れてから較正すること
// （→ docs/open-questions.md）。ここで検証済みなのは「与えられた閾値に対する
// サブサンプル補間の算術が正しいこと」と「不応期・ヒステリシスが多重検出を防ぐこと」
// の2つだけであり、閾値の決めかた自体(固定値か適応か)は意図的にスコープ外にしてある。
//
// Arduino に依存しない。ホストの g++ でテストできる（test/run.sh）。

#include <cstdint>

namespace ppsedge {

class PpsEdgeDetector {
 public:
  // threshold: 立ち上がり検出の閾値(ADC生サンプル値と同じ単位)。未校正。
  // refractorySamples: 1回エッジを検出したら、次を検出できるまでの最小サンプル間隔。
  //   PPSは1Hzなので、サンプルレートよりだいぶ短い値(例: 半分の秒数相当)を渡す
  //   ——同じパルスの中でノイズに乗って再度閾値を跨いでも2発目として拾わないための
  //   保険。ヒステリシス(下抜けるまで再アームしない)だけでは、閾値ちょうど付近に
  //   ノイズが乗る場合を防ぎきれないため二重に持たせてある。
  PpsEdgeDetector(double threshold, uint64_t refractorySamples);

  // 1サンプル食わせる。閾値の上向き交差をサブサンプル補間で検出したら true を返し、
  // outTicks へ「補間込みのサンプル位置」を書く(0始まりの通し番号、小数可)。
  bool feed(double sample, double& outTicks);

  void reset();

 private:
  double threshold_;
  uint64_t refractorySamples_;

  uint64_t sampleIndex_ = 0;
  bool haveLast_ = false;
  double lastSample_ = 0.0;
  bool armed_ = true;  // 閾値を下回ってから再び上回るまで待つ(ヒステリシス)
  bool haveLastEdge_ = false;
  uint64_t lastEdgeIndex_ = 0;
};

}  // namespace ppsedge
