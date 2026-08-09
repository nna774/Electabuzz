#pragma once
// 累積位相(GoertzelEstimator::cyclesQ16())をLEDの色相(hue)へマップする。
// 母艦のオンボードWS2812(GPIO48)向け。正体の確定は
// docs/log/2026-08-09-led-button-hardware-probe.md を参照。
//
// Arduino に依存しない。ホストの g++ でテストできる（test/run.sh、他のlibと同じ形）。

#include <cstdint>

namespace ledstatus {

struct Rgb {
  uint8_t r;
  uint8_t g;
  uint8_t b;
};

// cyclesQ16: GoertzelEstimator::cyclesQ16()の生値をそのまま渡す。
//
// **1サイクル分の小数部(下位16bit)をそのままhueにする。実機のシンクロスコープ
// (同期検定器)と同じ見え方になる。** Goertzel.cppの実装上、cyclesAccum_は
// 窓ごとに「fNominalHz_*windowSec_(整数、例:50.0) + dphi/(2π)(実測とのずれ)」だけ
// 増える。**基準周波数ぴったりならdphi=0で整数しか足されないので小数部は
// 変化せず、色は静止する。周波数がずれている間だけ小数部が動き、色相が回る。**
// ずれの大きさが回転速度、ずれの向き(速い/遅い)が回転方向として見える——
// clampして振り切れさせる方式(旧設計)より、実機の計器に近い挙動になる。
//
// 彩度は常に最大。brightnessで明度を制御する(0〜255。常時点灯前提なので
// 眩しすぎない値を呼び出し側で選ぶこと)。
//
// gain: 回転速度の倍率。**素の対応(gain=1)は「1回転=1.0サイクルの累積ずれ」
// (50Hz系なら時刻偏差にして20ms相当)で、実系統は数十mHzオーダーでしかずれない
// ため回転がかなり遅い。** gainを掛けても数学的には壊れない——
// cyclesQ16は「fNominalHz*windowSec(整数)の階段 + 端数」の形をしているので、
// 整数gainを掛けても整数部は掛け算後も整数のまま(mod 65536で消える)。
// 掛かるのは端数の回転速度だけ。**小さいずれでも回転が体感できる速さまで
// gainで底上げしてよい**（→ docs/log/2026-08-09-led-status-feature.md）。
Rgb cyclesToColor(uint64_t cyclesQ16, uint8_t brightness = 15, uint32_t gain = 1);

}  // namespace ledstatus
