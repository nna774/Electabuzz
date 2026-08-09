# OTA更新

ファームの無線更新。2026-08-09に実装した。**NVS化・テレメトリは実機・実クラウドへ
投入し疎通確認済み**（`[env:provision]`→`[env:record]`で実機へ書き込み、NVSからの
WiFi/HMAC鍵読み込み・バッチ送信・`terraform apply`後のCloudWatchテレメトリログ
まで確認。→ [log/2026-08-09-ota-hardware-deploy.md](log/2026-08-09-ota-hardware-deploy.md)）。
**pull型OTA本体(バイナリ取得〜書き込み〜再起動)は配信対象未設定のためまだ未確認**
（`firmware/lib/*/test/run.sh`全種・`pio run`全env(s3/gridfreqtest/record/provision)・
`.venv/bin/python -m pytest lambda/tests`は確認済み）。

着手理由は「開発中に何度もUSBで挿し直すのが面倒になった」で、
[open-questions.md](open-questions.md)が定めていた着手条件そのもの。
Namazu(`../NamazuHaUrokoGaNai`)は同じ動機でOTAを実装しているが、あちらは
複数台の無人運用（外出先からの更新、watchdogによる停滞検知、DynamoDBの
`pending_ota_version`によるデバイス単位のロールアウト）を前提にしている。
Electabuzzは実機1台・2号機の予定なし・watchdog/生存台帳が未着手
（→ [progress.md](progress.md)「現在の状態」）なので、**トリガー機構は
大幅に簡略化した**（→ 3章）。設計判断そのもの（pull型・NVS化・ルートCA
埋め込み）はNamazuを踏襲するが、配線・パーティション・トリガーは
Electabuzz側で決め直した。

## 1. 採用した方式: HTTPSプル型のみ（push型は作らない）

Namazuは§2でLAN内push(ArduinoOTA)、§7でHTTPSプル型の両方を実装しているが、
Electabuzzは**プル型だけ**を実装した。理由は検討時に実機で確認済みの制約
——このデバイスが繋がる家庭内WiFi(`unnamed_network_g`)はNamazu側で
**VLAN間のクライアント分離**が確認されており(ICMPは通るがespotaのUDP招待
(ポート3232)には無応答)、push型を実装しても母艦から直接は届かない
（→ Namazuの`docs/ota.md`§5「ネットワーク分離」）。同じネットワークに
Electabuzzの実機も置く予定なので、push型を作るコストが実益に見合わない。

## 2. 土台の棚卸し

| 項目 | 状態 |
|------|------|
| パーティション | `board_build.partitions = default_16MB.csv`（既定のまま、変更不要）。`nvs`(0x5000)・`otadata`(0x2000)・`app0`/`app1`(各0x640000=6.25MB)・`spiffs`(0x360000)を最初から持つOTA対応レイアウトだった |
| 実装後のファームサイズ | `firmware.bin`(env:record)約987KB。スロット(6.25MB)の15.1%、余裕は十分 |
| LittleFS(spiffs) | appパーティションとは別領域なので、OTAしても`/gfrq_spill`の退避バッチは消えない |
| 失敗の検知 | **無い。** watchdog Lambda自体がまだ無い(→フェーズ9)。今は`tools/publish_ota.sh`実行者がシリアルログを見て確認する運用に留まる |

## 3. トリガー: バッチ送信レスポンスへの便乗（DynamoDB・watchdogは使わない）

Namazuの「バッチ送信レスポンスへの便乗」パターン自体は踏襲するが、
**ターゲットバージョンの置き場所はDynamoDBではなくterraformの環境変数**にした。
理由: Namazuの`pending_ota_version`はデバイス単位のロールアウト（複数台に
段階的に配る）を表現するための状態で、Electabuzzは実機1台・2号機の予定も
無いフラット構成なので、その表現力が要らない。**存在しない要件への一般化を
しない**という方針（→ [batch-uplink.md](batch-uplink.md)）にも合う。

```
terraform.tfvars: ota_target_version = "<gitの短縮hash>"
        ↓ terraform apply
ingest Lambdaの環境変数 ELBZ_OTA_TARGET_VERSION
        ↓ 毎バッチPOSTの成功レスポンスに便乗
レスポンスヘッダ X-Elbz-Ota-Version: <version>
        ↓ Uploader::lastResponseHeaderValue()で読む(batch-uplink v1.6.0の既存API)
ファームがELBZ_FW_VERSIONと比較、不一致なら取得・書き込み
```

**消費しない。** Namazuの`X-Namz-Ota-Version`と同じく「あるべき状態」として
扱うので、ingestはデバイスのビルドバージョンと一致するかどうかに関わらず、
`ELBZ_OTA_TARGET_VERSION`が設定されている限り毎回このヘッダを返す。
ファームのビルドバージョンと一致した時点でファーム側が自然に更新をやめる
（`checkAndPerformOta()`が`target == ELBZ_FW_VERSION`で早期returnする）。
取得・書き込み失敗時の自然なリトライにもなる。

配信を止める/戻すのも同じ経路——`terraform.tfvars`の`ota_target_version`を
空文字列に戻すかロールバック先のバージョンに書き換えてapplyする。

