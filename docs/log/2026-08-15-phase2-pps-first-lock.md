# フェーズ2実配線、初回でPPSロック成功(resid_ns=30)

## 経緯

GNSS(NEO-M8N)UART(GPIO13/14)・電源、PPS用の分圧+LPF網(L chと同じR1=100kΩ/R2=6.8kΩ/C1=15nF、PCM1808のR IN)をユーザーが実配線した。フェーズ2(PPS同時サンプリング、方式A)の実測に着手した——[docs/risks.md](../risks.md)前提1、設計全体の成否を決める本丸。

## 詰まった点: ESP32-S3のUSBポートが2つあり、片方は自動リセットが壊れている

書き込み用に使っていたポート(`/dev/cu.usbmodem1101`、`esptool`が`USB mode: USB-Serial/JTAG`と報告するネイティブ側)でシリアルモニタを開こうとしたところ、`pio run -t upload`直後を含めどうやってもデータが読めなかった。調査の結果:

- `esptool`のDTR/RTSベースの自動リセットシーケンス(`ClassicReset`/`HardReset`/`USBJTAGSerialReset`)を色々試したが、どれもダウンロードモード(`waiting for download`)に落ちる
- **`esptool` v4.11自体にバグがあると特定した**——`ESP32S3ROM.hard_reset()`が`ESPLoader.hard_reset(self, uses_usb_otg)`を呼ぶが、ネイティブ`USB-Serial/JTAG`(`uses_usb_jtag_serial()`)の場合`uses_usb_otg`は常にFalseなので、正しい`USBJTAGSerialReset`ではなく古典的な`HardReset(uses_usb=False)`が使われてしまう
- 物理リセットボタンを押しても同じ症状が再現したため、ソフトウェアのバグだけが原因ではないと判明
- **実は本体には`USB`と`UART`の2つのUSB-Cポートがあった。** もう一方(`/dev/cu.usbmodem5CCD0331811`、CP2102/CH340系ブリッジ経由)に挿し直したところ、何の問題もなく大量にデータが流れてきた

**教訓: このボードでシリアルモニタを使うときは`UART`側のポートを使え。** ネイティブ`USB-Serial/JTAG`側は書き込みには使えるが、自動リセットの制御が壊れていて詰みやすい。→ [docs/hardware.md](../hardware.md)に追記した。

## PPSエッジ閾値の較正: プレースホルダ(100000)がそのまま正解だった

`env:gridfreqtest`でR chの生データ(デシメート済み、実効240Hz)をダンプして確認した。

- **PPSのパルス(立ち上がりエッジ)はfc≈1.84kHzの受動LPFを素直に通過し、PCM1808内蔵のデジタルHPFで差分化されて巨大なスパイクになる。** 立ち上がりで約+80万〜85万、立ち下がり(100ms後)で約-40万〜46万(24bitフルスケール±838万に対して余裕あり、クリップなし)
- **ベースライン(静穏区間)のノイズは最大でも±1万程度。** 閾値100000は、ノイズ(最大1万)と実際のPPSピーク(80万超)の間に**桁で余裕のある位置**にあり、8秒間のキャプチャで8回、正確に1.000秒間隔で閾値上向き交差を検出、誤検出ゼロだった
- **`kPpsEdgeThreshold`(未校正のプレースホルダとして100000.0が入っていた値)は変更不要と確認できた。** 偶然にも最初から妥当な値が入っていたことになる

## PPSロック成功

`env:record`を実機に投入したところ、起動後まもなく:

```
# pps locked: goertzel re-armed fs=48001.814138 seed_cycles_q16=95091516 obs=30 resid_ns=30
```

**残差30ns/s——狙い通りppb級の確度が実測で出た。** 45秒後・105秒後の追加バッチでも`flags=0x0001`(`kGfrqFlagPpsLocked`)が継続して立っており、**ロックは安定している。**

`fs=48001.814138Hz`は公称48000Hzに対し約+37.8ppm。過去のNTP回帰実測(水晶+3.8873ppm、`fs`との差分は分周器由来で+31.7〜32.9ppm一定 → [docs/timebase.md](../timebase.md)リスク10)と合わせると+35.6〜36.6ppmの予想レンジになり、**実測+37.8ppmはこのレンジに近く、独立した2経路(NTP回帰とPPS回帰)が同じ`fs`を指しているという傍証になる**(`docs/timebase.md`が言う「`fs`の独立クロスチェック」がここで初めて実現した)。

## 残った小さな宿題: `kGfrqFlagGnssFix`が立たない

`flags=0x0001`はPPSロックのみで、`kGfrqFlagGnssFix`(bit1、GNSS UART経由のGGA `fix quality`から立てるフラグ)は今回一度も立たなかった。PPSの残差が30ns/sと極めて良好なことから、**GNSS自体は確実にfixしている**(free-running holdoverではこの精度は出ない)。原因はGNSS UART(GPIO13/14)側のNMEA読み取りにあると見てよい——配線・ボーレート・`Serial1.available()`のタイミングのいずれかを次回疑うこと。**PPSロックという本丸には影響しない副次的な課題**として切り出しておく。

## 次にやること

- `kGfrqFlagGnssFix`が立たない原因調査(GNSS UART配線・NMEA読み取り)
- `tools/gnss_cfg_query.py`(→ [log/2026-08-15-gnss-cfg-query-tool.md](2026-08-15-gnss-cfg-query-tool.md))で`CFG-TP5`/`CFG-NAV5`の実際の設定値を、今回配線が繋がった状態で読み返し確認する
- 長時間(数時間〜1日)PPSロックが安定して継続するかのsoak確認
- 実機を`env:record`のまま`series/`への着弾を確認し、クラウド側でも`timebase_source=PPS`のデータが見えることを確認する
