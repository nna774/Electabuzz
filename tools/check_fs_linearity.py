"""NOMINAL区間(fs未規正)のGoertzel出力を後からスカラー補正で戻せるか、線形性を確認する。

→ `docs/open-questions.md`「NOMINAL区間の扱い」の検証。案A/B(NTPロック後に補正を
適用する設計)はどちらも「fsが間違っていたときのGoertzel出力は、真のfsが分かった
時点でスカラー1個掛ければ戻る」という前提に乗っている。ここではその前提を、
既知のppm誤差を注入して確かめる。実機・firmware不要。

手法: 真の系統周波数を50.000Hz固定とし、物理サンプルレート
`fs_true = 48000 * (1 + eps_ppm * 1e-6)` で正弦波を生成する。
firmwareはfs未規正のあいだ「1秒 = 48000サンプル」と決め打ちして窓を切るので、
それと同じく`goertzel_cycles(..., fs=48000)`(nominal、わざと間違った値)を渡す。
出力`freq_hz`の平均と真値50.000Hzの差が系統誤差(bias)。epsを広く振って
biasに対して線形回帰し、残差(=線形近似で説明できない分)を見る。

使い方:
    python tools/check_fs_linearity.py
"""

from __future__ import annotations

import numpy as np

from gridfreq.goertzel import goertzel_cycles

FS_NOMINAL = 48000.0
F_TRUE = 50.000  # 系統の真の周波数(固定。fs誤差だけを見る)
DURATION_S = 60.0  # 60秒ぶん(=60窓)。NTPロック閾値600秒よりは短いが傾向を見るには十分
EPS_VALUES_PPM = (-1000, -500, -200, -100, -50, -20, -10, 0, 10, 20, 50, 100, 200, 500, 1000)


def measure_bias_hz(eps_ppm: float) -> float:
    fs_true = FS_NOMINAL * (1.0 + eps_ppm * 1e-6)
    n = int(round(fs_true * DURATION_S))
    t = np.arange(n) / fs_true  # 物理時間軸(本物のサンプル間隔)
    x = np.sin(2 * np.pi * F_TRUE * t)
    # 規正前のfirmwareは fs_nominal を「fsだ」と思って計算する
    result = goertzel_cycles(x, fs=FS_NOMINAL, f_nom=50.0, window_sec=1.0)
    return float(np.mean(result.freq_hz)) - F_TRUE


def main() -> None:
    eps_arr = np.array(EPS_VALUES_PPM, dtype=float)
    bias_mhz = np.array([measure_bias_hz(eps) * 1000 for eps in EPS_VALUES_PPM])

    print(f"{'eps(ppm)':>10} {'bias(mHz)':>12}")
    for eps, bias in zip(EPS_VALUES_PPM, bias_mhz):
        print(f"{eps:>10} {bias:>12.4f}")

    # 線形回帰(最小二乗)で傾き・切片・決定係数・残差を出す
    a = np.vstack([eps_arr, np.ones_like(eps_arr)]).T
    slope, intercept = np.linalg.lstsq(a, bias_mhz, rcond=None)[0]
    pred = slope * eps_arr + intercept
    ss_res = np.sum((bias_mhz - pred) ** 2)
    ss_tot = np.sum((bias_mhz - np.mean(bias_mhz)) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    max_abs_residual = float(np.max(np.abs(bias_mhz - pred)))

    print()
    print(f"線形回帰: bias[mHz] = {slope:.6f} * eps[ppm] + {intercept:.6f}")
    print(f"R^2 = {r2:.8f}")
    print(f"最大残差 = {max_abs_residual:.6f} mHz "
          f"(目標精度は±1mHzなので、これがそれより十分小さいかが線形補正の妥当性の目安)")


if __name__ == "__main__":
    main()
