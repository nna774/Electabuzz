# 2026-08-28 detectの周波数逸脱閾値、実データでのバックテスト

## 経緯

2026-08-22([log/2026-08-22-slack-webhook-setup.md](2026-08-22-slack-webhook-setup.md))の時点で
「既定100mHz、実データで1日数件発火」を確認し様子見と判断していた。その後
「けっこう出すぎな気がする」という指摘を受け、150mHzに上げるとどれだけ減るかを
実データで確かめた。

## 何をしたか

新規ツール[tools/backtest_detect_thresholds.py](../../tools/backtest_detect_thresholds.py)を作成。
`series/`の実バッチを取得し、`lambda/common/grid_detect.analyze`(副作用の無い純粋関数)へ
`freq_dev_threshold_hz`だけを変えて複数回流し、確定した`freq_deviation`イベント数を比較する
（`grid_detect.analyze`を運用中のLambdaに触らず再利用できる設計だったので、既存の解析ロジックを
複製せずそのまま流用できた）。RoCoF・電圧異常は今回の比較対象外なので、絶対に発火しない値
（`voltage_dev_fraction=1.0`・`rocof_threshold_hz_per_s=10**9`等）で無効化した。

対象は実機device 1、直近192時間(8日、2026-08-14 05:42〜2026-08-28 05:42 UTC)、
22,933バッチ全件（`hold_records`は既定の3で固定）。

## 結果

| 閾値 | freq_deviationイベント件数 | 延べ継続時間 |
|---|---|---|
| 100mHz(現行既定) | 102件 | 2531秒 |
| 120mHz | 40件 | 737秒 |
| 150mHz | 2件 | 65秒 |
| 200mHz | 0件 | 0秒 |

ピーク値の上位は 192.8 / 169.4 / 146.2 / 146.0 / 144.2 mHz……で、150mHzを超える逸脱は
この8日間で2件しかない。100mHz→150mHzへの変更でイベント数は**102件→2件（約98%減）**になる。

## 判断

**まだterraformの既定値(`freq_deviation_threshold_hz`)は変更していない。** 実データでの
効果は確認できたが、実際にどこへ設定するかはユーザー判断待ち——本ログは調査結果の記録のみ。
