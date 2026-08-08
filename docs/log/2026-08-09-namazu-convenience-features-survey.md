# Namazu firmwareの便利機能を棚卸しし、Electabuzzへの転用候補をリスト化した

Namazu(NamazuHaUrokoGaNai)のfirmware/docsには、地震計の運用強化フェーズ(§5)で
入れた機能が複数あり、そのうち何がElectabuzz(1台稼働・batch-uplink共有)にも
使えそうかを調査した。実装はせず、[open-questions.md](../open-questions.md)の
「急がないがそのうちやりたいこと」に候補を追記するだけに留める。

## 棚卸しした機能と判断

読んだのは`../NamazuHaUrokoGaNai/docs/ota.md`・`remote_restart.md`・`uptime.md`・
`log/2026-08-08-uplink-v1.7.0-conn-reuse.md`・`log/2026-08-08-uplink-v1.8.0-ca-cert-pin.md`・
`log/2026-08-08-heap-telemetry.md`。

| 機能 | 判断 |
|---|---|
| OTA(push/pull)+ NVS化 | **既に[open-questions.md](../open-questions.md)に既存エントリあり。今回は追記しない**(重複回避) |
| batch-uplink v1.7.0(接続使い回し)・v1.8.0(CA証明書ピン留め) | **追加候補。** Electabuzzのpinは現在`v1.6.0`(`firmware/platformio.ini`・`terraform/build_lambda.sh`で確認)。両バージョンともNamazu実機で動作確認済みで、APIは後方互換(`caCert`引数はデフォルト`nullptr`→従来通り`setInsecure()`)。バージョンpinを上げるだけで導入できる、コストの低い改善 |
| batch-uplink v2.0.0(ヘッダ配列のnullptr終端化、4本上限撤廃) | **今回は見送り。** Namazu自身もまだ追従しておらず(v1.8.0のまま)、Electabuzzは現状`extraRequestHeaderNames`/`watchResponseHeaders`を1つも使っていないので上限に当たる場面が無い。上限に当たってから検討すれば足りる |
| リモート再起動(バッチ送信レスポンス便乗) | **追加候補。** 使うAPI(`watchResponseHeader`)は既にv1.6.0に入っているので、batch-uplinkの追従は不要。firmware側の安全な再起動シーケンス(`flushToSpill()`→再起動)とingest側の1回性フラグ実装が要る |
| 稼働時間(uptime)ヘッダ→再起動検知 | **追加候補。** `extraRequestHeaderNames`も既にv1.6.0で使える。ingest側で`boot_epoch_us = batch_start_us - uptime_us`を計算する処理が要る(Namazuの`device_meta.py`パターンを参考にできる) |
| ビルド時バージョン埋め込み(git短縮hash) | **追加候補。** OTA本体を待たずに単独で先取りできる。シリアルログにビルドhashが出るだけで、実機障害時に「今動いているのはどのビルドか」を確認できるようになる |
| heapテレメトリ(free/maxblock) | **追加候補だが優先度は下げた。** Namazu側はバックフィル中のクラッシュ調査という具体的な動機があったが、Electabuzzはまだ長時間バックフィルでのクラッシュを経験していない。CloudWatchカスタムメトリクスという新しい構成要素も伴うので、他の項目より後でよい |
| `gBatchQueue`のdrop-oldestボトルネック・送信/吸い出しタスク分割案 | **追加しない(参考情報として留める)。** [2026-08-08のprogress.mdエントリ](../progress.md)で確認済みの通り、ElectabuzzのGFRQデータレートはNamazuの1/87程度で、既定パーティションのままspillに約2.9日分の余裕がある。Namazuを70分で溢れさせた同じ障害はElectabuzzでは起きにくく、今この設計変更を追いかける実益が薄い。Namazu側が実装(まだ「合意したが未着手」)したら再度見る |
| 緊急再起動ボタン(物理ボタン長押し) | **追加しない。** TFT+ボタンを前提としたNamazu固有のハードウェア機能で、Electabuzzの現行ハードウェア構成(母艦のみ)には対応する入力デバイスが無い |
| watchdog Lambda(生存監視+Slack通知) | **追加しない(既存の記載で足りる)。** [progress.md](../progress.md)の「現在の状態」に既にフェーズ9の一部として明記されている。firmwareの「便利機能」というより検知フェーズ全体の一部なので、ここで重複させない |

## 次に何が可能になったか

[open-questions.md](../open-questions.md)の「急がないがそのうちやりたいこと」に
4行(batch-uplink追従・リモート再起動・稼働時間/再起動検知・ビルド版数埋め込み)
+ 優先度を下げたheapテレメトリ1行を追加した。どれも未着手のまま、手が空いた時に
拾える形にしてある。
