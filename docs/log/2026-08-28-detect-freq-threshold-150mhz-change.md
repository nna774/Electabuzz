# 2026-08-28 detectの周波数逸脱閾値を100mHz→150mHzへ変更

## 経緯

[log/2026-08-28-detect-freq-threshold-backtest.md](2026-08-28-detect-freq-threshold-backtest.md)で
実データ(直近8日・22,933バッチ)をバックテストし、100mHz→150mHzでfreq_deviationイベントが
102件→2件(約98%減)になることを確認した。この結果を見てユーザーが実際の変更を判断した。

## 何をしたか

- `terraform/variables.tf`の`freq_deviation_threshold_hz`の`default`を`0.1`→`0.15`に変更
  （`terraform.tfvars`に個別指定は無く、この既定値がそのまま使われている）
- `docs/cloud.md`のdetectしきい値表の記述(既定100mHz)を150mHzに更新

## 状態

terraformのコードは変更したが、**`terraform apply`はまだ実行していない**。反映には
別途applyが要る。
