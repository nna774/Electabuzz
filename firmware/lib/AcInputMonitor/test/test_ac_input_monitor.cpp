// AcInputMonitor(v_rms_mvのしきい値監視でAC入力断を検知するステートマシン)のテスト。
// Arduinoに依存しないのでホストのg++で走る。

#include <cstdio>

#include "AcInputMonitor.h"

static int gFailures = 0;

static void check(const char* name, bool ok) {
  printf("%s %s\n", ok ? "ok  " : "FAIL", name);
  if (!ok) ++gFailures;
}

int main() {
  // --- 1. しきい値未満が sustainWindows 回続くまでは fault にならない ---
  {
    acinput::AcInputMonitor mon(/*thresholdMv=*/1000, /*sustainWindows=*/3);
    bool changed1 = mon.update(100);  // below, 1回目
    bool changed2 = mon.update(100);  // below, 2回目
    check("1回目は状態変化なし", !changed1 && !mon.faulted());
    check("2回目もまだ確定しない", !changed2 && !mon.faulted());
  }

  // --- 2. 3回目の連続below でfault確定し、そのwindowだけtrueを返す ---
  {
    acinput::AcInputMonitor mon(1000, 3);
    mon.update(100);
    mon.update(100);
    const bool changed = mon.update(100);  // 3回目で確定
    check("sustainWindows回連続でfault確定", changed && mon.faulted());
    const bool changedAgain = mon.update(100);  // 確定後の継続はエッジではない
    check("確定後の継続はエッジを返さない", !changedAgain && mon.faulted());
  }

  // --- 3. 連続していなければ確定しない(1回above を挟むとカウントがリセットされる) ---
  {
    acinput::AcInputMonitor mon(1000, 3);
    mon.update(100);  // below 1
    mon.update(100);  // below 2
    mon.update(5000); // above — リセット
    const bool changed = mon.update(100);  // below 1(振り出しに戻る)
    check("途中でaboveを挟むとカウントがリセットされる", !changed && !mon.faulted());
  }

  // --- 4. 復帰も同じsustainWindows回のヒステリシスを要求する ---
  {
    acinput::AcInputMonitor mon(1000, 3);
    mon.update(100);
    mon.update(100);
    mon.update(100);  // fault確定
    check("fault確定を確認", mon.faulted());

    const bool c1 = mon.update(5000);  // above 1
    const bool c2 = mon.update(5000);  // above 2
    check("復帰1回目はまだ確定しない", !c1 && mon.faulted());
    check("復帰2回目もまだ確定しない", !c2 && mon.faulted());
    const bool c3 = mon.update(5000);  // above 3 — 復帰確定
    check("sustainWindows回連続で復帰確定", c3 && !mon.faulted());
  }

  // --- 5. ちょうどthresholdMv(境界値)は「未満ではない」= above扱い ---
  {
    acinput::AcInputMonitor mon(1000, 1);
    const bool changed = mon.update(1000);  // ちょうどしきい値
    check("しきい値ちょうどはfaultにならない", !changed && !mon.faulted());
  }

  // --- 6. reset()で内部カウントとfault状態が初期化される ---
  {
    acinput::AcInputMonitor mon(1000, 2);
    mon.update(100);
    mon.update(100);  // fault確定
    check("resetを試す前にfault確定を確認", mon.faulted());
    mon.reset();
    check("reset直後はfaultedがfalse", !mon.faulted());
    const bool changed = mon.update(100);  // resetされていればまだ確定しない(1回目)
    check("reset後はカウントも振り出しに戻る", !changed && !mon.faulted());
  }

  // --- 7. sustainWindows=1なら1回のbelowで即fault確定する ---
  {
    acinput::AcInputMonitor mon(1000, 1);
    const bool changed = mon.update(100);
    check("sustainWindows=1なら1回で確定", changed && mon.faulted());
  }

  if (gFailures == 0) {
    printf("all tests passed\n");
    return 0;
  }
  printf("%d test(s) failed\n", gFailures);
  return 1;
}
