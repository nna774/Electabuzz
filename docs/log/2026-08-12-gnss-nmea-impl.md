# GNSS UART読み取り(NMEA GGA解析)を実装した(アンテナ非依存・ホストテストのみ)

## 経緯

[log/2026-08-12-gnss-pps-wiring-plan.md](2026-08-12-gnss-pps-wiring-plan.md)で洗い出した
「アンテナが無くても進められる作業」の④(GNSS UART/UBX読み取りコード)に着手した。

## スコープを絞った判断

**UBX-MON-VER(チップの本物確認)はfirmwareに実装しない。** u-centerで一度EEPROMに
`CFG-TP5`/`CFG-NAV5`を焼く作業(→[log/2026-08-12-gnss-pps-wiring-plan.md](2026-08-12-gnss-pps-wiring-plan.md)
「u-centerでやること」)のついでに`UBX-MON-VER`も確認できるので、firmware側で
バイナリUBXプロトコルを実装する理由が無い。**GFRQワイヤ形式が実際に必要としているのは
`gnss_fix`フラグ1ビットだけ**(→[wire-format.md](../wire-format.md))で、これは
u-bloxが既定で出しているNMEA GGAセンテンスのfix quality フィールドで足りる。
一番簡単な経路で足りる情報を、わざわざ複雑な経路(UBXバイナリ)で取りに行かない。

## 実装

`firmware/lib/GnssNmea/`に2つの薄い層を作った。

- **`NmeaLineReader`**: GNSS UART(Serial1、未配線)から届くバイト列を1行(NMEA
  センテンス)ずつに組み立てる。`feed(char)`を1バイトずつ呼ぶ形にしてあるので、
  実際のUART読み出しループ(main.cpp側、未実装)はこのクラスへバイトを流し込む
  だけの糖衣になる。固定長バッファ(128バイト、NMEA仕様の82バイト上限に余裕を
  見た値)で動き、あふれた行は次の`\n`まで静かに読み捨てて次の行から復帰する
  ——1行壊れても受信全体を止めない設計
- **`parseGga`**: GGAセンテンスを解析し、fix qualityを取り出す。チェックサム
  (`$`〜`*`直前のXORが`*`直後2桁の16進と一致すること)を検証し、talker ID
  (GP/GN/GL/GA/GB/GQ等、u-bloxのマルチGNSS既定はGN)は問わずGGAとして認識する

どちらもArduinoに依存しない。ホストのg++でテストできる。

## テスト

`firmware/lib/GnssNmea/test/`、2バイナリ・10ブロック22チェック全緑
(`test_nmea_line_reader.cpp`・`test_nmea_gga.cpp`、`run.sh`が両方をビルド・実行)。

- 行の切り出し(`\r\n`終端、複数行の連続処理)
- バッファあふれからの復帰、`reset()`の挙動(診断値`overflowCount()`は残る)
- fixあり/無し(quality=0)の区別、`hasFix()`の判定
- talker ID非依存の解析(GN含む)
- チェックサム不一致・GGA以外のセンテンス・壊れた入力の拒否

チェックサムはWikipedia等の既知の実例文字列を記憶に頼って埋め込むのではなく、
テスト内で自前計算する関数(`withChecksum()`)を使った——記憶違いによる
偽陽性/偽陰性を避けるため。

既存の`Timebase`/`GridFreq`/`Goertzel`/`PpsEdge`のホストテストも全緑のまま(退行なし)。

## 残タスク

- **main.cppへの統合は未着手。** `Serial1`のセットアップ(GPIO1/2、ボーレート)、
  `NmeaLineReader::feed()`を呼ぶ読み出しループ、`parseGga()`の結果を
  `gnss_fix`フラグへ反映する配線が要る
- **UBX-MON-VER確認はu-centerでの手動作業のまま。** firmware側で自動化する
  要望が出たら、そのとき着手すればよい(→ 上記のスコープ判断)
- **PlatformIO実機ビルドの確認はまだ**（このセッションのサンドボックスに`pio`が
  無い。`<cstdint>`/`<cstdlib>`のみ使用のため通る見込みは高い)
