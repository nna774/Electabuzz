# データ保存: 累積位相・retention・ロールアップ

## 差分2: 累積位相を保存し、永久保存層を分ける

### 周波数ではなく累積位相を保存する

系統時刻偏差は積分量である。

```
TE(t) = ∫ (f(τ) - f_nom)/f_nom dτ
```

周波数 f の時系列だけを保存すると欠測区間の積分が復元不能になる。
**累積位相**(起動以降に通過した総サイクル数、小数部込み)を保存すれば

```
TE(t) = cycles(t)/f_nom - (t - t0)     … 偏差が差の形で直接出る
f(t)  = d(cycles)/dt                   … 周波数は任意窓で後から再計算できる
```

の両方が導出できる。**第一級のデータは累積位相であり、周波数は派生量。**

さらに差分ではなく**絶対値**を持つことが効く。実コードに欠測経路があるからだ。

> [main.cpp:113-119](https://github.com/nna774/NamazuHaUrokoGaNai/blob/master/firmware/src/main.cpp#L113-L119) —
> `gBatchQueue`(深さ4, [main.cpp:230](https://github.com/nna774/NamazuHaUrokoGaNai/blob/master/firmware/src/main.cpp#L230))
> が満杯だと**最古のバッチを `delete` する**。Uploader の LittleFS 退避に到達する前に
> 捨てられるので、「2xx まで捨てない」の不変条件はここをカバーしていない。

加速度計では許容できる設計判断だ。そして**累積位相を絶対値で持てば、周波数版でも
この経路が無害になる**: 落ちた30秒間の細かい周波数は失うが、次のバッチが絶対値を
持っているので時刻偏差は正確に計算できる。差分保存だと積分が永久に狂う。

### セッションの扱い (再起動を跨ぐ設計)

`cycles_q16` はセッション内の相対値なので、再起動を跨いで TE を繋ぐには
**セッションごとのアンカー**が必要になる。

- `session_id` は **ESP32 の NVS に保持し、起動ごとにインクリメント**する。単調増加が
  保証されないと時系列の順序が壊れる
- cloud 側は各セッションの最初のバッチから **アンカー `(t0_us, cycles_q16=0 の時刻)` を
  DynamoDB に記録**する。TE はセッションごとに計算し、境界は「不定区間」として明示する
- ダッシュボードはセッション境界を**線を繋がずに描く**。繋いでしまうと、実際には
  測定していない区間の偏差を捏造したことになる
- 停電で数分落ちた場合、その間の系統時刻偏差は原理的に測れない。**測れないものを
  測れたように見せないのが、この設計で最も重要な一線だ**

### retention: prefix を分けるだけで済む

[s3.tf:14-28](https://github.com/nna774/NamazuHaUrokoGaNai/blob/master/terraform/s3.tf#L14-L28) の lifecycle は
`filter { prefix = "raw/" }` なので、**`series/` に置けば自動的に永久保存**になる。
既存の「lifecycle は prefix 単位なので events/ へコピーで永久化」という解法と同じ発想。

| prefix | 内容 | 容量 | lifecycle |
|---|---|---|---|
| `series/YYYY/MM/DD/HH/<dev>-<start_us>.bin` | 累積位相 1Hz | **380MB/年** | **永久**(新バケットの既定。expire を掛けない) |
| `raw/...` | デシメーション生波形(検証期間のみ有効化) | 173MB/日 | 90日 expire |
| `events/<id>/` | イベント前後の生波形 + meta.json | — | 永久 |
| `rollup/1m|1h|1d/...` | ダウンサンプル | 極小 | 永久 |

1Hz × 12B = 12B/s。既存の 100Hz×3軸(600B/s)より **2桁軽い**。
`kMaxSpillBatches = 20000` ([config.h:28](https://github.com/nna774/NamazuHaUrokoGaNai/blob/master/firmware/src/config.h#L28),
「90日ぶんの上限目安」)は、周波数版のバッチが 424B なので**時間換算で桁違いに長く持つ**。

生波形の常時保存は価値が低い。既存のイベント切り出し思想を踏襲し、
**立ち上げ検証期間だけ `raw/` を有効化**して波形を眺めるのが賢い使い方。

---

## 差分3: ロールアップ (既存にない新規要素)

既存の地震計は「イベント前後の数十秒」しか描かないのでこの問題がなかった。
周波数モニタは**1年連続グラフが本質的な要求**で、1Hz なら 3100万点。ブラウザが死ぬ。

- EventBridge で日次起動する `rollup` Lambda を新設(watchdog と同じパターン:
  [lambda.tf:85-102](https://github.com/nna774/NamazuHaUrokoGaNai/blob/master/terraform/lambda.tf#L85-L102))
- `rollup/1m/YYYY/MM/DD.bin`(1分値) → `rollup/1h/YYYY/MM.bin` → `rollup/1d/YYYY.bin`
- **min/max を必ず保持する。** 平均だけだと逸脱イベントがグラフから消える
- 累積位相は区間末の値を持てば、どの階層でも時刻偏差が正しく出る
- ブラウザは表示レンジに応じて層を選ぶ

これで **Athena も時系列DBも不要**。「S3 をデータストアとする」既存思想を時系列表示まで
延長できる。

**配信経路: CloudFront OAC で `rollup/` だけ配る。**

既存の data バケットは [s3.tf:6-12](https://github.com/nna774/NamazuHaUrokoGaNai/blob/master/terraform/s3.tf#L6-L12) で
public access を全ブロックしているので、既存スタックに相乗りするなら api Lambda を経由する
しかなかった。**が、スタックを分離して新バケットを作るなら最初から OAC 前提で設計できる。**

- `rollup/` にだけ CloudFront OAC を向ける。`series/` と `raw/` は非公開のまま
- rollup は**不変・小容量**なので CDN キャッシュが完全に効き、Lambda 課金もかからない
- 長期グラフは静的ファイルの GET だけで描ける。API を叩かない
- 直近の細かいデータ(`series/`)は api Lambda 経由にする。二層で役割を分ける

既存の `terraform/dashboard.tf` とは別のディストリビューションになるので、
互いに干渉しない。これも分離の恩恵だ。

---

