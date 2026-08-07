"""単一ビンDFT(Goertzel)による周波数・累積位相の推定。

`docs/signal-processing.md` のアルゴリズムそのまま:

    窓長 T = 1秒 (公称周波数の整数倍周期に一致)
    z(k) = Σ_n x[n]·exp(-j2π f_nom n / fs)
    φ(k) = arg z(k)
    Δφ   = unwrap(φ(k) - φ(k-1))
    cycles += f_nom·T + Δφ/2π

高調波は直交ビンに落ちて原理的に除去される(フィルタ設計に依存しない)。
**累積位相(`cycles`)が第一級のデータで、周波数はその微分(派生量)** ——
`docs/storage.md`の`cycles_q16`と同じ考え方。ここではfloat64で持つ
(firmwareのQ16固定小数点はC++移植時の話)。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def _wrap_to_pi(x: np.ndarray | float) -> np.ndarray | float:
    """(-pi, pi] へ折り返す。"""
    return (x + np.pi) % (2 * np.pi) - np.pi


@dataclass
class GoertzelResult:
    t_s: np.ndarray  # 各窓の終端時刻[秒](窓 k の終わり = (k+1)*window_sec)
    cycles: np.ndarray  # 累積サイクル数(絶対値、起点は最初の窓の頭)
    freq_hz: np.ndarray  # 各窓の瞬時周波数[Hz] = f_nom + Δφ/(2π·T)
    mag: np.ndarray  # |z(k)| (振幅の目安。0に近いと位相が定義できず信用できない)


def goertzel_cycles(samples: np.ndarray, fs: float, f_nom: float,
                     window_sec: float = 1.0) -> GoertzelResult:
    """全区間を`window_sec`秒ごとの窓に切り、各窓でf_nom近傍の複素相関を取って
    累積位相を積み上げる。**リアルタイム実装(firmware)は窓をオーバーラップさせず
    1個ずつ確定させていく想定**なのでここも同じ非オーバーラップで切る。
    """
    win_n = int(round(fs * window_sec))
    if win_n < 2:
        raise ValueError(f"window too short: fs={fs} window_sec={window_sec} -> win_n={win_n}")
    n_windows = len(samples) // win_n
    if n_windows < 2:
        raise ValueError(f"not enough samples for even 2 windows: n={len(samples)} win_n={win_n}")

    n = np.arange(win_n)
    coeff = np.exp(-1j * 2 * np.pi * f_nom * n / fs)

    t_out = np.empty(n_windows - 1)
    cycles_out = np.empty(n_windows - 1)
    freq_out = np.empty(n_windows - 1)
    mag_out = np.empty(n_windows - 1)

    prev_phase = None
    cycles = 0.0
    for k in range(n_windows):
        seg = samples[k * win_n:(k + 1) * win_n]
        z = np.sum(seg * coeff)
        phase = float(np.angle(z))
        mag = float(np.abs(z))

        if prev_phase is None:
            # 最初の窓は基準点として使うだけ(位相の絶対値そのものは意味を持たない
            # ——AC結合の位相原点は任意)。cyclesは0のまま、次の窓から積み上げる
            prev_phase = phase
            continue

        dphi = _wrap_to_pi(phase - prev_phase)
        prev_phase = phase
        cycles += f_nom * window_sec + dphi / (2 * np.pi)

        idx = k - 1
        t_out[idx] = k * window_sec + window_sec  # k番目の窓(0-indexed)の終端
        cycles_out[idx] = cycles
        freq_out[idx] = f_nom + dphi / (2 * np.pi * window_sec)
        mag_out[idx] = mag

    return GoertzelResult(t_s=t_out, cycles=cycles_out, freq_hz=freq_out, mag=mag_out)


def detect_nominal_freq(samples: np.ndarray, fs: float,
                         candidates: tuple[float, ...] = (50.0, 60.0),
                         window_sec: float = 1.0) -> float:
    """起動時の50/60Hz判別。**両ビンのパワー比較だけ**(→ signal-processing.md)。
    最初の1窓ぶんだけ使う——判別に長い区間は要らない。
    """
    win_n = int(round(fs * window_sec))
    if len(samples) < win_n:
        raise ValueError("not enough samples for even one window")
    seg = samples[:win_n]
    n = np.arange(win_n)
    best_f, best_mag = candidates[0], -1.0
    for f in candidates:
        coeff = np.exp(-1j * 2 * np.pi * f * n / fs)
        mag = abs(np.sum(seg * coeff))
        if mag > best_mag:
            best_f, best_mag = f, mag
    return best_f
