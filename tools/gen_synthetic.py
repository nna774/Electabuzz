"""合成グリッド波形の生成(Goertzel参照実装のテスト・デモ用)。

Namazu の `tools/gen_synthetic.py`(加速度計版)と同じ位置付け。
CSV形式は `tools/capture_serial.py` と同じ `t_us,l,r`(r は常に0、未接続想定)。

使い方:
    python tools/gen_synthetic.py --f0 50.02 --harmonics 3:0.05,5:0.03 --seconds 120 > synth.csv
    python tools/gen_synthetic.py --wobble-hz 0.05 --wobble-period 30 --seconds 300 > synth.csv
"""

from __future__ import annotations

import argparse
import sys

import numpy as np


def synth_grid(fs: float, seconds: float, f0: float = 50.0, amp: float = 1_000_000.0,
                harmonics: list[tuple[int, float]] | None = None,
                drift_hz_per_s: float = 0.0,
                wobble_hz: float = 0.0, wobble_period_s: float = 60.0,
                noise_rms: float = 0.0, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """商用波形っぽい合成信号を作る。

    返り値: (signal, f_inst) — f_inst は各サンプル時点の瞬時周波数[Hz](正解値)。
    位相は瞬時周波数を累積(cumsum)して作る——`drift`/`wobble`ありでも
    位相が連続になるようにするため(単純にf(t)を積分せず離散和で済ませる。
    fsに対して十分細かいので誤差は無視できる)。
    """
    n = int(fs * seconds)
    t = np.arange(n) / fs
    f_inst = f0 + drift_hz_per_s * t
    if wobble_hz:
        f_inst = f_inst + wobble_hz * np.sin(2 * np.pi * t / wobble_period_s)

    phase = 2 * np.pi * np.cumsum(f_inst) / fs
    sig = amp * np.sin(phase)

    if harmonics:
        for h, rel in harmonics:
            sig = sig + amp * rel * np.sin(h * phase)

    if noise_rms:
        rng = np.random.default_rng(seed)
        sig = sig + rng.standard_normal(n) * noise_rms

    return sig, f_inst


def parse_harmonics(s: str | None) -> list[tuple[int, float]] | None:
    """'3:0.05,5:0.03' -> [(3,0.05),(5,0.03)]"""
    if not s:
        return None
    out = []
    for part in s.split(","):
        h, rel = part.split(":")
        out.append((int(h), float(rel)))
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--fs", type=float, default=48000.0, help="サンプルレート[Hz]")
    p.add_argument("--seconds", type=float, default=120.0)
    p.add_argument("--f0", type=float, default=50.0, help="基本周波数[Hz]")
    p.add_argument("--amp", type=float, default=1_000_000.0, help="基本波の振幅(ADCコード相当)")
    p.add_argument("--harmonics", type=str, default=None,
                   help="'3:0.05,5:0.03' の形で高調波次数:相対振幅をカンマ区切り")
    p.add_argument("--drift-hz-per-s", type=float, default=0.0, help="線形ドリフト[Hz/s]")
    p.add_argument("--wobble-hz", type=float, default=0.0, help="周波数の正弦揺らぎ振幅[Hz]")
    p.add_argument("--wobble-period", type=float, default=60.0, help="揺らぎの周期[秒]")
    p.add_argument("--noise-rms", type=float, default=0.0, help="加算ホワイトノイズのRMS")
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args()

    sig, f_inst = synth_grid(args.fs, args.seconds, f0=args.f0, amp=args.amp,
                              harmonics=parse_harmonics(args.harmonics),
                              drift_hz_per_s=args.drift_hz_per_s,
                              wobble_hz=args.wobble_hz, wobble_period_s=args.wobble_period,
                              noise_rms=args.noise_rms, seed=args.seed)

    print(f"# synthetic: fs={args.fs} f0={args.f0} harmonics={args.harmonics} "
          f"drift={args.drift_hz_per_s}Hz/s wobble={args.wobble_hz}Hz/{args.wobble_period}s "
          f"noise_rms={args.noise_rms} mean_f={f_inst.mean():.6f}Hz", file=sys.stderr)

    # 1行ずつのprintだと数百万サンプルで遅すぎるのでベクトル化する
    n = len(sig)
    t_us = np.round(np.arange(n) * 1e6 / args.fs).astype(np.int64)
    l_code = np.round(sig).astype(np.int64)
    r_code = np.zeros(n, dtype=np.int64)
    out = np.column_stack([t_us, l_code, r_code])

    print("t_us,l,r")
    np.savetxt(sys.stdout, out, fmt="%d", delimiter=",")
    return 0


if __name__ == "__main__":
    sys.exit(main())
