# Electabuzz — 商用電力周波数モニタ

家庭に設置して、商用電力の周波数を常時測る装置。現在値を出すだけでなく
**系統時刻偏差**——グリッドの時計が標準時に対して何秒ずれているか——を積算し続ける。
設置先は 50Hz 地域（東日本）。目標確度 ±1mHz 以下、分解能 0.1mHz 級。

**状態: 設計フェーズ。** ハードウェアは AC入力部のみ確定・実測済み。コードは未着手。
経緯と現況は [docs/progress.md](docs/progress.md) にある。

姉妹プロジェクトに [NamazuHaUrokoGaNai](https://github.com/nna774/NamazuHaUrokoGaNai)
（家庭用地震計、実機稼働中）がある。送信基盤の大半をそこから流用し、
共通部分は `batch-uplink` という独立ライブラリに切り出して両者で共有する。

---

## 何が難しいのか

**難所は1つだけだ。** 位相推定はサンプル列を時間軸として使うので、
**ADC のサンプルレートの誤差がそのまま測定値の誤差になる。**

ESP32 の水晶の ±20ppm は、積算すると **1日あたり1.7秒の偽の時刻偏差**を生む。
実際の系統時刻偏差の全変動幅が数秒なのだから、これは誤差ではなく破壊である。
**ここを解けるかどうかが全てで、他は全部その後の話だ。**

## どう解くか

PCM1808 は**ステレオ** ADC である。これを使う。

```
L ch ← 商用波形（トランス式ACアダプタ経由）
R ch ← GNSS の 1PPS
```

**信号と時間基準が同一のサンプルクロックで測られる**ので、クロック誤差が両方に共通に乗り、
比を取った時点で**一次で相殺する**。熱ドリフトは消える。
結果として**水晶の質にほとんど依存しない測定器**になり、TCXO も GPSDO も要らない。

**そして GNSS が届く前から動かせる。** 時間基準を `NOMINAL` / `NTP` / `PPS` の
差し替え可能なプラグインにしてあるので、当面は NTP 回帰で走る（偽TE は 10〜90ms/日 で、
系統時刻偏差の実変動より1〜2桁小さい）。`NtpTimebase` は PPS 到着後も
holdover とサンプルレートのクロスチェックとして残る。

詳細は **[docs/timebase.md](docs/timebase.md)** にある。**この設計で読む価値が最も高い一本だ。**

## 設計の要点

- **保存するのは周波数ではなく累積位相。** 周波数はその微分、時刻偏差はその差分として
  後から導出できる。微分値だけ保存すると欠測のたびに積分が壊れて二度と復元できない
- **商用電源に一切配線しない。** トランス式AC出力アダプタ（Ideal Power DA-12-09）を
  コンセントに挿すだけで完全絶縁。バレルジャック1個で受けるので AC側の配線作業がゼロになる
- **金をかけるべきは受信機ではなくアンテナ。** アクティブアンテナを窓際か屋外に引く。
  タイミング用の NEO-M8T（$100前後）は買わない——要るかどうかは家の空の見え方で決まり、
  それは安価な受信機で数日測れば分かる
- **確度は GNSS で自己校正する。** 二重測定はしない。代わりに GNSS の TIMEPULSE2 を
  50.000000Hz に設定して L ch に入れ、本番と同じ信号経路で既知の GNSS 同期信号を測る。
  関数発生器より確実で、トレーサビリティが GNSS まで繋がる
- **稼働中の地震計を壊しえない構成にする。** 共通コードはタグで pin した独立レポジトリに切り出し、
  AWS スタックも分離する
- **貫く一線: 測れなかった区間を測れたように見せない。** セッション境界で線を繋がない

概算は [docs/bom.md](docs/bom.md)。段階1で 12,000〜18,000円。

---

## ドキュメント

| | |
|---|---|
| [docs/timebase.md](docs/timebase.md) | **時間基準。設計の核心。** サンプルレート誤差が何を壊すか、GNSS 1PPS を同一ADCで測る方式、時間基準のプラグイン化、うるう秒 |
| [docs/hardware.md](docs/hardware.md) | ハードウェア構成。ACアダプタの選定と実測、AFE、測定器の信頼度、電源、母艦選定 |
| [docs/gnss.md](docs/gnss.md) | GNSS 受信機の選定と買う順序、アンテナ、別件の NTP サーバとの共用 |
| [docs/signal-processing.md](docs/signal-processing.md) | 単一ビンDFT（Goertzel）。ゼロクロス検出を採らない理由 |
| [docs/wire-format.md](docs/wire-format.md) | `GFRQ` v1。64バイトヘッダ + 12バイト固定長レコード |
| [docs/storage.md](docs/storage.md) | 累積位相を第一級データにする理由、retention、ロールアップ |
| [docs/cloud.md](docs/cloud.md) | ingest / detect / rollup |
| [docs/batch-uplink.md](docs/batch-uplink.md) | 共通ライブラリの切り出し。流用境界の実測、切り出しの順序、レポジトリ配置 |
| [docs/verification.md](docs/verification.md) | 検証。GNSS による自己校正、先行実装との外部照合 |
| [docs/roadmap.md](docs/roadmap.md) | 実装フェーズ |
| [docs/risks.md](docs/risks.md) | 未検証の前提とリスク、注意点 |
| [docs/bom.md](docs/bom.md) | 部品構成と概算 |
| [docs/progress.md](docs/progress.md) | 進捗の索引。詳細は [docs/log/](docs/log/) の日付ファイル |
| [docs/open-questions.md](docs/open-questions.md) | 未決の問い、購入時の確認事項、部品到着後に測ること |

作業の段取りと守るべき不変条件は [CLAUDE.md](CLAUDE.md) にまとめてある。

## 名前について

エレブー（Electabuzz）は電気タイプ。地震計が `NamazuHaUrokoGaNai`（鯰は鱗が無い）なので、
そちらに合わせて由来のある名前にした。コード内のモジュール名やディレクトリには
ドメイン名として `gridfreq` を使う。

## License

MIT. [LICENSE](LICENSE) を参照。
