"""Goertzel参照実装(`tools/gridfreq/`)のバックテスト。

Namazu の `tools/backtest.py`(`tools/jismo/` を「単一の真実」として検証する)と
同じ位置付け(→ `docs/signal-processing.md`)。合成波形(既知周波数+高調波+ノイズ+
ドリフト)を食わせて、復元した周波数が既知の正解とどれだけ合うかを見る。

**目標精度は `docs/timebase.md` の ±1mHz。** 現実的な速さの周波数変動
(系統周波数の実際の揺らぎは分オーダーの時定数)ならこの精度に収まることを
合成波形で確認する。非現実的に速い変動(参考ケースとして残す)は精度が
落ちることも合わせて示す——**1秒窓のGoertzelは窓内平均を返す**という
性質そのものであり、バグではない。

使い方:
    python tools/backtest_gridfreq.py                    # 内蔵の合成ケースを流す
    python tools/backtest_gridfreq.py --csv capture.csv --fs 240 --f0 50  # 実キャプチャを解析
    python tools/gen_synthetic.py --f0 50.02 | python tools/backtest_gridfreq.py --csv - --fs 48000
"""

from __future__ import annotations

import argparse
import sys

import numpy as np

from gridfreq.goertzel import detect_nominal_freq, goertzel_cycles
from gen_synthetic import synth_grid


def load_csv(path: str) -> tuple[np.ndarray, float]:
    f = sys.stdin if path == "-" else open(path)
    with f:
        rows = []
        for line in f:
            if not line.strip() or line.startswith("#"):
                continue
            if line.startswith("t_us"):
                continue
            rows.append(line.split(","))
    a = np.array(rows, dtype=float)
    t_us = a[:, 0]
    fs = 1.0 / (np.median(np.diff(t_us)) / 1e6) if len(t_us) > 1 else 1000.0
    return a[:, 1], fs


class Case:
    def __init__(self, name: str, tol_max_mhz: float, tol_rms_mhz: float, assert_it: bool, **kw):
        self.name = name
        self.tol_max_mhz = tol_max_mhz
        self.tol_rms_mhz = tol_rms_mhz
        self.assert_it = assert_it
        self.kw = kw


CASES = [
    Case("定常(高調波+ノイズあり)", tol_max_mhz=0.5, tol_rms_mhz=0.3, assert_it=True,
         fs=48000.0, seconds=20.0, f0=50.02,
         harmonics=[(3, 0.15), (5, 0.08), (7, 0.04)], noise_rms=50_000.0, seed=1),
    Case("60Hz判別+定常", tol_max_mhz=0.5, tol_rms_mhz=0.3, assert_it=True,
         fs=48000.0, seconds=20.0, f0=59.97,
         harmonics=[(3, 0.1)], noise_rms=30_000.0, seed=2),
    Case("現実的な緩やかなドリフト(5分周期±0.05Hz)", tol_max_mhz=1.0, tol_rms_mhz=0.6, assert_it=True,
         fs=48000.0, seconds=300.0, f0=50.0,
         wobble_hz=0.05, wobble_period_s=300.0,
         harmonics=[(3, 0.1), (5, 0.05)], noise_rms=30_000.0, seed=3),
    # 参考: 系統では起きない速さの変動。1秒窓のGoertzelは窓内平均を返すので
    # ここまで速いと誤差が伸びる——設計の限界を示すための記録用で、閾値は緩め
    Case("参考: 非現実的に速い変動(20秒周期±0.08Hz)", tol_max_mhz=30.0, tol_rms_mhz=20.0, assert_it=False,
         fs=48000.0, seconds=60.0, f0=50.0,
         wobble_hz=0.08, wobble_period_s=20.0, seed=4),
]


def window_avg_truth(fs: float, n_samples: int, window_sec: float, f0: float,
                      drift_hz_per_s: float = 0.0, wobble_hz: float = 0.0,
                      wobble_period_s: float = 60.0) -> np.ndarray:
    """各窓の正解=区間平均瞬時周波数。最初の窓は基準用でGoertzel側の出力に
    含まれないので、こちらも先頭を落とす。"""
    win_n = int(round(fs * window_sec))
    t_full = np.arange(n_samples) / fs
    f_full = f0 + drift_hz_per_s * t_full
    if wobble_hz:
        f_full = f_full + wobble_hz * np.sin(2 * np.pi * t_full / wobble_period_s)
    n_windows = n_samples // win_n
    avg = np.array([f_full[k * win_n:(k + 1) * win_n].mean() for k in range(n_windows)])
    return avg[1:]


