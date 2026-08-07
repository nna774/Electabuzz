# 実装フェーズ

> **番号について。** 冒頭の「着手順序」の表と、この一覧で別々に1から番号を振ってしまい
> 混乱を招いた。**この一覧の番号を正とする。** 紙の調査を**フェーズ0**として明示した。

## フェーズ0: 紙で潰す (ハードウェア不要・費用ゼロ)

**0-a. 系統周波数の外部参照を確保する** → **2026-08-03 調査済み。結論が出た**

- **東電PG / OCCTO は「系統周波数」の実績を公開していない。** 公開しているのは
  でんき予報の**需給実績**(電力使用状況・エリア需給、CSV)であって、周波数ではない。
  系統情報公表制度で出るのも予想潮流等。**当初の想定した参照先は存在しなかった**
- **代わりに個人運営の計測サイトが存在する。これが本命の照合先になる。**
  - **[powerk95](https://powerk95.net/50Hz/)** — **東日本50Hz系統**の周波数を実時間公開。
    **周波数・RoCoF・時差**を出し、日次グラフと**CSV履歴**がある。60Hz版の姉妹サイトあり。
    閾値超過のブラウザ通知、リプレイ機能、本日の最大/最小の記録も持つ
  - [power.f5.si](http://www.power.f5.si/) — 電源周波数変動の公開。アラーム通知付き
- **残タスク**: powerk95 の**測定方式**(ゼロクロスか位相推定か、時間基準は NTP か GPS か)と、
  **CSV/API の取得方法・粒度・遡れる期間**を確認する。サイトが bot を 403 で弾くので
  ブラウザで見ること

**0-b. PCM1808 の内蔵HPF仕様** → **2026-08-03 調査済み。リスクはほぼ消えた**

- **HPF はデジタルである。** データシートは「delta-sigma modulator with 64-times
  oversampling + **digital decimation filter and high-pass filter** that removes the
  dc component」と記述しており、デシメーションフィルタと同じデジタル信号路にある
- **デジタルであることが決定的だ。係数が固定なので温度で位相がドリフトしない。**
  リスク項目2の懸念(位相の熱ドリフト)は**原理的に発生しない**
- デジタルフィルタの諸元は**すべて fs で正規化**されている(pass band 0.454 fs、
  stop band 0.583 fs、リップル ±0.05dB、阻止域 −65dB)。**HPF のコーナーも fs 比のはずで、
  fs は GPS で規正して正確に知る**ので、位相シフトは既知の定数になる
- 仮にコーナーが 2.7Hz でも 50Hz での位相は arctan(2.7/50) = **3.1°、しかも定数**。
  定数位相は時間微分でゼロになるので瞬時周波数に効かない(トランスの位相特性と同じ論法)
- **残タスク**: データシートの DIGITAL FILTER CHARACTERISTICS 表から **HPF のコーナー
  周波数の実数値**を拾う。無効化できるかも見る。優先度は低い(上記の通り効かないため)

**0-c. 買う GNSS 基板が PPS ピンを出しているか**

- 通販ページの写真とピン配で確認できる。**安価なクローン基板は PPS が LED にしか
  繋がっておらずパッドが出ていない個体がある**
- 基板を選んでから。段階1の受信機選定(前掲)と同時に済ませる

---

## フェーズ1以降 (ハードウェアが要る)

1. ~~**AFE + PCM1808 の疎通**~~ **完了(2026-08-07)** — `NAMZ_SENSOR_TEST` と同じ
   パターンで `NAMZ_GRIDFREQ_TEST` ビルドフラグを作り、シリアルに生サンプルを吐いた。
   `tools/capture_serial.py` + `tools/spectrum.py` で FFT。50Hz の判別と THD の実測が
   済んだ(基本波50.026Hz、THD 0.0%、ゼロクロス法でも中央値49.934Hz)。
   **I2S は最初からステレオで初期化済み**(R ch は未接続。ノイズフロアも確認)。
   **PCM1808 の SCKI が ESP32 の MCLK 駆動であることはフェーズ1.5 の実測で確定**
   （→ [log/2026-08-07-fs-wiring-verification.md](log/2026-08-07-fs-wiring-verification.md)、
   [log/2026-08-07-gridfreq-test-mode.md](log/2026-08-07-gridfreq-test-mode.md)）
1.5. **時間基準プラグイン + `NtpTimebase`(GNSS 不要。ADC すら不要。到着を待たずに始める)** —
   `TimebaseEstimator` を切り、`NominalTimebase` と `NtpTimebase` を実装する。
   **ティック源もインターフェイスにしろ。** 回帰は「単調増加するティックを NTP 時刻に
   回帰する」だけなので、**ティックが `esp_timer` の µs でも I2S のサンプル数でも同じコードで動く。**
   だから **PCM1808 が届く前に ESP32-S3 単体で書けて、走らせて水晶の実 ppm も取れる**
   (→ リスク10 の片方の実測値になる)。差し替えは `esp_timer` → I2S → PPS の3段で同形。
   測定専用 SNTP クライアント(システム時刻を触らない)で
   `(累積サンプル数, NTP時刻, RTT)` を溜め、`fs` を回帰。
   **`fs` の実測値・安定度・SoC温度相関がここで初めて数字になる。**
   **これで GNSS を待たずにフェーズ3以降(送信・AWS・rollup・ダッシュボード・detect・外部照合)
   の全部が走る。** PPS 到着後は `PpsTimebase` を差すだけで、
   **wire format も後段も1バイトも変えない**。→ [timebase.md](timebase.md)
2. **PPS の同時サンプリング(方式A)** — R ch に PPS を入れ、エッジ間サンプル数から
   実効サンプルレートを同定。回帰残差が ppb 級に落ちることを確認。
   **ここが成否を決める。最初に潰せ。** 駄目なら方式B。
3. ~~**Goertzel 位相推定**~~ **完了(2026-08-07)** — `tools/gridfreq/` に Python 参照実装 →
   C++ 移植（`firmware/lib/Goertzel/`）→ `tools/backtest_gridfreq.py` で照合。既存 jismo
   と同じ流れ。Python参照実装は合成波形で ±1mHz(`docs/timebase.md`の目標精度)以内を
   確認済み、実キャプチャに通すとゼロクロス法(std 304mHz)より桁違いに安定(std 17.8mHz)
   した（→ [log/2026-08-07-goertzel-reference.md](log/2026-08-07-goertzel-reference.md)）。
   **C++移植はフェーズ2(PPS)を待たずに完了させた**——PPSが効くのは結果をGNSS絶対時刻へ
   固定する後段の較正だけで、Goertzel本体はLチャンネルの生サンプルと`fs`だけで完結する
   という整理に基づく判断（→ [log/2026-08-07-goertzel-cpp-port.md](log/2026-08-07-goertzel-cpp-port.md)）。
   標準的な2次IIR再帰(状態2個)に置き換えてあり、`firmware/lib/Goertzel/test/run.sh`で
   符号・振幅・高調波除去を検証済み。`NAMZ_GRIDFREQ_RECORD`ビルドモードで
   `timebase_source=NTP`としてGFRQを実際に送るところまで実装したが**実機には未投入**
4. ~~**`batch-uplink` を切り出して v1.0.0 を打つ**~~ **完了(2026-08-03)** —
   `Batch`(レイアウト非依存化済み)・`Uploader`/`HmacSha256`・`TimeSync`(C++)、
   `auth`・`devices`・`notify`・`s3util`(Python)。**一般化を Namazu の中で先に済ませてから
   移した**ので独立レポで無理にタグを分けることはしなかった。
   **その後 Namazu が OTA 等のために v1.1.0〜v1.6.0 を切っており(いずれも後方互換の
   追加)、現在の pin は両プロジェクトとも v1.6.0**（→ [log/2026-08-07-goertzel-cpp-port.md](log/2026-08-07-goertzel-cpp-port.md)）。
   → [batch-uplink.md](batch-uplink.md)
5. ~~**`GFRQ` ヘッダを `Batch` に載せる**~~ **完了(2026-08-03)** — `Batch(30, 12, 64, 0)` に
   64バイトヘッダを書き、`records()`/`recordsSize()` から `crc32` を埋める薄い層
   (`firmware/lib/GridFreq/`)。ヘッダは `static_assert` で寸法を固定してある。
   ハードウェア不要でホストの g++ でテストできる形で、フェーズ1〜3と並行して進めた
6. **送信** — `Uploader` に無改造で通す。**コードは書けた**
   (`NAMZ_GRIDFREQ_RECORD`ビルドモード。→ [log/2026-08-07-goertzel-cpp-port.md](log/2026-08-07-goertzel-cpp-port.md))
   が**実機には未投入**。実地確認では
   **回線を意図的に数時間切り、復帰後に `series/` に穴がないことを S3 側で確認**すること
7. ~~**`Electabuzz/terraform/` を新規に立てる（ingest分）**~~ **完了(2026-08-07)** —
   新バケット・IAMロール・Lambda・Function URL。state は Namazu と同じ保存先バケットの
   別key([versions.tf](../terraform/versions.tf))で独立。**`apply`済みで`ingest_url`が
   出ている**（→ [log/2026-08-07-terraform-apply-and-secrets.md](log/2026-08-07-terraform-apply-and-secrets.md)）。
   **detect・rollup・api・watchdog・CloudFront はまだ**——対応する Lambda 本体が
   無いので、先に terraform だけ書くと死んだリソース定義になる。
   **NamazuHaUrokoGaNai の `terraform/` には一切 apply しない**
8. **ダッシュボード** — 瞬時周波数・時刻偏差・PPS品質・欠測区間。rollup 層の切り替え
9. **detect + 通知**、**バッテリー給電と停電時の挙動**

> フェーズ4(切り出し)はハードウェアを必要としないので、**部品の到着を待つ間に
> 進めておける。** そして切り出しが v1.0.0 として固まっていないと、
> フェーズ5以降が地震計を巻き込むリスクを抱え続ける。**先にやれ。**

---

