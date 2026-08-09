# OTA(pull型)を実装した

## 何を決めたか、なぜそう決めたか

「開発中に何度もUSBで挿し直すのが面倒になった」という着手条件
（→ [open-questions.md](../open-questions.md)旧エントリ、
[log/2026-08-07-terraform-apply-and-secrets.md](2026-08-07-terraform-apply-and-secrets.md)）
が満たされたので着手した。設計判断の経緯は以下、現在の結論は
[docs/ota.md](../ota.md)にまとめてある。

### パーティションは変更不要だった

「パーティションを弄るならNVSも一緒に」という声を受けて調べたところ、
`firmware/platformio.ini`が既に指定している`board_build.partitions =
default_16MB.csv`はESP-IDF付属の既定ファイルで、最初から`nvs`(0x5000)・
`otadata`(0x2000)・`app0`/`app1`(各0x640000)・`spiffs`(0x360000)を持つ
OTA対応レイアウトだった。**パーティション変更は不要と判明**したが、
NVS化自体はopen-questions.mdの既存決定（「OTAに着手するときにNamazuと
同じ形でNVS化とセットでやる」）どおり実施した。

### push型(LAN内espota)は作らなかった

最初はNamazuと同じくLAN内push+HTTPSプル型の両方を検討したが、ユーザーから
「LAN型push、動かない。HTTPS配信したい」という指摘があった——Electabuzzの
実機が繋がる家庭内WiFi(`unnamed_network_g`)はNamazu側で**VLAN間の
クライアント分離**が確認済み(ICMPは通るがespotaのUDP招待には無応答、
→ Namazuの`docs/ota.md`§5)。同じネットワークにElectabuzzを置く予定なので、
push型を実装しても届かないと最初から分かっている。**プル型のみに絞った。**

### トリガー: DynamoDB方式ではなくterraform環境変数+バッチ送信便乗

Namazuの`pending_ota_version`(DynamoDB)+ingestヘッダ便乗+watchdog停滞検知を
そのまま持ち込むかどうかを検討した。**watchdogを作らずにバッチ便乗だけ
できないか**という指摘を受けて再検討し、以下の理由で最小構成に決めた:

- Electabuzzは実機1台・2号機の予定なしのフラット構成。`pending_ota_version`の
  デバイス単位ロールアウト表現力は要らない
- watchdog/生存台帳自体がまだ無い(フェーズ9未着手)。停滞検知を作ると
  「存在しない要件への一般化」になる
- ターゲットバージョンの置き場所を**terraformの環境変数**
  (`ota_target_version`→`ELBZ_OTA_TARGET_VERSION`)にすれば、DynamoDBも
  専用CLIツールも不要。`terraform.tfvars`編集+applyという既存の操作感に
  そのまま乗る

ヘッダを読む・返すためのAPI(`Uploader::watchResponseHeaders`/
`lastResponseHeaderValue()`、`extraRequestHeaderNames`)はbatch-uplink
v1.6.0に既に入っており(Electabuzzは既にこれをpin中)、**ライブラリ側の
変更は不要**だった。

### テレメトリ(ビルド版数・空きヒープ・稼働時間)も同じ便乗で送る

ユーザーから「同じように現在のバージョンとか、空きメモリとかも送るように
するといい気がする。uptimeはバッチの中に情報ある？」という指摘があった。
GFRQのワイヤ形式(`testdata/gfrq_v1_golden.hex`で固定された契約)には
uptime相当のフィールドが無い(`session_id`は起動ごとの通し番号のみ)。
運用情報を計測データのワイヤ形式に混ぜるべきではないので、OTAトリガーと
同じ`extraRequestHeaderNames`チャネル(HTTPヘッダ)で運ぶことにした——
これは`open-questions.md`が個別に挙げていた3項目(ビルド版数埋め込み・
uptime送信・heap free送信)をまとめて解消する副産物になった。ingestは
CloudWatchログに出すだけで保存はしない(生存台帳が無いため)。

### NVS化: secrets.hを読むのはprovision_main.cppだけにした

Namazuの`DeviceIdentity`パターンを踏襲。Electabuzzは単一デバイス構成なので
Namazuの`tools/provision_device.py`/`devices.json`のような複数デバイス向け
生成ツールは作らず、**既存の`secrets.h`をそのまま`provision_main.cpp`が
includeする**形にした——フィールドも変えていない。`kOtaBaseUrl`だけは
NVSではなくコンパイル時定数のままにした(秘密ではなく公開URLで、
デバイス個体差ではなくデプロイ差に属する値だから)。

### TLS検証: 証明書チェーンを実測確認してからルートCAを決めた

`openssl s_client -showcerts`でダッシュボードのCloudFront
(`d749zv0enwqn1.cloudfront.net`)を直接確認し、`*.cloudfront.net` ->
`Amazon RSA 2048 M01` -> `Amazon Root CA 1`とNamazuが実機で確認した
チェーンと同じだと分かったので、Namazuの`amazon_root_ca1.pem`をそのまま
コピーして使った。Namazuが低レベルAPI・既定CAバンドル検証で2段階の失敗を
実機で踏んだ経緯(→ Namazu側`docs/ota.md`§7)を知っていたので、最初から
`HTTPUpdate`+`WiFiClientSecure::setCACert()`方式を選び、同じ失敗を
再現する手間を省いた。

### 安全な停止シーケンスがNamazuより単純で済んだ

Namazuは100Hz周期タイマー駆動のサンプリングを止める・タスクウォッチドッグの
監視対象から一時的に外す、という手順が要ったが、Electabuzzは
I2SのDMA連続読み出し(タイマー割り込みではない)で、タスクウォッチドッグも
そもそも登録していない。フラッシュ書き込み中のDMA取りこぼしは既存の
オーバーフロー検出(`GfrqFlagDiscontinuity`)がそのまま拾うので、
新規に実装したのは`gUploader->flushToSpill()`によるRAMキュー退避だけで済んだ。

## 何が覆ったか

[open-questions.md](../open-questions.md)の以下のエントリを解消・更新した:
- OTA本体のエントリを削除(実装完了、→ [docs/ota.md](../ota.md))
- 「ビルド時バージョン埋め込み」を削除(`get_fw_version.py`で完了)
- 「稼働時間ヘッダ送信 → 再起動検知」を一部解消に更新(送信・ログ出力は完了、
  `boot_epoch_us`逆算は未着手のまま残した)
- 「heapテレメトリ」を一部解消に更新(free heapは完了、max alloc blockは
  未着手のまま残した)
- batch-uplink v1.7.0/v1.8.0の項に、OTAで埋め込んだルートCAをUploader側にも
  流用できる旨を追記した

[docs/log/2026-08-07-terraform-apply-and-secrets.md](2026-08-07-terraform-apply-and-secrets.md)
の「今はやらないと判断した」は、着手条件(USB挿し直しが苦になった)が
満たされたことで覆った——ただしその判断自体(存在しない要件を先取りしない)
は誤りではなく、着手条件が成立するまでの正しい判断だったので訂正ではない。

## 次に何が可能になったか

**実機での動作確認が次の一手。** `tools/publish_ota.sh`でダミーのバージョンを
公開し、`terraform.tfvars`の`ota_target_version`で配信、実際に取得・
書き込み・再起動まで通ることを確認する。GNSS到着待ちの間の手空き作業候補にもなる。

副次的に、リモート再起動の実装コストが下がった——`checkAndPerformOta()`の
パターン(バッチ便乗+`flushToSpill()`退避)をほぼそのまま流用できる
(→ open-questions.mdの該当エントリに追記済み)。
