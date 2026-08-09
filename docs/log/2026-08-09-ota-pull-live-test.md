# pull型OTA本体を実機・実クラウドで通しで確認した

## やったこと

[docs/log/2026-08-09-ota-hardware-deploy.md](2026-08-09-ota-hardware-deploy.md)
でNVS化・テレメトリまでは確認済みだったが、**pull型OTA本体(バイナリ取得〜
書き込み〜再起動)は未確認**だった。今回、実際に配信して通しで確認した。

```
tools/publish_ota.sh                                    # env:record をビルドし
                                                          # ota/record/351cd38.bin を
                                                          # ダッシュボードのS3へ公開
terraform.tfvars: ota_target_version = "351cd38"
terraform apply                                          # ingestの環境変数を更新(1 change)
```

シリアルログで観測した一連の流れ:

```
# batch enqueue: records=30 flags=0x0000 ram=0 spill=0
# ota: update available dafd1e7 -> 351cd38
# ota: flushed 0 batch(es) to spill
# ota: fetching https://d749zv0enwqn1.cloudfront.net/ota/record/351cd38.bin
# ota: write OK, restarting
[...] Reason: 8 - ASSOC_LEAVE
ESP-ROM:esp32s3-20210327
rst:0xc (RTC_SW_CPU_RST),boot:0x8 (SPI_FAST_FLASH_BOOT)
[...]
# fw_version=351cd38
# session_id=17
# wifi connected ip=10.255.255.158 rssi=-54
[...]
# batch enqueue: records=30 flags=0x0000 ram=0 spill=0
# batch enqueue: records=30 flags=0x0000 ram=0 spill=0
```

## 確認できたこと

- **バッチ送信便乗トリガーが実際に機能した。** ingestが返す`X-Elbz-Ota-Version`
  ヘッダをUploaderが読み、ビルドバージョン(`dafd1e7`)との不一致を検出して
  `checkAndPerformOta()`が起動した
- **TLS検証込みのダウンロードが成功した。** `WiFiClientSecure::setCACert()`で
  埋め込んだAmazon Root CA1でCloudFrontとのハンドシェイクが通り、
  `HTTPUpdate`で964KBの新バイナリを取得・書き込みできた
- **再起動は`RTC_SW_CPU_RST`(ソフトウェアリセット)。** `ESP.restart()`が
  正しく呼ばれ、電源断ではなく制御された再起動になっていることを確認
- **NVSがOTAをまたいで保持された。** 新ファーム起動後も`device 1`・同じWiFi・
  同じHMAC鍵で送信継続（app0/app1スロット切り替えがNVSパーティションに
  触れない設計どおり）。`session_id`は16→17に単調増加(継続、リセットされない)
- **バージョン一致後は再試行しない。** 再起動後の2回のバッチ送信ログに
  `# ota:`系のメッセージが出ていない——`target == ELBZ_FW_VERSION`の早期
  returnが効いている(ingestは`X-Elbz-Ota-Version: 351cd38`を返し続けているが、
  ファーム側の`ELBZ_FW_VERSION`も`351cd38`になったので一致、何もしない)

## 未確認のまま残っているもの

- **失敗系(TLS検証失敗・書き込み失敗時のバックオフ)。** 今回は成功系しか
  通っていない
- **ロールバック。** 実装していない(→ [docs/ota.md](../ota.md)「未決事項」)
- **RAMキューに実際にデータが溜まっている状態でのOTA。** 今回`flushed 0
  batch(es)`——たまたまバッチ送信直後でRAMキューが空だった。溜まっている
  状態での`flushToSpill()`は未確認

## 次に何が可能になったか

pull型OTAの主要経路(トリガー・NVS・TLS・ダウンロード・書き込み・再起動・
バージョン収束)が実機で一通り確認できたので、**OTAは実運用で使える状態**
になった。次にUSB挿し直しが面倒になったら、`tools/publish_ota.sh`+
`terraform.tfvars`書き換え+applyだけで済む。
