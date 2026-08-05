# Electabuzz — 作業のためのエントリポイント

商用電力の周波数と**系統時刻偏差**（グリッドの時計が標準時から何秒ずれているか）を
常時測る装置。設置先は 50Hz 地域（東日本）。設計フェーズで、コードは未着手。

このファイルは**ハブであって仕様ではない**。実体は各ドキュメントにある。
必要なノードまでリンクを辿れ。全部読む必要はない。

---

## 1. 最初に読む順序

1. **[docs/timebase.md](docs/timebase.md)** — **設計の核心。難所はここ1つで、他は全部その後の話。**
   位相推定はサンプル列を時間軸として使うので ADC のサンプルレート誤差がそのまま測定値の
   誤差になる。ここを理解しないと他のドキュメントの判断理由が読めない
2. **[docs/risks.md](docs/risks.md)** — 未検証の前提とリスク一覧、および注意点。
   実装に手を付ける前に読む
3. **[docs/progress.md](docs/progress.md)** — 何がどう決まったかの索引。
   詳細は `docs/log/YYYY-MM-DD-*.md` に分かれている。**新しいものから読む**
4. **[docs/open-questions.md](docs/open-questions.md)** — 未決の問い。手が空いたときの調査先

## 2. 現在の状態

**[docs/progress.md](docs/progress.md) を単一の真実とする。** 手持ち部品・確定事項・
着手可能タスクはそこにあり、**このファイルに複製しない**（二重管理は必ず食い違う）。