def run_case(case: Case) -> bool:
    sig, _ = synth_grid(
        fs=case.kw["fs"], seconds=case.kw["seconds"], f0=case.kw["f0"],
        amp=case.kw.get("amp", 1_000_000.0),
        harmonics=case.kw.get("harmonics"),
        drift_hz_per_s=case.kw.get("drift_hz_per_s", 0.0),
        wobble_hz=case.kw.get("wobble_hz", 0.0),
        wobble_period_s=case.kw.get("wobble_period_s", 60.0),
        noise_rms=case.kw.get("noise_rms", 0.0),
        seed=case.kw.get("seed", 0),
    )
    fs = case.kw["fs"]

    detected = detect_nominal_freq(sig, fs)
    res = goertzel_cycles(sig, fs, detected)

    truth = window_avg_truth(fs, len(sig), 1.0, case.kw["f0"],
                              drift_hz_per_s=case.kw.get("drift_hz_per_s", 0.0),
                              wobble_hz=case.kw.get("wobble_hz", 0.0),
                              wobble_period_s=case.kw.get("wobble_period_s", 60.0))
    n = min(len(res.freq_hz), len(truth))
    err_mhz = (res.freq_hz[:n] - truth[:n]) * 1000
    max_err = float(np.max(np.abs(err_mhz)))
    rms_err = float(np.sqrt(np.mean(err_mhz ** 2)))

    ok = max_err <= case.tol_max_mhz and rms_err <= case.tol_rms_mhz
    status = "OK" if ok else "NG"
    detect_note = f" (判別: {detected:.0f}Hz, 正解{case.kw['f0']:.0f}Hz近傍)" \
        if abs(detected - round(case.kw['f0'])) < 0.5 else f" (判別ミス: {detected:.0f}Hz)"
    print(f"[{status}] {case.name}: max={max_err:.4f}mHz(閾値{case.tol_max_mhz}) "
          f"rms={rms_err:.4f}mHz(閾値{case.tol_rms_mhz}){detect_note}"
          f"{'' if case.assert_it else '  [参考、判定対象外]'}")

    return ok if case.assert_it else True


def run_synthetic_suite() -> int:
    all_ok = True
    for case in CASES:
        if not run_case(case):
            all_ok = False
    return 0 if all_ok else 1


def run_csv(path: str, fs_arg: float | None, f0_arg: float | None) -> int:
    samples, fs_detected = load_csv(path)
    fs = fs_arg if fs_arg is not None else fs_detected
    print(f"# n={len(samples)} fs={fs:.3f}Hz(指定={'yes' if fs_arg else 'no、検出値'})",
          file=sys.stderr)

    f0 = f0_arg if f0_arg is not None else detect_nominal_freq(samples, fs)
    print(f"# f0={f0}Hz", file=sys.stderr)

    res = goertzel_cycles(samples, fs, f0)
    print("t_s,freq_hz,cycles,mag")
    for t, f, c, m in zip(res.t_s, res.freq_hz, res.cycles, res.mag):
        print(f"{t:.3f},{f:.6f},{c:.6f},{m:.1f}")
    print(f"# median={np.median(res.freq_hz):.4f}Hz std={np.std(res.freq_hz)*1000:.3f}mHz",
          file=sys.stderr)
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--csv", help="実キャプチャCSV(t_us,l,r)を解析する。'-'でstdin。"
                                  "省略時は内蔵の合成波形テストスイートを走らせる")
    p.add_argument("--fs", type=float, default=None, help="--csv用。省略時はタイムスタンプから検出")
    p.add_argument("--f0", type=float, default=None, help="--csv用。省略時は50/60Hz自動判別")
    args = p.parse_args()

    if args.csv:
        return run_csv(args.csv, args.fs, args.f0)
    return run_synthetic_suite()


if __name__ == "__main__":
    sys.exit(main())