**watchdogによる停滞検知は作らない。** Namazuはこれを「証明書検証失敗の
ような問題が起きても、デバイスは黙ってバックオフ・リトライを繰り返すだけ
になる」ことへの保険として追加したが、Electabuzzは`request_ota.py list`
相当のツールも生存台帳も無い1台構成で、`tools/publish_ota.sh`実行者が
シリアルログを直接見る運用を前提にしている。停滞に気づく手段が欲しく
なったら、それはwatchdog Lambda自体(フェーズ9)の話としてまとめて作る。

### テレメトリ: ビルド版数・空きヒープ・稼働時間も同じ便乗で送る

OTAのトリガーに使う`extraRequestHeaderNames`機構は、他の運用情報を運ぶのにも
そのまま使える。GFRQのワイヤ形式(`testdata/gfrq_v1_golden.hex`で固定された
契約)には手を入れず、HTTPヘッダという別チャネルで運ぶ:

| ヘッダ | 内容 | 用途 |
|---|---|---|
| `X-Elbz-Fw-Version` | `ELBZ_FW_VERSION`(ビルド時のgit短縮hash) | 実機障害時に「今動いているのはどのビルドか」を確認できる |
| `X-Elbz-Heap-Free` | `ESP.getFreeHeap()` | 実機の健全性の粗い指標 |
| `X-Elbz-Uptime-Us` | `esp_timer_get_time()`の生値 | 再起動の有無を後から見分けられる(ただし`boot_epoch_us`への逆算はまだ未実装。→ [open-questions.md](open-questions.md)) |

ingestはこれらをCloudWatchログへ出すだけ(`_log_telemetry()`)。生存台帳が
無いのでS3/DynamoDBには保存しない——**OTAロールアウトを手元で見守る時の
可観測性のためだけ**の実装で、恒久的なダッシュボード表示は想定していない。

## 4. バイナリの秘密情報の分離（NVS化）

Namazuと同じ理由で必要——`ota/record/<version>.bin`をCloudFrontで公開する
設計は、バイナリに平文の秘密が焼き込まれていると成立しない。公開した瞬間、
その1台の家WiFiパスワードと投稿用HMAC鍵を世界に漏らすことになる。

旧`firmware/src/secrets.h`（WiFi SSID/パス・`kDeviceId`・`kHmacSecret`・
`kIngestUrl`）は、main.cppからは完全に切り離した。**secrets.hを読むのは
`provision_main.cpp`(`[env:provision]`)だけ**にした:

```bash
pio run -e provision -t upload --upload-port <USBポート>  # NVSへ書く(初回のみ)
pio run -e record -t upload --upload-port <USBポート>     # 続けて通常のfirmwareを焼く
```

`firmware/lib/DeviceIdentity/`がNVS(`Preferences`、namespace`"electabuzz"`
——`session_id`と同じnamespaceに同居させている)の読み書きを担う。
`main.cpp`は起動時に`loadDeviceIdentity()`を呼び、`deviceId`/`wifiSsid`/
`hmacSecret`/`ingestUrl`のいずれかが空なら**測定・送信を一切開始せず
起動時ログを出し続けて停止する**（Namazuと同じ「不定な状態で動かさない」
方針）。この停止チェックは`NAMZ_GRIDFREQ_RECORD`(実運用)だけでなく、
既定env(`s3`、fs実測soak)にもかかっている——どちらもWiFi接続にNVSの
identityを使うため。`NAMZ_GRIDFREQ_TEST`(WiFi不使用)は対象外。

**`kOtaBaseUrl`(ダッシュボード配信のCloudFront URL)はNVSに置いていない。**
秘密ではなく公開URL(ダッシュボード自体が認証なし公開)で、デバイス個体差
ではなくデプロイ差に属する値だからだ。`firmware/src/config.h`に
コンパイル時定数として直接書いてある。ダッシュボードのCloudFront
distributionを作り直すとURLが変わるので、その時だけ更新が要る。

`secrets.h`自体のフィールドは変えていない（`kWifiSsid`/`kWifiPass`/
`kDeviceId`/`kHmacSecret`/`kIngestUrl`のまま）。単一デバイス構成なので
Namazuの`tools/provision_device.py`/`devices.json`のような複数デバイス
向けの生成ツールは作らず、`secrets.h`をそのまま`provision_main.cpp`が
includeする。

## 5. バージョン識別: ビルド時にgit短縮hashを埋め込む

`firmware/get_fw_version.py`(extra_script)が`git rev-parse --short HEAD`を
`ELBZ_FW_VERSION`へ注入する(Namazuの`get_fw_version.py`と同じ設計)。
作業ツリーが汚れていたら`-dirty`サフィックスを付け、未コミット状態を
配布版として掴む事故に気付けるようにする。起動シリアルログにも出す。

## 6. 配布物: 既存ダッシュボードのS3+CloudFrontに相乗り

新規ドメイン/ACM証明書を作らず、ダッシュボード配信で使っている既存の
S3バケット(`aws_s3_bucket.dashboard`)+CloudFrontに`ota/`プレフィックスで
相乗りする。

