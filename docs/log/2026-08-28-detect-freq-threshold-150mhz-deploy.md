# 2026-08-28 detectの周波数逸脱閾値150mHzへの変更、apply・実クラウド確認まで完了

## 経緯

[log/2026-08-28-detect-freq-threshold-150mhz-change.md](2026-08-28-detect-freq-threshold-150mhz-change.md)
（PR #88）をユーザーがマージし、「マージしてデプロイして」の指示で反映した。

## やったこと

- `terraform plan`: `electabuzz-detect`の環境変数`ELBZ_FREQ_DEV_THRESHOLD_HZ`のみ
  `0.1`→`0.15`(0 add/1 change/0 destroy)。想定通りで他の差分は無かった
- `terraform apply -auto-approve`はAuto Modeの分類器に一度ブロックされ、ユーザーに
  「applyしていい？」と確認を取ってから実行した
- apply後、`aws lambda get-function-configuration --function-name electabuzz-detect`で
  `ELBZ_FREQ_DEV_THRESHOLD_HZ=0.15`が実際に反映されていることを確認した

## 状態

**detectの周波数逸脱閾値は150mHzで運用中。** 実際の逸脱事例での動作確認は今後の
実データ待ち（従来通り）。
