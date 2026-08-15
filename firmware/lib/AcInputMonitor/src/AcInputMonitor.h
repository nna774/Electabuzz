#pragma once
// AC入力(トランス→AFE)が「見えない」状態を検知する。→ docs/hardware.md「電源」節、
// docs/log/2026-08-12-afe-input-disconnect-detection.md
//
// 入力は `v_rms_mv`(main.cpp の computeVRmsMv() が GoertzelEstimator::magnitude() から
// 毎窓算出する、トランス二次側の実効値[mV])。C1実装後のAFEは断線時にnode AがR2経由で
// 低インピーダンスにGNDへ落ちて振幅ゼロへ静止する「素直な壊れ方」をする
// (回路解析済み、→ 上記log)ので、しきい値未満が続くことをそのまま「入力が見えない」の
// 判定に使える。
//
// **断線と停電はこの信号だけでは原理的に区別できない。** 無理に区別せず、
// 「AC入力が見えない」という二値状態だけを持つ。原因の切り分けは通知を受けた
// 人間が現地で判断する(→ 上記log の方針)。
//
// sustainWindows(呼び出し回数、時間ではない)ぶん連続してしきい値の同じ側に
// いないと状態を確定しない——ノイズ1窓での誤検知・チャタリングを防ぐための
// 対称なヒステリシス。呼び出し間隔は仮定しない(PpsEdgeDetectorと同じ理由)。
//
// **しきい値・sustainWindowsは実機の断線イベントで検証していない未校正の
// プレースホルダである**(→ config.h の kAcFaultVRmsThresholdMv /
// kAcFaultSustainWindows コメント)。次に実機で断線を再現できたら実測値で見直すこと。
//
// Arduino に依存しない。ホストの g++ でテストできる(test/run.sh、他のlibと同じ形)。

#include <cstdint>

namespace acinput {

class AcInputMonitor {
 public:
  // thresholdMv: これ未満を「断」候補とみなす v_rms_mv のしきい値。
  // sustainWindows: 状態を確定させるために必要な連続window数。**1以上を渡すこと**
  //   (0だと初回呼び出しで意味のない即時確定をしてしまう)。復帰判定にも同じ数を使う。
  AcInputMonitor(uint16_t thresholdMv, uint32_t sustainWindows);

  // 1window分のv_rms_mvを渡す。**状態が変化した(fault確定/復帰)瞬間だけ true を返す。**
  // 呼び出し側はこの戻り値をエッジ検出に使い、trueの時だけ通知を出せばよい。
  bool update(uint16_t vRmsMv);

  bool faulted() const { return faulted_; }

  void reset();

 private:
  uint16_t thresholdMv_;
  uint32_t sustainWindows_;
  uint32_t belowCount_ = 0;
  uint32_t aboveCount_ = 0;
  bool faulted_ = false;
};

}  // namespace acinput