要点だけ言うと、**GNSS は未入手。MCU（ESP32-S3-WROOM-1 N16R8）と PCM1808 が手元にある**
（PCM1808 は**無改造で使え、配線とピン割り当ては [docs/hardware.md](docs/hardware.md) に確定済み**）。
**`GFRQ` の書き手（`firmware/lib/GridFreq/`）と読み手（`lambda/wire_gridfreq.py`）が揃い、
契約は `testdata/gfrq_v1_golden.hex` で両側から固定してある。**
**フェーズ1.5 の soak（`firmware/lib/Timebase/`）は母艦で走行中**で、
**一昼夜ぶんの結果はもう出ている**（手元の水晶は **+3.8873 ppm**、温度補正は不要、
`NtpTimebase` の実力は **0.2 ppm 級**）。**`ingest` Lambda（`lambda/ingest/`）も書けている**
（`/alert` と `terraform/` は未着手）。
送信基盤（[batch-uplink](https://github.com/nna774/batch-uplink) **v1.0.0**）は切り出し済みで
**`Batch` の契約は確定している**。

```sh
firmware/lib/GridFreq/test/run.sh          # 実機も PlatformIO も要らない
firmware/lib/Timebase/test/run.sh          # 同上（回帰は Arduino 非依存）
.venv/bin/python -m pytest lambda/tests    # repo 直下の .venv（Namazu と同じ形）
.venv/bin/pio run -d firmware              # ビルド（platformio も同じ .venv に入っている）
```

### 着手可能なタスク

**PCM1808 が届いたので手は動かせる。** soak はまだ回しているが、
**主要な問いは [log/2026-08-05-soak-first-day.md](docs/log/2026-08-05-soak-first-day.md) で
片付いている**（水晶の実 ppm・温度依存の不在・`residual_ns` の床）ので**急いで見るな**。
生ログは `soak/`（gitignore 対象）、捕捉は `tools/soak_capture.py <port> <path>`。
**接続すると基板がリセットされて回帰が積み直しになる**ので、用も無く繋ぎ直すな。
読むだけなら `tail soak/soak-*.csv` で足りる。**ポートを開くな。**

**次の一手は `fs` の実測だ。** PCM1808 の I2S を配線してサンプルを数え、
`NtpTimebase` の時間軸に対する `fs` の ppm と安定度を出す。**AFE も GNSS も DMM も要らない。**
**比較対象は soak で出た水晶の +3.8873 ppm** で、外れたら配線かクロック経路が想定と違う。
**これでリスク10 の残り半分が埋まる。** 配線に手を付ける時点で soak の捕捉を落とせ。

買い物では **アクティブアンテナが最優先**（→ [docs/progress.md](docs/progress.md)）。
GNSS 受信機は発注済みだが、**アンテナが無いと段階1の判定を始められない。**

`terraform/` を書く手もあるが、**急ぐ理由は無い。**
デバイス側の送信経路がまだ無く（`main.cpp` は soak 専用）、
フェーズ2（PPS 同時サンプリング）が成否の分岐点である以上、そちらが通ってからでよい。

## 3. 絶対に破ってはいけない不変条件

**これだけは他のドキュメントを読まなくても守れ。理由は各リンク先にある。**

- **測れなかった区間を測れたように見せるな。** セッション境界で線を繋ぐな。
  時間基準の質を `timebase_source` に必ず記録しろ（→ [docs/timebase.md](docs/timebase.md)）
- **`fs`（サンプルレート）を定数として書くな。** 「48000」は二重に信用できない。
  最初から `TimebaseEstimator` 越しに「測って報告する量」として持て
- **I2S は最初からステレオで初期化しろ。** GNSS 未入手で R ch が未接続でも同じ。
  **ここだけが後戻りできない**
- **`GPIO 33〜37` を使うな。** 手元の N16R8 モジュールでは内部で octal PSRAM に
  配線されている。**PSRAM を有効化しているかどうかとは無関係**で、ピンヘッダには
  出ているので何事もなく刺さる（→ [docs/hardware.md](docs/hardware.md)）
- **累積位相は絶対値で持て。** 差分保存だと欠測のたびに積分が壊れて復元できない
  （→ [docs/storage.md](docs/storage.md)）
- **`batch-uplink` はタグで pin しろ。ブランチ追従にするな。**
  稼働中の地震計が黙って壊れる（→ [docs/batch-uplink.md](docs/batch-uplink.md)）
- **NamazuHaUrokoGaNai の `terraform/` には apply するな。** Electabuzz は独立 state に閉じる
- **切り出しと一般化を同時にやるな。** 一般化は**テストと実機が揃っている側**で先に済ませ、
  出来上がったものをバイト等価に移す（→ [docs/batch-uplink.md](docs/batch-uplink.md)）

## 4. 作業したらログを1本足す

**このレポの進捗は `docs/log/` に日付ファイルを追記する形で記録する。**
既存ファイルを書き換えて履歴を消すな。

1. `docs/log/YYYY-MM-DD-<slug>.md` を新規作成する（1セッション・1トピックで1本）
2. **[docs/progress.md](docs/progress.md) の表に1行追記する**（新しいものが上。1〜3文の要約 + ログへのリンク）。
   状態が変わったなら同ファイルの「現在の状態」「着手可能なタスク」も直す
3. 設計判断が変わったなら、**該当する `docs/*.md` 本体も同じコミットで直す。**
   ログは経緯、`docs/*.md` は現在の結論。**両者が食い違ったら `docs/*.md` を正とする**
4. 未決の問いが増えた・片付いたなら [docs/open-questions.md](docs/open-questions.md) を更新する

ログに書くこと: **何を決めたか、なぜそう決めたか、何が覆ったか、次に何が可能になったか。**
作業の実況中継は要らない。**判断とその理由だけ残せ。**

## 5. ドキュメントの地図

| 知りたいこと | ファイル |
|---|---|
| サンプルレート誤差が何を壊すか / GNSS 1PPS を同一ADCで測る方式 / 時間基準のプラグイン化と実装の契約（`residual_ns` の定義・標本の捨てかた） / うるう秒 | [docs/timebase.md](docs/timebase.md) |
| トランス式ACアダプタの選定と実測 / AFE / 測定器の信頼度 / 電源 / 母艦選定 | [docs/hardware.md](docs/hardware.md) |
| GNSS 受信機の選定と買う順序 / アンテナ / 別件の NTP サーバとの共用 | [docs/gnss.md](docs/gnss.md) |
| 単一ビンDFT(Goertzel)を採る理由 / ゼロクロス検出を採らない理由 | [docs/signal-processing.md](docs/signal-processing.md) |
| `GFRQ` v1 のヘッダとレコード定義 | [docs/wire-format.md](docs/wire-format.md) |
| 累積位相を第一級データにする理由 / retention / ロールアップ | [docs/storage.md](docs/storage.md) |
| ingest の実装の契約（応答コードと置き先・CRC不一致の隔離・環境変数） / detect / rollup | [docs/cloud.md](docs/cloud.md) |
| 共通ライブラリの切り出し / 流用境界の実測 / タグ pin / レポジトリ配置 | [docs/batch-uplink.md](docs/batch-uplink.md) |
| 絶対確度をどう担保するか / 先行実装との外部照合 | [docs/verification.md](docs/verification.md) |
| フェーズの順序 | [docs/roadmap.md](docs/roadmap.md) |
| 未検証の前提とリスク / 注意点 | [docs/risks.md](docs/risks.md) |
| 部品と概算 | [docs/bom.md](docs/bom.md) |
| 決定の経緯・現在の状態 | [docs/progress.md](docs/progress.md) → `docs/log/` |
| 未決の問い・購入時の確認事項 | [docs/open-questions.md](docs/open-questions.md) |

## 6. 関連レポジトリ

- **[NamazuHaUrokoGaNai](https://github.com/nna774/NamazuHaUrokoGaNai)**（`../NamazuHaUrokoGaNai`）—
  家庭用地震計。**実機稼働中。壊すな。**
  送信基盤の大半をここから流用する。`docs/*.md` の相対リンクはこのレポを指している
- **[batch-uplink](https://github.com/nna774/batch-uplink)** — 両者が共有する送信基盤。
  **v1.0.0 が出ている。タグで pin しろ**（→ [docs/batch-uplink.md](docs/batch-uplink.md)）

## 7. 書きぶりの約束

- ドキュメントは日本語。**判断だけでなく「なぜそう判断したか」を残す。**
- **`docs/*.md` は現在の結論、`docs/log/` は経緯。** 判断が覆ったら、**本体は新しい結論に
  書き換え、覆った経緯はログに書く。** 本体に `> **訂正**:` を積み上げるな。
  読む側が毎回「どちらが今の話か」を判定させられ、現在の結論であるという役割が壊れる
- **ただし「意図的に採らなかった選択肢」は本体に残せ。** 消すと同じ提案が再浮上する。
  残すときは履歴（「当初はこう書いていたが誤りだった」）ではなく、
  **「なぜそれを採らないか」という肯定文**で書け。それは経緯ではなく判断だからだ
- **ログに無い経緯を本体から消すな。** 先にログへ移してから消すこと
- 数値は**出典か実測かを区別できるように書く**（データシート値・実測値・机上計算を混ぜない）
- **README.md は人間向け。** Claude 向けの指示・段取りはこの CLAUDE.md に書く
