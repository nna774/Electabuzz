# フェーズ2(PPS)のsoak確認: 27時間超・再起動ゼロでロック100%を実測、クローズ

## 経緯

dashboardのキャプション修正([log/2026-08-17-dashboard-pps-caption-fix.md](2026-08-17-dashboard-pps-caption-fix.md))
の過程で、フェーズ2の残タスクが「長時間soak確認」の1点だけになっていた。`/recent` API
(`lambda/api/handler.py`)は`MAX_RECENT_MINUTES=30`が上限で数時間分は一度に見えないため、
`series/`を直接読んでチェックする `tools/check_pps_soak.py` を新規に書いた。

## `tools/check_pps_soak.py`

`tools/README.md`の「何度も条件を変えて解析するときのS3キャッシュ」規約に従い、
`get_object`だけ`.s3cache/`でキャッシュし(`series/`は永久保存前提なので腐らない)、
`list_objects_v2`は新着を見逃さないよう毎回本物のS3へ通す。期間内のバッチを
`wire_gridfreq.parse()`で読み、次を機械的に検出する:

- `timebase_source`がPPS/PPS_NTPから外れた区間
- 欠測ギャップ(バッチ間隔が30秒を大きく超える)
- `session_id`の変化(予期しない再起動)
- `PPS_LOCKED`フラグと`timebase_source`の不整合

## 実測結果

2026-08-14 06:00 UTC〜2026-08-16 18:35 UTC(60.6時間、device 1)を通しで見たところ、
2026-08-15の日中は複数回の再起動(session_id 20→27)とtimebase_sourceの往復が
記録されていた。これは[log/2026-08-15-phase2-pps-first-lock.md](2026-08-15-phase2-pps-first-lock.md)・
[log/2026-08-15-nmea-line-reader-linelen-bug.md](2026-08-15-nmea-line-reader-linelen-bug.md)
の実装・検証作業そのもの(ビルドを焼き直すたびに再起動する)であり、soakの失敗ではない。

**最後の再起動(session_id 27、2026-08-15 15:18:44 UTC)以降を切り出すと:**

```
期間: 2026-08-15 15:37:46 UTC 〜 2026-08-16 18:45:48 UTC(27.8時間)
PPS/PPS_NTPロック率: 100.0%（99720s / 99750s）
tb_residual_ns: min=0 max=23 mean=0.1
イベント: 0件
```

**再起動ゼロ・ソース後退ゼロ・欠測ギャップゼロで27時間超、ロック率100%。**
`CLAUDE.md`が挙げていた目安「数時間〜1日」を上回る継続時間が実測できた。

## 結論

**フェーズ2(PPS同時サンプリング、方式A)のsoak確認は完了とし、フェーズ2をクローズする。**
残タスクとして挙げられていた「soak確認・クラウド着弾確認」はどちらも実測で片付いた
（クラウド着弾確認は同日先行して判明済み → [log/2026-08-17-dashboard-pps-caption-fix.md](2026-08-17-dashboard-pps-caption-fix.md)）。

次のフェーズは detect(周波数逸脱の確定判定、フェーズ9の残り)。時刻偏差(TE)の絶対値
表示・欠測区間の可視化もPPSデータが安定して出ている今、着手可能。
