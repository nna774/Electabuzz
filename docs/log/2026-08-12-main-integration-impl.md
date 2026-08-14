# main.cppへのPPS方式A統合を実装した(実機ビルド確認済み・実配線/実測前)

## 経緯

[log/2026-08-12-main-integration-design.md](2026-08-12-main-integration-design.md)
でまとめた設計を、そのままmain.cppへ書き写した。ユーザーから「`.venv`はリポジトリ
トップにある」と指摘を受け、worktree外(`/Users/nana/codes/Electabuzz/.venv`)の
`pio`をこのworktreeの`firmware/`へ`-d`オプションで向けて使えることを確認できた
——これで設計を「コンパイルすら確認できない」から「実際にビルドが通ることを
確認した」へ進められた。

## 実装

設計通り、変更点は4箇所。

1. **`config.h`**: `kGnssUartRxPin`/`kGnssUartTxPin`(GPIO2/1)/`kGnssUartBaud`、
   `kPpsEdgeThreshold`(未校正のプレースホルダ)/`kPpsEdgeRefractorySamples`、
   `kLedPpsLockPin`(GPIO8。従来「予約のみ・未使用」だったコメントを実際の定数に
   置き換えた)を追加
2. **`pumpI2s()`**: 既存の`g->addSample(l)`と同じループ内で、`gEdgeDetector`が
   非null(記録モードのみ)なら`r`を`feed()`し、エッジを検出したら`gPpsEdgeQueue`
   (Core1→Core0)へ送る。`gRecordGoertzel`と全く同じ「record modeでのみ非null」
   パターンを踏襲した
3. **`setup()`**: `Serial1.begin()`、`kLedPpsLockPin`の`pinMode`、
   `gEdgeDetector`の構築(`xTaskCreatePinnedToCore(i2sTask, ...)`より前、
   `gRecordGoertzel`と同じ理由)
4. **`loop()`**: 毎周回すブロックとして、①`gPpsEdgeQueue`を`gPps.addEdge()`へ
   流し込み、PPSロック遷移でGoertzelを(NTPロック時と同じ手順で)再武装
   ②`Serial1`を読み`parseGga()`で`gGnssFix`を更新、を追加。オーバーフロー時は
   `gFs.reset()`と並べて`gPps.reset()`も呼ぶ。GFRQヘッダ組み立ては
   `fs_measured_uhz`/`tb_obs_count`/`tb_residual_ns`をPPS優先に、
   `timebase_source`を`kGfrqTbPps`/`kGfrqTbPpsNtp`まで正しく分岐、
   `flags`に`kGfrqFlagPpsLocked`/`kGfrqFlagGnssFix`を追加した

設計からの変更は無い——書き写しただけで済んだ。

## ビルド確認

`/Users/nana/codes/Electabuzz/.venv/bin/pio run -d firmware -e <env>`で確認。

| env | 結果 |
|---|---|
| `record` | **SUCCESS**(39.6秒。`PpsTimebase`/`PpsEdgeDetector`/`GnssNmea`とも
  リンクされていることをビルドログで確認) |
| `s3` | SUCCESS |
| `gridfreqtest` | SUCCESS |
| `ledtest` | SUCCESS |
| `provision` | FAILED(`secrets.h`が無い。**このworktreeに元々コピーされて
  いない、gitignore対象ファイルが原因で、今回の変更とは無関係**——
  `provision_main.cpp`は`env:record`のビルドから`build_src_filter`で除外されて
  おり、PPS関連の変更が一切触れていないファイル) |

`firmware/lib/{Timebase,GridFreq,Goertzel,PpsEdge,GnssNmea}/test/run.sh`も
全て再実行し、退行が無いことを確認した。

## 残タスク

- **実機投入・実配線・実測は何もしていない。** `kPpsEdgeThreshold`は依然
  未校正のプレースホルダ。R ch AFEの実配線、GNSS UARTの実配線、アンテナ到着後の
  fix取得が揃って初めて、この統合が実際に意味のある値を出せる
- `UBX-MON-VER`の自動確認は引き続きスコープ外(u-centerでの手動確認のまま)
