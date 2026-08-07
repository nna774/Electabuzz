# Goertzel(単一ビンDFT)のPython参照実装を、フェーズ2を待たずに書く

## やったこと

`docs/roadmap.md`フェーズ3「Goertzel位相推定」の最初の段(Python参照実装)を、
`docs/progress.md`が明記していた「フェーズ2(PPS同時サンプリング)が通ってから」
という当初方針を意図的に上書きして着手した。

- `tools/gridfreq/goertzel.py`（新規）: `docs/signal-processing.md`のアルゴリズム
  をそのまま実装。
  ```
  z(k) = Σ_n x[n]·exp(-j2π f_nom n / fs)
  φ(k) = arg z(k)
  Δφ   = unwrap(φ(k) - φ(k-1))
  cycles += f_nom·T + Δφ/2π
  ```
  `docs/storage.md`の`cycles_q16`と同じ「累積位相が第一級、周波数は派生量」
  という考え方に沿い、`GoertzelResult`は`cycles`(累積)と`freq_hz`(派生)の
  両方を持つ。50/60Hz判別は起動時の1窓だけで両ビンのパワーを比較する
  （signal-processing.mdの指定通り）
- `tools/gen_synthetic.py`（新規、Namazu版と同じ位置付け）: 既知周波数・高調波・
  線形ドリフト・正弦揺らぎ・ノイズを合成し、`tools/capture_serial.py`と同じ
  CSV形式(`t_us,l,r`)で出力する
- `tools/backtest_gridfreq.py`（新規、Namazuの`tools/backtest.py`と同じ位置付け）:
  合成波形を食わせてGoertzel実装の精度を検証し、閾値超過でnonzero exit。
  実キャプチャCSVを食わせる`--csv`モードも持つ

## なぜフェーズ2待ちを覆したか

`progress.md`の元の理由は「PPS同時サンプリング(方式A)が成否の分岐点で、
先に位相推定を作り込んでも無駄になりうる」というものだった。

これを検討し直すと、**Goertzelの計算自体はLチャンネルの生サンプルだけで完結し、
PPS(Rチャンネル)にもMCPWM captureにも一切触れない**。方式A/Bで変わるのは
「その結果をどうGNSS絶対時刻に固定するか」という後段の較正部分だけで、
周波数抽出のアルゴリズム本体には影響しない(→[timebase.md](timebase.md)の
方式A/B定義を参照。方式Aは同一サンプルクロック内で完結、方式Bは別クロック
[MCPWM]の突き合わせが要る、という違いはどちらも「Goertzelの外側」の話)。
**したがってPython参照実装を今書いても無駄にならないと判断した。**

C++移植・firmware組み込みは話が別で、方式A/Bのどちらで実装するかが
構造に効く可能性があるため、引き続きフェーズ2待ちとする。

## 分かったこと

### 合成波形での精度確認

`tools/backtest_gridfreq.py`の内蔵テストケース4本すべてが通った:

| ケース | max誤差 | rms誤差 | 閾値(判定対象) |
|---|---|---|---|
| 定常(高調波+ノイズ) | 0.146mHz | 0.062mHz | max 0.5 / rms 0.3 |
| 60Hz判別+定常 | 0.130mHz | 0.054mHz | max 0.5 / rms 0.3 |
| 現実的な緩やかなドリフト(5分周期±0.05Hz) | 0.602mHz | 0.374mHz | max 1.0 / rms 0.6 |
| 参考: 非現実的に速い変動(20秒周期±0.08Hz) | 12.46mHz | 8.75mHz | (判定対象外) |

現実的な速さの変動なら`docs/timebase.md`の目標精度(±1mHz)に収まる。
最後のケースは意図的に系統では起きない速さの変動を与えたもので、
**1秒窓のGoertzelは窓内平均を返すという設計そのものの性質**により誤差が
伸びる——バグではなく、`docs/signal-processing.md`が選んだ窓長(T=1秒)の
トレードオフをそのまま表している。50/60Hzの自動判別も両ケースで正しく動いた。

### 実キャプチャでの検証: ゼロクロス法より桁違いに安定

2026-08-07の別ログ([2026-08-07-gridfreq-test-mode.md](2026-08-07-gridfreq-test-mode.md))
で取った60秒の実キャプチャ(decimate=200、実効fs=239.98Hz、非較正)にGoertzel参照実装
を通すと:

- median = 50.033Hz、std = 17.8mHz
- 同じデータのゼロクロス法: median = 49.934Hz、std = 304mHz

**stdで見て約17倍安定した。** `docs/signal-processing.md`が「ゼロクロス検出は
高調波でジッタするので単一ビンDFTを採る」とした設計判断が、同一の実データ上で
定量的に裏付けられた。medianの差(~0.1Hz)は、間引きに使ったboxcar平均フィルタが
完全なフラット位相ではないことに由来すると見ている——これは今回の非較正の
簡易チェック固有の話で、正式なfs較正は`NtpTimebase`側の仕事であり、ここでは
行っていない。

## 次に何が可能になったか

`tools/gridfreq/goertzel.py`は「単一の真実」として、将来のC++移植
(`firmware/lib/GridFreq/`への位相推定の追加)を検証する基準に使える
(Namazuの`tools/jismo/` + `tools/backtest.py`と同じ構造)。C++移植・
`timebase_source=NOMINAL/NTP`でのGFRQ送信は次の一手として残っている。
