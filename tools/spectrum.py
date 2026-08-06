"""キャプチャCSVからグリッド周波数の粗いチェックをする(フェーズ1の疎通確認用)。

**これはフェーズ3のGoertzel位相推定の代わりではない。** ここで使うゼロクロス法は
単純だが高調波ノイズに弱く、TE級の精度を主張できるものでもない
(→ docs/signal-processing.mdでゼロクロスを採らない理由を参照)。
「配線した信号がだいたい50Hzに見えるか」を確認するためだけの使い捨てツール。

    python tools/spectrum.py cap.csv --out-json freq_series.json
"""

from __future__ import annotations

import argparse
import json
import sys

import numpy as np


def load_csv(path: str):
    f = sys.stdin if path == "-" else open(path)
    with f:
        f.readline()  # header
        rows = [line.split(",") for line in f if line.strip() and not line.startswith("#")]
    a = np.array(rows, dtype=float)
    t_us = a[:, 0]
    fs = 1.0 / (np.median(np.diff(t_us)) / 1e6) if len(t_us) > 1 else 1000.0
    return t_us, a[:, 1], a[:, 2], fs


def zero_crossing_freq(t_us: np.ndarray, sig: np.ndarray):
    """立ち上がりゼロクロスの間隔から瞬時周波数の時系列を作る。線形補間で交点の
    時刻をサブサンプル精度に寄せる(整数サンプル境界の量子化誤差を減らすだけで、
    高精度化が目的ではない)。"""
    x = sig - np.mean(sig)
    sign = x >= 0
    rising = np.where((~sign[:-1]) & sign[1:])[0]  # 負→正の遷移点index
    if len(rising) < 2:
        return np.array([]), np.array([])

    # 線形補間でゼロ交差の厳密時刻を求める
    t0 = t_us[rising]
    t1 = t_us[rising + 1]
    x0 = x[rising]
    x1 = x[rising + 1]
    frac = -x0 / (x1 - x0)
    t_cross = (t0 + frac * (t1 - t0)) / 1e6  # 秒

    periods = np.diff(t_cross)
    freqs = 1.0 / periods
    t_mid = (t_cross[:-1] + t_cross[1:]) / 2.0
    return t_mid, freqs


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("csv")
    p.add_argument("--top", type=int, default=6)
    p.add_argument("--band", type=float, nargs=2, default=[40.0, 60.0],
                   help="基本波を探すバンド(Hz)")
    p.add_argument("--out-json", help="ゼロクロス周波数系列とスペクトルをJSONで書き出す")
    args = p.parse_args()

    t_us, l, r, fs = load_csv(args.csv)
    n = len(l)
    print(f"# samples={n} effective_fs={fs:.2f}Hz (デシメーション由来、非較正)")

    for name, sig in (("l", l), ("r", r)):
        sig_ac = sig - np.mean(sig)
        rms = np.sqrt(np.mean(sig_ac ** 2))
        freqs = np.fft.rfftfreq(n, 1.0 / fs)
        spec = np.abs(np.fft.rfft(sig_ac)) / n
        spec_for_peak = spec.copy()
        spec_for_peak[0] = 0
        idx = np.argsort(spec_for_peak)[::-1][:args.top]
        idx = np.sort(idx)
        peaks = ", ".join(f"{freqs[k]:.2f}Hz(mag={spec[k]:.1f})" for k in idx)
        print(f"{name}: RMS={rms:.1f}code  卓越周波数: {peaks}")

    # 基本波(バンド内最大)とTHD
    band_lo, band_hi = args.band
    freqs = np.fft.rfftfreq(n, 1.0 / fs)
    spec_l = np.abs(np.fft.rfft(l - np.mean(l)))
    band_mask = (freqs >= band_lo) & (freqs <= band_hi)
    if not band_mask.any():
        print(f"# {band_lo}-{band_hi}Hz帯にビンが無い(サンプル数不足)。--secondsを増やして再取得しろ",
              file=sys.stderr)
        f0 = None
    else:
        f0_idx = np.argmax(spec_l * band_mask)
        f0 = freqs[f0_idx]
        fundamental_mag = spec_l[f0_idx]
        harmonics_energy = 0.0
        for h in range(2, 8):
            target = f0 * h
            if target >= freqs[-1]:
                break
            hidx = np.argmin(np.abs(freqs - target))
            harmonics_energy += spec_l[hidx] ** 2
        thd = (np.sqrt(harmonics_energy) / fundamental_mag * 100) if fundamental_mag > 0 else float("nan")
        print(f"# 基本波(L, {band_lo}-{band_hi}Hz帯内最大): {f0:.3f}Hz  THD(2-7次)={thd:.1f}%")

    t_mid, zc_freqs = zero_crossing_freq(t_us, l)
    if len(zc_freqs) > 0:
        # バンド内だけ残す(高調波・ノイズによる異常な交差を弾く粗いフィルタ)
        band_ok = (zc_freqs >= band_lo) & (zc_freqs <= band_hi)
        kept = band_ok.sum()
        print(f"# ゼロクロス周波数: n={len(zc_freqs)} (バンド内{kept}件) "
              f"median={np.median(zc_freqs[band_ok]) if kept else float('nan'):.3f}Hz "
              f"std={np.std(zc_freqs[band_ok]) if kept else float('nan'):.4f}Hz")
    else:
        print("# ゼロクロスが検出できなかった(信号が小さすぎるかDCに寄っている)")

    if args.out_json:
        out = {
            "effective_fs_hz": fs,
            "n_samples": n,
            "fundamental_hz": f0,
            "spectrum_l": {"freqs": freqs.tolist(), "mag": spec_l.tolist()},
            "zero_crossing": {"t_s": t_mid.tolist(), "freq_hz": zc_freqs.tolist()},
        }
        with open(args.out_json, "w") as f:
            json.dump(out, f)
        print(f"# wrote {args.out_json}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
