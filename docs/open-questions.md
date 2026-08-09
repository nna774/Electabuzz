# 未決の問い

手が空いたとき、あるいは該当する部品が届いたときに潰す。
片付いたらこの表から消し、[progress.md](progress.md) に一行足して `log/` に詳細を書く。

## 問い合わせ・調査

| 相手/対象 | 訊く・調べること |
|---|---|
| **W53SA 氏** | 構成は[記事](https://www2.hatenadiary.jp/entry/2022/04/12/freqWatch)で判明済み（ゼロクロス / 時間基準なし / ±10ppm / 東西両方）。残る問いは ①**東京50Hz 系はまだ稼働中か**（照合に使えるのは東日本側だけ）②生データを絶対時刻付きで交換できるか ③ゼロクロスの高調波ジッタの実測値 ④**MCPWM input capture の落とし穴**（方式B の退避先として先に聞いておく）⑤実装で何が壊れたか。→ [verification.md](verification.md) |
| **powerk95** | 測定方式と時間基準（ゼロクロスか位相推定か、NTP か GPS か）。CSV/API の取得方法・粒度・遡れる期間。**bot を 403 で弾くのでブラウザで見ること** |

## 急がないがそのうちやりたいこと

| 対象 | メモ |
|---|---|
| **batch-uplinkを`v1.7.0`(接続使い回し)・`v1.8.0`(CA証明書ピン留め)へ追従する** | Electabuzzの現行pinは`v1.6.0`(`firmware/platformio.ini`・`terraform/build_lambda.sh`)。両バージョンともNamazu実機で確認済みで後方互換(`Uploader`の`caCert`引数は既定`nullptr`→従来通り`setInsecure()`にフォールバック)なので、pinを上げるだけで導入できる。**v1.7.0**はバックフィル中(切断からの復旧時)にTLSハンドシェイクをやり直さず接続を使い回す改善——Namazuでは長時間バックフィル中のクラッシュ調査から生まれた。**v1.8.0**はOTA用に埋め込み済みのAmazon Root CA1証明書をingest/alert送信にも流用する、`setInsecure()`より厳格なTLS検証。**OTA(→ [ota.md](ota.md))で同じルートCAを既にingest系とは別経路(`WiFiClientSecure::setCACert()`)で埋め込んだので、v1.8.0に上げればUploader側もそれを流用してsetInsecure()を卒業できる**。着手する時はまず`openssl s_client -showcerts`で実際の証明書チェーンを確認すること（OTA実装時に確認済み: `*.cloudfront.net` -> `Amazon RSA 2048 M01` -> `Amazon Root CA 1`。ingest先はLambda Function URLで別ドメインなので改めて確認要）。**`v2.0.0`(ヘッダ配列のnullptr終端化、4本上限撤廃)への追従は見送り**——OTA実装で`extraRequestHeaderNames`を3本(fw_version/heap_free/uptime)使うようになったが、`kMaxExtraRequestHeaders=4`にはまだ余裕がある。上限に当たってから検討すれば足りる(→ [2026-08-09-namazu-convenience-features-survey.md](log/2026-08-09-namazu-convenience-features-survey.md)) |
| **リモート再起動**（コマンドラインから再起動要求を送り、次のバッチ送信タイミングでデバイスが自分で再起動する） | 実機は1台のみで、物理アクセス無しに再起動を試せる足場になる。Namazuは「バッチ送信レスポンスへの便乗」方式(`Uploader::watchResponseHeader`でレスポンスヘッダを監視)で実装している。**必要なAPIは既にpin中の`v1.6.0`に入っているので、batch-uplinkのバージョンアップは不要**。firmware側は安全な再起動シーケンス(`flushToSpill()`でRAMキューをLittleFSへ退避してから`ESP.restart()`)、ingest側は1回性フラグ(要求を伝えた直後にクリア)の実装が要る。**OTA(→ [ota.md](ota.md))で同じ便乗パターン・同じ`flushToSpill()`退避シーケンスを既に実装したので、着手コストは下がっている**（`checkAndPerformOta()`をほぼそのまま参考にできる。ヘッダ名だけ別にする必要がある——`X-Elbz-Ota-Version`は「あるべき状態」として消費しない設計だが、再起動要求は「一度実行したら意味を失うイベント」なので1回性フラグが要る、という違いに注意） |
| **稼働時間(uptime)ヘッダ→再起動検知** | **uptimeの送信自体はOTA実装(2026-08-09、→ [ota.md](ota.md))で片付いた**——`X-Elbz-Uptime-Us`ヘッダで`esp_timer_get_time()`の生値を毎バッチ送っており、ingestはCloudWatchログに出している。**残っているのは`boot_epoch_us = batch_start_us - uptime_us`を計算して再起動を検知するロジックだけ**——今はログに出すだけで、再起動の自動検知・通知は無い。生存台帳が無いので現状は保存先も無い(watchdog Lambda着手時にセットで検討) |
| **heapテレメトリ(free heap / max alloc block)** | **free heapの送信はOTA実装(→ [ota.md](ota.md))で片付いた**(`X-Elbz-Heap-Free`ヘッダ、CloudWatchログに出すだけ)。**max alloc block(断片化の兆候)は未実装のまま**——Namazu側はバックフィル中の長時間クラッシュ調査という具体的な動機から追加したもので、Electabuzzはまだ同種の障害を経験していないので、経験してから着手で足りる |
| **緊急再起動ボタン(物理ボタン長押し)** | 母艦(ESP32-S3-WROOM-1 N16R8のDevKitC系ボード)のBOOTボタンは**GPIO0**、押下・離しの両方を`digitalRead(0)`で正しく検出できることを実機で確認済み(2026-08-09、→ [log/2026-08-09-led-button-hardware-probe.md](log/2026-08-09-led-button-hardware-probe.md))。RST/ENはハードウェアリセット直結でソフトウェアからは検出できず、Namazuの「退避してから安全に再起動」パターンには使えない(この判断は変わらず)。**技術的な障壁は解消した。着手するかどうかは優先度次第**——GNSS到着待ちの間の手空き作業候補ではあるが、フェーズ2(PPS)に比べれば優先度は低い。**実装するなら参考実装がある**——Namazu(`../NamazuHaUrokoGaNai`)の`kPinButtonFlip`は**Electabuzzと同じGPIO0**（向こうもBOOTボタンの流用）で、`firmware/src/main.cpp`の約590〜690行目に press-edge検出・2段階閾値(`config.h`の`kRebootHoldConfirmMs=2000`で確認画面+キュー先回り退避、`kRebootHoldTriggerMs=5000`で実際に再起動、trigger前に離せば即キャンセル)の実装がある。Electabuzzには表示デバイスが無いのでUI部分(`renderRebootHold`等)は不要、退避+再起動のシーケンスだけ移植すればよい |

## 設計を進めると決まること

| 対象 | 決めること |
|---|---|
| **`v_rms_mv` の基準点** | **商用の 100V は mV では u16 に収まらない**（最大 65.535V）。トランス二次側の実効値[mV]なら 10.5V ≒ `10500` で収まる。二次側の値を持つか、壁側に換算して単位を変える（10mV 刻み等）か。**AFE 分圧抵抗は R1=100kΩ/R2=6.8kΩ に確定済み**（→ [hardware.md](hardware.md)）。レコードを1バイトも記録していない今なら変更が無料で、記録開始後は高くつく。→ [wire-format.md](wire-format.md) |
| **レコードの `flags`** | ビットを1つも割り当てていない。**何を品質として立てるかは位相推定の実装が決める**ので、それが在るまで決めない（今決めるのは「存在しない要件への一般化」）。フィールドは確保済み。→ [wire-format.md](wire-format.md) |

**バッチ境界のタイムスタンプジャンプの直し方**は片付いた(2026-08-09)。**NOMINAL区間**は固定アンカー+公称fsの線形外挿(境界dt=1.0000秒 stdev=0、実機確認済み)。**NTPロック済み区間**は「`unixUsAt()`の統一で解消」という以前の評価が観測数の多い成熟した回帰でしか検証できておらず不十分だったと判明(→ powerk95外部照合と並行セッションによる独立な再検証(261境界の全数走査)で16件・最大244.5mHzの残存異常を発見)。決定打はAPI側で、`lambda/api/handler.py`の周波数計算をジッタを含む実測dtから`record_rate_mhz`由来の理論値に切り替え、実データ・外部照合の両方で異常が事実上解消することを確認した(firmware側の回帰原点ロールフォワードも実装したが、A/Bテストで効果は約30%縮小に留まる緩和策)。→ [risks.md](risks.md)リスク12、[log/2026-08-09-nominal-anchor-fix.md](log/2026-08-09-nominal-anchor-fix.md)(NOMINAL側)、[log/2026-08-09-batch-boundary-jump-regression-cause.md](log/2026-08-09-batch-boundary-jump-regression-cause.md)(NTP側、原因特定)、[log/2026-08-09-batch-boundary-jump-ntp-fix.md](log/2026-08-09-batch-boundary-jump-ntp-fix.md)(NTP側、対策)

## 購入時に確認すること

| 対象 | 確認内容 |
|---|---|
| **GNSS 基板（2台目）**（1台目は NEO-M8N を発注済み → [log/2026-08-04-gnss-order.md](log/2026-08-04-gnss-order.md)。**2台目は段階1の判定が出てから決める**） | ①**PPS ピンがパッドに出ているか。** 安価なクローン基板は PPS が LED にしか繋がっていない個体がある ②**チップが本当に u-blox か。** 設計は `CFG-TP5`（fix 喪失時も TIMEPULSE を出させる）と `CFG-NAV5`（定置モード）に依存しており、**UBX を喋らない受信機ではリスク5の逃げ道②が使えない**。段階3の M8T へ知見が繋がらなくなる点も効く。**出品タイトルに複数のチップ名が並んでいたら疑え** — 検索に引っ掛けるためのキーワード詰めで、本当のチップは先頭の1つだけということがある（2026-08-04 に ATGM336H を NEO-M8N と誤認しかけた） |

## soak が空いたら試すこと

| 対象 | 内容 |
|---|---|
| **母艦のオンボード RGB LED** | 駆動 GPIO の特定。候補は GPIO38 / GPIO48（Espressif 純正 DevKitC-1 系の定番だが、手元は互換品なので保証なし）。`Adafruit_NeoPixel` のサンプルで順に試す。**soak 走行中は繋ぎ直さない**（→ [log/2026-08-05-onboard-led-idea.md](log/2026-08-05-onboard-led-idea.md)） |

## 部品到着後に測ること

| 部品 | 測ること |
|---|---|
| **DMM（HIOKI 3244-60）** | ①**トランス無負荷出力**（10.5 VAC 前後の想定。**分圧比をここで確定**）②**壁コンセント電圧**（好奇心ではなく二つの計算を閉じるため。巻数比 9/120 から、壁が 103V なら全負荷相当 7.7V、105V なら 7.9V。実測 10.5V に対する**無負荷上昇率が 33% か 40% かが確定**し、同時に**磁束の余裕**が数字で言える） |
| **PCM1808** | **到着済み**（2026-08-05）。**発振器用パッドは無く、`FMT`/`MD0`/`MD1` は開放でスレーブ + I2S。配線とピン割り当ては [hardware.md](hardware.md) に確定させた**（→ [log/2026-08-05-pcm1808-arrival.md](log/2026-08-05-pcm1808-arrival.md)）。**ESP32がSCKI masterであることは2026-08-07に実測で確定した**（→ [log/2026-08-07-fs-wiring-verification.md](log/2026-08-07-fs-wiring-verification.md)。リスク10解消）。**一度決めたら PPS 到着後に変えるな**（配線とクロック経路が変わり検証がやり直しになる）。**モジュール入力のDC電位も2026-08-07に実測済み**（数mV、ほぼ0V。`Vcc/2`バイアス網は不要と確定 → [hardware.md](hardware.md)）。この行の残タスクは無い |
| **GNSS + アンテナ** | ①**`UBX-MON-VER` を投げて版を読む。** 発注した NEO-M8N は**天面に u-blox ロゴが見えず、SKU 内部名も `NEO-8N`**（実在しない型番）だった。**本物と確認できるのはここだけだ** ②**SMA にアンテナ用のバイアス電圧が出ているか実測**（写真から確認できていない。同出品の `+antenna` 版がアクティブアンテナなので出ていると見ているが**推測である**）③数日ログを取り**捕捉衛星数と fix 安定性を実測**する。これが NEO-M8T（約$100）を買うか否かの判定そのもの。→ [gnss.md](gnss.md) |
