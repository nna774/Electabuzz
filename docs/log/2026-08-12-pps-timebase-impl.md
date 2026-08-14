# `PpsTimebase`(方式Aの回帰)を実装した(アンテナ非依存・ホストテストのみ)

## 経緯

[log/2026-08-12-gnss-pps-wiring-plan.md](2026-08-12-gnss-pps-wiring-plan.md)で洗い出した
「アンテナが無くても進められる作業」のうち、最優先とした`PpsTimebase`(3つ目の時間基準
プラグイン。今あるのは`NominalTimebase`/`NtpTimebase`のみだった)を実装した。

## 設計

`firmware/lib/Timebase/src/PpsTimebase.h/.cpp`。`NtpTimebase`と同じWelford回帰の型を
流用しつつ、PPS固有の性質を利用して簡略化した。

- **外部の絶対時刻(NTP/UTC)が要らない。** PPSエッジは(ロック時)厳密に1秒間隔で来るので、
  回帰のx軸に「原点からの経過エッジ数」をそのまま使える。`NtpTimebase`のように
  RTT・タイムアウト・往復遅延の非対称性を気にする必要が無い
- **`addEdge(double ticks)`が唯一の入力。** エッジのサブサンプル補間位置(小数可)を
  受け取るところから始まる。エッジ検出そのもの(R chの生波形からのピーク検出)は
  別レイヤの仕事として切り離した——`Goertzel`がLチャンネルの生サンプルだけで完結する
  設計と対称になっている
- **ギャップの扱いを2段にした。** 数エッジ分の欠落(deltaTicksが公称の整数倍に近い)は
  `expectedEdges`個ぶん橋渡しして回帰を続ける。`kMaxGapSeconds`(300秒)を超える
  ギャップは「unlocked/holdoverを跨いで繋げるのは危険」と判断してreset()し、
  `source()`が`kNominal`に戻る(`NtpTimebase`の「ティックが逆行したらreset」と
  同じ思想の拡張)
- **`kMinObs=10`・`kMinSpanSeconds=30`。** NTPの600秒(NTP自体の±5msノイズを均すための
  時間幅)に対し、PPSはノイズがほぼ無いので桁で短くした
- **本クラスが答えるのは実効レート(`fsMicroHz`)と確度(`residualNs`)だけ。** 絶対時刻
  (`batch_start_us`等)への固定は引き続き`NtpTimebase`が担う——`timebase_source`の
  `PPS+NTP`という値はこの役割分担をそのまま表している。この組み合わせ方(いつ`Pps`単独、
  いつ`PpsNtp`にするか)はmain.cpp統合時の判断として残っている

## テスト

`firmware/lib/Timebase/test/test_pps_timebase.cpp`、6ブロック18チェック全緑
(`firmware/lib/Timebase/test/run.sh`に追記)。

1. ノイズ無しで既知ppmを復元するか
2. エッジ検出のサブサンプル誤差(±0.5サンプル相当のジッタ)を乗せても復元するか、
   確度の自己申告がNTP(1ppm級)より桁で良い(<200ns/s)ことを確認
3. 観測不足のうちは`kNominal`を名乗らないか(不変条件)
4. 数エッジ分のギャップを橋渡しできるか、`spanSeconds()`がギャップぶんも数えるか
5. `kMaxGapSeconds`を超えるギャップはreset()して`kNominal`に戻るか
6. ティックの逆行でreset()するか

既存の`NtpTimebase`/`GridFreq`/`Goertzel`のホストテストも全緑のまま(退行なし)。

## 残タスク

- **PlatformIO実機ビルドの確認はまだ。** このセッションのサンドボックスに`pio`が
  無かったため、ESP32/Arduinoトールチェーンでのコンパイル確認はできていない。
  `<cstdint>`/`<cmath>`しか使っていないので通る見込みは高いが、次にPlatformIOが
  使える環境で`pio run -d firmware -e s3`を確認すること
- **main.cppへの統合は未着手。** R chのPPSエッジ検出(サブサンプル補間込みのピーク検出)
  も無い。次にやるなら「アンテナが無くても進められる作業」の④(GNSS UART/UBX読み取り)
  か、エッジ検出アルゴリズム自体(合成波形でホストテスト可能)のどちらか