```
ota/record/<version>.bin      # 例: ota/record/a1b2c3d.bin
ota/record/<version>.sha256   # 運用者が手元で照合する用（ファームは未検証）
```

`record`は固定（Electabuzzはボード・センサ構成が1種類だけなので、
Namazuの`esp32dev`/`adxl355`のようなenv振り分けは要らない）。
`tools/publish_ota.sh`でビルド〜アップロードまで行う（作業ツリーが
汚れていたら既定で拒否、`--allow-dirty`で強制可）。

## 7. ダウンロード: HTTPUpdate + TLS検証はルートCA埋め込み

Arduino-ESP32の`HTTPUpdate`(`httpUpdate.update(client, url)`。内部は
`WiFiClientSecure`+`HTTPClient`、書き込みは`Update.h`)を使う。
`rebootOnUpdate(false)`にして再起動は呼び出し側で制御する。

TLS検証は`openssl s_client -showcerts`でダッシュボードのCloudFront
(`d749zv0enwqn1.cloudfront.net`)の証明書チェーンを実際に確認した:
`*.cloudfront.net` -> `Amazon RSA 2048 M01` -> `Amazon Root CA 1`。
Namazuが実機で確認したチェーンと同じだったので、同じ`amazon_root_ca1.pem`
をそのまま`firmware/certs/`にコピーし、`board_build.embed_txtfiles`で
リンク、`WiFiClientSecure::setCACert()`で明示検証する。Namazuは
ESP-IDFの低レベルAPIや既定CAバンドル検証が実機で失敗した経緯があり
(`docs/ota.md`(Namazu側)§7参照)、その教訓を先取りして最初からこの方式にした。

### 安全な停止シーケンス: RAMキューの退避のみ（測定タイマー停止は不要）

Namazuは100Hzサンプリングをesp_timerの周期タイマーで駆動しており、フラッシュ
書き込み中のキャッシュ無効化(両コアの命令フェッチ停止)でタイマー割り込みを
確実に取りこぼすため、`esp_timer_stop()`→タスクウォッチドッグ登録解除→
再開、という手順が要った。**Electabuzzにはそのどちらも無い**——I2Sは
DMA駆動の連続読み出し(`i2sTask`、Core1)で、タイマー割り込みではない。
タスクウォッチドッグも登録していない(`esp_task_wdt_add()`を呼ぶ箇所が無い)。
フラッシュ書き込み中にDMAが取りこぼしても、既存の`pumpI2s()`のオーバー
フロー検出が`GfrqFlagDiscontinuity`として正直に申告する仕組みがそのまま
効く(→ [storage.md](storage.md)の「測れなかった区間を測れたように見せない」
不変条件)。**新しく作る必要があったのはRAMキューの退避だけ**——
`ESP.restart()`で送信待ちのバッチが消えないよう、`gUploader->flushToSpill()`
(batch-uplink v1.4.0で追加済み、Electabuzzは既に`v1.6.0`をpin)を
OTA開始前に呼ぶ(`flushBeforeOta()`)。

### 失敗時のバックオフ

Namazuが実機で踏んだ「バックオフ無しだとloop周期ごとに取得を再試行し、
安全停止処理が走り続けて実測に影響する」不具合を、最初からバックオフ
(`kOtaRetryBackoffUs`=60秒、`config.h`)込みで実装した。時刻源は
`esp_timer_get_time()`(int64 us)——Namazuが踏んだ`millis()`(uint32、
約49.7日で折り返す)の境界バグを最初から回避している。

## 8. 未決事項・既知の割り切り

- **pull型OTA本体(バイナリ取得〜書き込み〜再起動)の実機確認はまだ。**
  `tools/publish_ota.sh`でダミーのバージョンを公開し、`terraform.tfvars`の
  `ota_target_version`で配信して実際に取得・書き込み・再起動まで通ることを
  確認する（NVS化・テレメトリは2026-08-09に確認済み。→
  [log/2026-08-09-ota-hardware-deploy.md](log/2026-08-09-ota-hardware-deploy.md)）。
- **ロールバックは実装していない。** Arduino coreの既定ビルドは
  `CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE`が入っておらず、新イメージは
  書けた時点で有効扱いになる。最後の砦は物理アクセス(Namazuと同じ判断)。
- **`.sha256`との突き合わせはファーム側では実装していない。** `HTTPUpdate`
  (`Update.h`)自身がESP32イメージのマジック・チェックサムを検証するのと、
  TLS検証で「正規のCloudFrontから来た完全なデータ」であることは担保できる。
  `.sha256`は`publish_ota.sh`が生成し運用者が手元で目視確認する用途に留めた
  (Namazuと同じ割り切り)。
- **停滞検知(watchdog)は無い。** 3章参照。1台構成でシリアルログを直接見る
  運用が前提。watchdog Lambda着手時に必要なら合わせて検討する。
- **再起動検知(`boot_epoch_us`の逆算)は無い。** uptimeヘッダは送信・ログ
  出力までで、そこからの「再起動があったかどうか」の判定ロジックは
  未実装(→ [open-questions.md](open-questions.md))。
