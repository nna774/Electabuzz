# バッチ境界の針ノイズ対策(PR #21)を実機・実クラウドへ投入し、効果を確認した

## 投入したこと

[2026-08-09-batch-boundary-jump-ntp-fix.md](2026-08-09-batch-boundary-jump-ntp-fix.md)の対策を実機・実クラウドへ反映した。

1. `terraform apply`(0 add/2 change/0 destroy、api+ingestのコードのみ更新)。
   `lambda/api/handler.py`の理論値dt化がクラウドに反映された
2. `pio run -e record -t upload`で実機に焼き直し(`NtpTimebase`の回帰原点
   ロールフォワードを含む)。VID:PID=1A86:55D3(CH343)で本機と確認
3. 起動確認: シリアルログで`# batch enqueue`を確認、S3(`series/`)への
   継続的な着弾も確認

## NTPロックを実機で確認した

`env:record`は起動直後は`timebase_source=NOMINAL`、`kMinObs=8`かつ
`kMinSpanSeconds=600`を満たした時点で`NTP`に切り替わる設計([docs/timebase.md](../timebase.md))。
S3の最新バッチを30秒間隔でポーリングし、`tb_obs_count`と`source_name`の
遷移を実機で追跡した——起動から約17分後、`tb_obs=8`で`NTP`にロックした
(`session_id=13`)ことを確認した。

## ロック直後のセッションで対策の効果を再検証した

[2026-08-09-batch-boundary-jump-ntp-fix.md](2026-08-09-batch-boundary-jump-ntp-fix.md)
で使ったのと同じ検証手法(境界の周波数と、境界前後の局所的な変動幅を比較し、
30mHz超の乖離を異常とみなす)を、ロック直後のセッション(`session_id=13`、
`tb_obs=8`〜`14`、34境界)に適用した。

| 方式 | 異常件数(局所平均から30mHz超) | 最大偏差 |
|---|---|---|
| 実測dt(旧) | 34件中**5件** | **29198.4mHz**(約29Hz) |
| 理論値dt(新) | 34件中**0件** | 5.9mHz(正常範囲) |

**旧方式はNTPロック直後、最大29Hzという桁違いの異常を起こしていた。**
`session_id=8`(2026-08-08、成熟した回帰)で見た最大244.5mHzよりも
さらに2桁大きい——おそらくNOMINAL→NTPの遷移点でバッチ起点の計算方法自体が
切り替わる(`timesync::nowUs()`ベース→`gFs.unixUsAt()`ベース)瞬間、
両者の値の差がそのままdtの分母に乗り、極端な値になったと考えられる。

新しい理論値dt方式は、この極端なケースを含めて完全に吸収し、**異常0件・
最大5.9mHzに収まった。** 前回の検証(成熟した回帰、session_id=8)よりも
今回(ロック直後・遷移直後、session_id=13)の方が対策の効果がより劇的に
表れた——効くべき場面(遷移直後の不安定な区間)でこそ最も効いている、
という結果になる。

## 何が可能になったか

[risks.md](../risks.md)リスク12は実機・実データの両面で解消を確認した。
firmware側のロールフォワード対策は今回のセッションでも同居しているが、
NOMINAL→NTP遷移点のような極端なケースまで含めて実質的にAPI側の
理論値dt化がバッチ境界問題を吸収し切っている。
