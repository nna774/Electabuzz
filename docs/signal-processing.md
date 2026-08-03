# 信号処理: 単一ビンDFT

ゼロクロス検出は採らない。日本の商用波形はスイッチング負荷で頂部が潰れており、
高調波でゼロクロス時刻が数十µs単位でジッタする。60Hz の1周期 16.7ms に 50µs の
ジッタが乗れば単発 180mHz 相当。平均化しても高調波は完全にランダムではないので
系統誤差が残る。

代わりに公称周波数ビンの複素相関(Goertzel / 単一ビンDFT)を使う。

```
窓長 T = 1秒 (公称周波数の整数倍周期に一致)
z(k) = Σ_n x[n]·exp(-j2π f_nom n / fs_measured)   … fs は PPS 規正後の実測値
φ(k) = arg z(k)
Δφ   = unwrap(φ(k) - φ(k-1))
cycles += f_nom·T + Δφ/2π
```

- 高調波は直交ビンに落ちるので**原理的に除去される**。フィルタ設計に依存しない
- 全サンプルが推定に寄与するので SNR がサンプル数分改善する
- **累積位相が unwrap の副産物として自然に出る。要求そのものが副産物になる**
- 50/60Hz 判別は起動時に両ビンのパワー比較だけ

ESP32-S3(240MHz, FPU)で 48kHz の単一ビン Goertzel は Core1 に十分収まる。

**既存の検証思想を踏襲する。** `tools/jismo/` を単一の真実として `tools/backtest.py` で
firmware C++ 実装と数値照合する構造([design.md](https://github.com/nna774/NamazuHaUrokoGaNai/blob/master/docs/design.md)
39-40行目「必ず FFT版と数値照合してから信用する」)をそのまま持ち込む。
`tools/gridfreq/` に Python 参照実装を置き、`tools/backtest_gridfreq.py` で
合成波形(既知周波数 + 高調波)を食わせて両実装の一致を担保する。
`tools/gen_synthetic.py` が既にあるので流用できる。

---

