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

要点だけ言うと、**設計フェーズでコードは未着手。ADC も GNSS も未入手で、MCU だけが手元にある。**
それでも着手できるタスクが2本ある。

### 着手可能なタスク（並行して進められる）

**A. `batch-uplink` の切り出し → v1.0.0** — ハードウェア不要。
手順は [docs/batch-uplink.md](docs/batch-uplink.md) の「切り出しの順序」に従う。
**優先度はこちらが上**（稼働中の地震計を巻き込むリスクを消す作業だから）。

**B. `NtpTimebase` を ESP32-S3 単体で書く** — PCM1808 を待たない。
時間基準の回帰は「単調増加するティック源を NTP 時刻に回帰する」だけなので、
ティックが I2S のサンプル数か `esp_timer` の µs かを問わない。
数日走らせれば手元の ESP32-S3 の水晶の実 ppm が取れ、リスク10 の片方が埋まる。
詳細は [docs/timebase.md](docs/timebase.md)。

A は実機焼き直しの検証待ちが入るので、その待ち時間に B を走らせるのが最も詰まらない。

## 3. 絶対に破ってはいけない不変条件

**これだけは他のドキュメントを読まなくても守れ。理由は各リンク先にある。**

- **測れなかった区間を測れたように見せるな。** セッション境界で線を繋ぐな。
  時間基準の質を `timebase_source` に必ず記録しろ（→ [docs/timebase.md](docs/timebase.md)）
- **`fs`（サンプルレート）を定数として書くな。** 「48000」は二重に信用できない。
  最初から `TimebaseEstimator` 越しに「測って報告する量」として持て
- **I2S は最初からステレオで初期化しろ。** GNSS 未入手で R ch が未接続でも同じ。
  **ここだけが後戻りできない**
- **累積位相は絶対値で持て。** 差分保存だと欠測のたびに積分が壊れて復元できない
  （→ [docs/storage.md](docs/storage.md)）
- **`batch-uplink` はタグで pin しろ。ブランチ追従にするな。**
  稼働中の地震計が黙って壊れる（→ [docs/batch-uplink.md](docs/batch-uplink.md)）
- **NamazuHaUrokoGaNai の `terraform/` には apply するな。** Electabuzz は独立 state に閉じる
- **切り出しと一般化を同時にやるな。** バイト等価な移動 → v1.0.0 → その後に一般化で v1.1.0

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
| サンプルレート誤差が何を壊すか / GNSS 1PPS を同一ADCで測る方式 / 時間基準のプラグイン化 / うるう秒 | [docs/timebase.md](docs/timebase.md) |
| トランス式ACアダプタの選定と実測 / AFE / 測定器の信頼度 / 電源 / 母艦選定 | [docs/hardware.md](docs/hardware.md) |
| GNSS 受信機の選定と買う順序 / アンテナ / 別件の NTP サーバとの共用 | [docs/gnss.md](docs/gnss.md) |
| Goertzel / ゼロクロス検出を採らない理由 | [docs/signal-processing.md](docs/signal-processing.md) |
| `GFRQ` v1 のヘッダとレコード定義 | [docs/wire-format.md](docs/wire-format.md) |
| 累積位相を第一級データにする理由 / retention / ロールアップ | [docs/storage.md](docs/storage.md) |
| ingest / detect / rollup | [docs/cloud.md](docs/cloud.md) |
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
- **`batch-uplink`**（未作成）— 両者が共有する送信基盤。`nna774` 配下に作る

## 7. 書きぶりの約束

- ドキュメントは日本語。**判断だけでなく「なぜそう判断したか」と「何が覆ったか」を残す。**
  過去の誤りを消さずに `> **訂正**:` として残すのは、同じ罠に二度落ちないための仕組みだ
- 数値は**出典か実測かを区別できるように書く**（データシート値・実測値・机上計算を混ぜない）
- **README.md は人間向け。** Claude 向けの指示・段取りはこの CLAUDE.md に書く
