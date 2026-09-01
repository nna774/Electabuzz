# なまず(NamazuHaUrokoGaNai)の最近の更新をElectabuzzへ取り込めないか調査

## 背景

なまず側で2026-08-29〜09-01にかけてESP32コアダンプの自動収集・自動アップロード・
Slack通知の仕組みを実装し、加えてbatch-uplink v3.4.0への追従・WiFi再接続まわりの
バグ調査(arduino-esp32 `hostByName()`のスレッドセーフ違反、DNSキャッシュ破損)・
heap監視ビルドフラグ・OTA配信時の`firmware.elf`保存(coredump解析用)を行っていた。
Electabuzzに取り入れられるものがないか調査した(実装はまだ、調査のみ)。

## なまずのコアダンプ機構

- firmware側は`CoredumpQueue`ライブラリ(PR #171)。起動直後・WiFi接続前に
  `esp_core_dump_image_get()`でハードウェアcoredump領域の有無を確認し、あれば
  512Bチャンクで`esp_partition_read()`しつつLittleFSの`/coredump/`へリングバッファ
  としてコピー、コピー成功を確認してから`esp_core_dump_image_erase()`で消す
  (coredump領域は単一imageで次のpanicに上書きされるため、消す前にコピーを保証する
  設計)。WiFi接続後・`Uploader`生成前に`drainToCloud()`を同期呼び出しし、キューを
  古い順にHMAC署名付きで`ingestUrl + "/coredump"`へ直接POSTする——
  **batch-uplinkの`Uploader`は経由しない**(測定対象非依存という設計原則を守るため、
  送信先・形式がドメイン固有だから)。
- クラウド側は`lambda/ingest/handler.py`に`POST /coredump`ルートを追加、
  `data`バケットの`coredump/<device>/<fw_version>-<uploaded_at_us>.bin`に置き、
  `coredump/`prefix専用の60日ライフサイクルを設定(秘密情報混入の可能性があるため
  `events/`のような永久保持にしない)。Slack通知はJST読める時刻付き。
- symbolize(シンボル解決)はLambda側で自動化されておらず手元で`esp-coredump`を使う
  手作業のまま。2026-08-31、`publish_ota.sh`がOTA配信のたびに`firmware.elf`
  (約17MB)も`firmware.bin`と同じprefixへS3保存するようにし、実物のelfで
  `app_elf_sha256`照合が素直に通るようにした。ただしcoredump領域が単一image上書き
  のため「S3キーのfw_versionラベル≠実際にクラッシュしたビルド」がありうる点は
  残る(ラベル自身→1つ前の版→全履歴バイト一致検索、という手順で対処)。

## Electabuzzへの移植性

Electabuzzの`firmware/platformio.ini`は`board_build.partitions = default_16MB.csv`
(ESP-IDF標準)を使っており、**この標準テーブルには元からcoredump領域
(`coredump, data, coredump, 0xFF0000, 0x10000`)が含まれている**。なまずは16MB機
向けにパーティションcsvを手作りする必要があったが、Electabuzzは何もしなくても
coredump領域が既にある。`CoredumpQueue`自体は独立ライブラリ(LittleFS +
`esp_partition`/`esp_core_dump_*` API + `HTTPClient`/`WiFiClientSecure`直叩き)
なのでほぼそのまま移植可能——ただし`main.cpp`側の呼び出し位置(WiFi接続前/接続後・
Uploader生成前)を、Electabuzzの複数ビルドモード(`env:s3`/`gridfreqtest`/`record`/
`provision`)それぞれで意識して差し込む必要がある。なまずの`TlsMemPool`
(単一TLS接続前提の固定プール)はElectabuzzには存在せず、その制約は気にしなくて
よい分むしろ単純。クラウド側も`lambda/ingest`への`POST /coredump`ルート追加・
S3キー生成・`terraform/s3.tf`への60日ライフサイクル追加という定型作業で済む。
watchdog Lambdaで既にSlack通知基盤があるため通知部分の追加コストも低い。

## 判断

**緊急性は低い。** `docs/progress.md`を見る限りElectabuzzの実機ではまだpanicや
WDT再起動によるクラッシュ事例が報告されていない(なまずのdevice1/device2は
継続的にTASK_WDT・DNSレース由来のクラッシュを踏んでいる)。detectしきい値校正や
TE絶対値表示の方が優先度は高い。ただし実装コスト自体は低め(パーティションは
既にある)なので、手が空いた時のタスク候補として`open-questions.md`に残す。

## その他、ついでに確認したこと

- **batch-uplinkバージョン表記**: なまず側の調査で「Electabuzzは`CLAUDE.md`が
  `v2.12.0`と書いているが実コードは`v3.1.0`」という食い違いを見つけたが、確認した
  ところ`main`は既に2026-09-01時点で`v3.1.0`表記に直っていた
  (→ [log/2026-09-01-cycles-jump-wifi-reconnect-correlation.md](2026-09-01-cycles-jump-wifi-reconnect-correlation.md)
  に記録済み)。今回作業していたローカルブランチ(`detect-devices-table-env-fix`、
  既に`main`へマージ済みの古いスナップショット)だけが古い表記のまま残っていた
  ため見かけ上再発したように見えただけで、`main`側の修正は不要だった。
- **WiFi `hostByName()`のスレッドセーフ違反(arduino-esp32 2.x系の既知バグ、
  なまずPR #191/#193)**: Electabuzzも同じ2.x系・ドメイン名(`ingestUrl`)接続なので
  理論上同じレースが起きうるが、実害(実際のクラッシュ)はまだElectabuzzでは
  未報告。潜在リスクとして認識だけしておく。
- **batch-uplink v3.4.0(なまず側の追従先)**: 内容の深追いはしていない。Electabuzz
  は現在`v3.1.0`。差分確認は別タスク。
- **heap監視(`NAMZ_HEAP_CHECKPOINT`)**: 診断用ビルドフラグの追加のみで移植コストは
  低いが、Electabuzzは`X-Elbz-Heap-Free`ヘッダで既にfree heapは送信済み
  (→ [open-questions.md](../open-questions.md)「heapテレメトリ」項)。max alloc
  block相当の追加はなまずと同じく「同種の障害を経験してから」でよい。
- **platformバージョンpin問題(pioarduino/arduino-esp32 3.x移行PoC)**: Electabuzz
  は既に`espressif32@7.0.1`を明示pin済みなので、なまずが踏んだ「pioarduinoが
  既定解決先を上書きする」事故は当面該当しない。
