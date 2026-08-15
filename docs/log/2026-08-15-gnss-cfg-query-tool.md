# CFG-TP5/CFG-NAV5をpollで読み返すツールを書いた

## 経緯

フェーズ2の実配線前に、u-centerで焼いたはずの`CFG-TP5`(fix喪失時もTIMEPULSEを出す設定)・`CFG-NAV5`(定置モード)が実際にEEPROMへ反映されているかを確認したい。2026-08-13時点では「u-centerで操作した」という申告止まりで、反映確認はまだだった。GUIのスクリーンショットを毎回撮って目視確認するのではなく、**receiverに直接pollして機械可読な答えを得る**方が確実で繰り返しやすい。

## 実装

`tools/gnss_cfg_query.py`。UBXプロトコルの素直な性質(payload無しでそのclass/idを送ると現在の設定が返る)を使い、`CFG-TP5`(0x06/0x31)と`CFG-NAV5`(0x06/0x24)をpollして応答をパースする。既存の`tools/parse_gnss_log.py`の`iter_ubx_frames`/`ubx_checksum_ok`をそのまま流用し、フレーム同定・チェックサム検証のロジックを重複させていない。

見るポイントは2つに絞った:
- `CFG-TP5`の`flags`ビット2(`lockedOtherSet`) — 立っていればfix喪失時もTIMEPULSEを出し続ける
- `CFG-NAV5`の`dynModel` — 2ならStationary(定置モード)

アンテナ・fixは不要(`UBX-MON-VER`確認と同じ性質。→ [log/2026-08-12-neo-m8n-ucenter-first-connection.md](2026-08-12-neo-m8n-ucenter-first-connection.md))。合成payloadでbuild/parseの往復とチェックサムの整合性を確認済み(実機テストはまだ——USB-TTLアダプタでGNSSモジュールに繋いだ状態で`python tools/gnss_cfg_query.py --port <port>`を実行すれば読める)。

## 使い方

```sh
python tools/gnss_cfg_query.py --port /dev/tty.usbserial-XXXX
```

フェーズ2の配線前チェックリスト(→ [progress.md](../progress.md))の「CFG-TP5/CFG-NAV5の反映確認」はこのツールで代替する。
