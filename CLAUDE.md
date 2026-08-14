# Electabuzz — 作業のためのエントリポイント

商用電力の周波数と**系統時刻偏差**（グリッドの時計が標準時から何秒ずれているか）を
常時測る装置。設置先は 50Hz 地域（東日本）。**実機1台が稼働中で、系統周波数の
ダッシュボードも公開済み**（→ 2章）。GNSS到着後のフェーズ2(PPS)が最後の本丸。

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

要点だけ言うと、**フェーズ0〜1.5・3・4・5・6・8(v1)は完了し、実機1台が
`env:record` で稼働、ダッシュボードも実データを表示している。** GNSS受信機・
アクティブアンテナは到着済みで、**段階1の判定(捕捉衛星数・fix安定性の実測)に
着手した**（屋外で3D Fix・約2時間の連続ログを確認済み。屋内設置との比較・
数日分のログ積み上げが残っている）。それが済んだらフェーズ2(PPS)、
その先にdetect(フェーズ9)。

- **時間基準**: `firmware/lib/Timebase/`（`NtpTimebase`）で `fs` 実測が完了、
  リスク10解消（水晶は **+3.8873 ppm**、`fs` との差分は分周器由来で一定 →
  [docs/timebase.md](docs/timebase.md)）
- **位相推定**: `firmware/lib/Goertzel/`（単一ビンDFTの2次IIR再帰）。
  PPS(フェーズ2)を待たずにC++移植した——PPSが効くのは結果を絶対時刻へ固定する
  後段の較正だけで、Goertzel本体はLチャンネルの生サンプルと`fs`だけで完結する
  という整理に基づく（→ [docs/log/2026-08-07-goertzel-cpp-port.md](docs/log/2026-08-07-goertzel-cpp-port.md)）
- **`GFRQ`の書き手・読み手**: `firmware/lib/GridFreq/` と `lambda/wire_gridfreq.py`。
  契約は `testdata/gfrq_v1_golden.hex` で両側から固定
- **実機**: `env:record`ビルドモードを焼き、`fs`がNTPで規正できてからGoertzelを
  起動、`timebase_source=NTP`と正直に申告してGFRQバッチを`Uploader`で送信。
  **実際に`ingest`まで届き、`series/`に着弾することを確認済み**
- **クラウド**: `lambda/ingest/`（受信）+ `lambda/api/`（`/recent`のみ。
  detect/生存台帳が無いので`/events`・`/devices`は無い）。送信基盤は
  [batch-uplink](https://github.com/nna774/batch-uplink) **v2.12.0**
  （2026-08-11、TLSハンドシェイクタイムアウト短縮・CA証明書ピン留め・spillの
  破損隔離(`discardSpillOn400`)を取り込むため追従。`v2.0.0`のヘッダ配列
  nullptr終端化に伴い呼び出し側`main.cpp`も書き換え済み。実機投入はまだ
  → [docs/log/2026-08-11-batch-uplink-v2.12.0-bump.md](docs/log/2026-08-11-batch-uplink-v2.12.0-bump.md)）
- **`terraform/`**: ingest + api + dashboard 分を書いて **`apply`済み**。
  state はNamazuと同じ保存先バケットの別keyで独立。detect/rollup/watchdogは
  対応するLambdaが無いのでまだ書いていない
- **ダッシュボード**: `dashboard/`（vanilla JS + Canvas、外部依存なし）。
  瞬時周波数と時間基準の品質(`timebase_source`等)を表示。実データで動作確認済み
  （→ [docs/log/2026-08-07-dashboard-v1.md](docs/log/2026-08-07-dashboard-v1.md)）
- **`firmware/src/secrets.h`・`terraform/terraform.tfvars`**: 埋め済みだが
  **gitignore対象なのでこのworktreeにしか無い。本体の作業ツリーへ手でコピーが要る**
  （→ [docs/log/2026-08-07-terraform-apply-and-secrets.md](docs/log/2026-08-07-terraform-apply-and-secrets.md)）
- **OTA(pull型)**: `[env:provision]`でNVSへ秘密を書き込み、`main.cpp`は
  `secrets.h`を読まなくなった。配信対象は**DynamoDB(`electabuzz-devices`、
  デバイス生存台帳)の`pending_ota_version`**に持ち、`tools/request_ota.py`で
  操作する(terraform applyは不要)。`X-Elbz-Ota-Version`ヘッダ(バッチ送信便乗)で
  更新対象を知り、ダッシュボードと共用のS3+CloudFrontから`HTTPUpdate`で取得する。
  ビルド版数は生存台帳へ、空きヒープ・稼働時間はCloudWatchログへ、同じ便乗で送る。
  `api`の`/devices`・ダッシュボードの品質テーブルからビルド版数が見える。
  **全経路(NVS化・テレメトリ・DynamoDBトリガー・pull型OTA本体・`/devices`・
  ダッシュボード表示)を実機・実クラウドで確認済み**（→ [docs/ota.md](docs/ota.md)）。
  **dashboardはterraform apply管理外**——`aws s3 sync`+CloudFront invalidationの
  デプロイが別途要る（→ [dashboard/README.md](dashboard/README.md)）

```sh
firmware/lib/GridFreq/test/run.sh          # 実機も PlatformIO も要らない
firmware/lib/Timebase/test/run.sh          # 同上（回帰は Arduino 非依存）
firmware/lib/Goertzel/test/run.sh          # 同上
.venv/bin/python -m pytest lambda/tests    # repo 直下の .venv（Namazu と同じ形）
.venv/bin/pio run -d firmware -e s3 -e gridfreqtest -e record -e provision  # ビルド（4 env とも実機不要）
```

### 着手可能なタスク

**次の一手は段階1の判定（捕捉衛星数・fix 安定性のログ取り）の続き**（→ [docs/progress.md](docs/progress.md)）。
屋外(窓越し)で3D Fix・約2時間の連続ログは確認済み。残るのは屋内(窓ガラス貼り付け)
設置との比較と数日分のログ積み上げ。それが済んだらフェーズ2(PPS同時サンプリング。
方式A)に着手する——**ここが設計全体の成否を決める**。

それまでの間に手を付けられるもの: 時刻偏差(TE)の絶対値表示・欠測区間の可視化
（どちらもPPS到着後でないと本質的な値は出せないが、UIの下地は先に作れる）。
**OTA(pull型)は実装済み**——実機でのUSB挿し直しが面倒という声を受けて着手し、
NVS化・ルートCA埋め込み・バッチ送信便乗トリガーまで実装したが、**実機での
動作確認はまだ**（→ [docs/ota.md](docs/ota.md)）。detect・rollup・watchdog 用の
terraform は対応する Lambda がまだ無いので書いていない（フェーズ9）。

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
| OTA(pull型)の設計・NVS化・トリガー(バッチ送信便乗)・テレメトリヘッダ | [docs/ota.md](docs/ota.md) |
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
  **現在の pin は v2.12.0。タグで pin しろ**（→ [docs/batch-uplink.md](docs/batch-uplink.md)）

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
