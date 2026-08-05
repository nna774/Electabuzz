# 進捗

新しいものが上。各行の詳細は `log/` の該当ファイルにある。
**このファイルは索引だ。判断の理由は各ログに、現在の結論は各設計ドキュメントにある。**

| 日付 | 何が決まったか | 詳細 |
|---|---|---|
| 2026-08-06 | **実配線用の配線図を作った。** AFE（R1=100kΩ/R2=6.8kΩ）・電源（5V/3.3Vの2系統）・I2Sピン割り当てを1枚にまとめてArtifactとして公開。**図を描く過程でAC出力の戻り端子の扱いが抜けていると気づいた**——バレルジャックの2端子はどちらもAC（トランス二次巻線の両端）で、あらかじめGND電位に決まっている端子は無いのに、既存の図は信号側の1本しか描いていなかった。`hardware.md` に戻り端子を回路GNDへ直結する旨を明記した | [log/2026-08-06-afe-wiring-diagram.md](log/2026-08-06-afe-wiring-diagram.md) |
| 2026-08-05 | **`main` の分岐マージで AFE 分圧抵抗の前提を突き合わせ、確定値を実測 VCC で検算した。** 並行セッションで一方は VCC 公称5V前提で R1=100kΩ/R2=6.8kΩ に確定し、もう一方は ESP32 の `5V` ピン実測が 4.84V だったことから分圧の目標を「フルスケールの60〜75%」というレンジに緩めていた。マージ時に確定済みの R1/R2 を実測 4.84V で検算すると、ワーストケース FS比は 72%→74.5%（ADC 負荷込みで 65%→67.4%）とやや天井に近づくが、いずれもクリップの余裕は残る。**両者は矛盾ではなく合成できた** | [log/2026-08-05-merge-afe-divider-reconciliation.md](log/2026-08-05-merge-afe-divider-reconciliation.md) |
| 2026-08-05 | **`fs` を測るファームを書いた**（`firmware/src/main.cpp` を v2 に。ビルドは通ったが**実機未投入**）。**推定器を2本立て、同じ NTP 標本を食わせてティック源だけ変える**: `gXtal`(esp_timer) が水晶、`gFs`(I2S 累積フレーム数) が `fs`。`NtpTimebase` はティック源を問わない設計なので**1行も変えずに済んだ**。**構成上この2つは一致しなければならず、不一致なら配線かクロック経路が想定と違う**（比較対象は +3.8873 ppm）。**落とし穴を2つ潰した**: ①**ESP32 が I2S マスタなので PCM1808 が無くても BCK/LRCK は出る** — フレーム数だけでは配線を証明できず「測れたように見える」ので、L/R の振幅 `l_pp`/`r_pp` を毎行載せた（0 なら DOUT が死んでいる） ②**DMA が溢れるとフレームを数え損ねて `fs` が静かに低く出る** — イベントキューで `RX_Q_OVF` を数え、検出したら `gFs.reset()` し、**吸い出しを Core1 の専用タスクへ出した**（SNTP は Core0 で最大2秒ブロックしうる。DMA は 85ms ぶんしか無い）。CSV は末尾に8列追記（既存の解析を壊さない）。**`platform` を `espressif32@7.0.1` で pin した** — このコードはレガシー `driver/i2s.h` 依存で、core 3.x(IDF5) は別 API だ | [log/2026-08-05-fs-measurement-firmware.md](log/2026-08-05-fs-measurement-firmware.md) |
| 2026-08-05 | **PCM1808 が届き、無改造で使えると確定した。** シルク `SKU:013325`、チップ刻印 `PCM1808 / BB S2A / C561`。**`FMT`/`MD0`/`MD1` は開放でよい** — データシートが内部 50kΩ プルダウンを明記しており、開放 = 全 Low = **スレーブ + I2S 24bit** で、これが欲しい構成そのもの（GND へ落とす手も採らない。配線が増えれば間違える余地も増える）。**発振器用パッドは無く**、缶発振器を外付けしない判断が実質確定した。**PCM1808 スレーブ / ESP32 が SCKI・BCK・LRCK を出す構成**とピン割り当て（MCLK=16, BCK=17, LRCK=18, DIN=15）を [hardware.md](hardware.md) に確定。**電源は 5V(アナログ) と 3.3V(デジタル) の2系統が要る**（レギュレータ非搭載）。**未決の問いが2つ潰れた**: フルスケール入力 **3Vpp @ VCC=5V** から **AFE の分圧比 1/14** が出た（机上計算。DMM 実測待ち）。内蔵 HPF コーナーは **`0.019 fS/1000` = 48kHz で 0.912Hz**、50Hz への位相進みは 1.045° = **58µs の固定オフセット**で無視できる（**実測不要**として問い自体を閉じた） | [log/2026-08-05-pcm1808-arrival.md](log/2026-08-05-pcm1808-arrival.md) |
| 2026-08-05 | **soak の一昼夜が閉じ、水晶の実 ppm が出た: +3.8873 ± 0.0055 ppm**（29.4時間、668点）。±10ppm 仕様の部品として素直な個体。初期の +11.2 ppm を信じなかったのが正しく、**`fs` の隣に `residual_ns` を置いた設計の値打ちがそのまま出た**。**温度補正は実装しないと決めた**（`temp_c` が 42〜57℃ を往復して共線が解けた区間で温度係数は `-0.044 ± 0.030 ppm/℃` = 有意でない。最悪値でも床と同じ桁で得るものが無い）。**最大の発見は `residual_ns` に床があること**: 局所 ppm の χ²/dof = 1.65 で**1〜2時間スケールの傾きは 0.2 ppm 級でふらついており**、同時点の申告 0.005 ppm と40倍離れる。定義（回帰の傾きの 1σ）は変えないが、**誤差予算の全体ではなく下限である**旨を [timebase.md](timebase.md) に実測値つきで足した。**`NtpTimebase` を信じてよいのは 0.2 ppm 級まで**（= 50Hz で 10µHz、時刻偏差は長期バイアスが効くので 0.5ms/日未満。要求は大きく上回る）。これは**方式Aを採る理由の裏取り**でもある | [log/2026-08-05-soak-first-day.md](log/2026-08-05-soak-first-day.md) |
| 2026-08-04 | **段階1の GNSS を NEO-M8N に確定し、1枚発注した**（1,629円、基板 `HW-542`、`PPS RXD TXD GND VCC`、IPEX + SMA、EEPROM 搭載）。**世代の選定を本体に書いた**: QZSS 対応（準天頂軌道 = 窓際で効くのは高仰角の衛星）・同時受信（狭い空で衛星数を稼ぐ唯一の方法）・M8T と同世代（段階3へ知見が繋がる）。**NEO-6M は QZSS 非対応で外し、M9N は設定方式が `VALSET`/`VALGET` に変わる上に M8T の代替にならない**（M8T の値打ちは 0D モード）。受信機の要件も書き直した（ジッタは要件でない代わりに **u-blox であること**が要件。UBX が無いとリスク5の逃げ道②が使えない）。**アンテナは未購入で、揃うまで段階1の判定は始められない**（測っているのは受信機ではなく空の見え方だ） | [log/2026-08-04-gnss-order.md](log/2026-08-04-gnss-order.md) |
| 2026-08-05 | **AFE の分圧抵抗を R1=100kΩ / R2=6.8kΩ に確定した。** PCM1808 データシートのフルスケール入力仕様(0.6VCC Vpp、VCC=5Vで3.0Vpp)から逆算。ADCの入力インピーダンス60kΩ(typ.)がR2と並列に効くことまで考慮すると、ワーストケース入力34VppでFS比65%、実測29.1VppでFS比56〜62%となりクリップの余裕は十分。**LPF(C1)・TVS・Vcc/2バイアスの定数とOPアンプ選定は未確定のまま残した**（この計算は VCC 公称5V 前提。**実測4.84Vでの検算は上の合流行を参照**） | [log/2026-08-05-afe-divider-resistors.md](log/2026-08-05-afe-divider-resistors.md) |
| 2026-08-05 | **母艦のオンボード RGB LED（WS2812互換1個）を色相インジケータとして使う方針だけ決めた。** 物理的に回る意匠にはできない（LEDは1個）ので、`residual_ns` などに応じて色相を時間軸で回す案にとどめる。駆動 GPIO は未確認（候補は GPIO38/48）で、soak が走行中の今は繋ぎ直して確認しない。実装は未着手 | [log/2026-08-05-onboard-led-idea.md](log/2026-08-05-onboard-led-idea.md) |
| 2026-08-04 | **PCM1808 モジュール(缶発振器なし版)を発注した。** 缶発振器の有無は方式Aの正しさに影響せず(相殺)、GNSS 未着の今なら構成を変えても実測やり直しで済むため判定待ちをせず購入。**この構成は ESP32 が SCKI の master になる**(= S3 採用理由である MCLK ピン自由度をそのまま使う) | [log/2026-08-04-pcm1808-order.md](log/2026-08-04-pcm1808-order.md) |
| 2026-08-04 | **`ingest` Lambda を書いた。** `lambda/ingest/handler.py` + `lambda/s3keys.py`、テスト37件が緑（AWS には触らない）。**置き先を `series/` にし `batch_uplink.s3util` は使わない**（あちらの `raw_key()` は `raw/` 固定で、Namazu の lifecycle が 90日 expire を掛けている。**永久保存のはずのデータが90日で消え、気づくのは3ヶ月後**になる。**prefix は保存方針そのものなので共有ライブラリの既定に寄りかからない**）。これに伴い「s3util の prefix を v1.1.0 で引数化する」を**覆した**。**CRC 不一致は隔離して 200**（400 だと同じ壊れたバッチが送られ続けて uplink が詰まる。捨てると証拠が消える。隔離キーは `batch_start_us` を使わず受信時刻と本文ハッシュで組む）。**生存台帳はテーブル未設定なら書かない**。**`/alert` と `terraform/` は意図的に書いていない** | [log/2026-08-04-ingest-lambda.md](log/2026-08-04-ingest-lambda.md) |
| 2026-08-04 | **フェーズ1.5 の soak が実機で走り出した。** 焼いて接続まで到達し、`flash=16MB` が返って **`platformio.ini` の 16MB 上書きが実機で効いていることを裏取り**した。**新発見: pyserial は既定で DTR/RTS を立ててポートを開く**ので、素直に開くと ESP32 の自動リセット回路が基板を握って一文字も出ない（実際に踏んだ）。`tools/soak_capture.py` に閉じ込めた。**macOS では open のたびに基板がリセットされるのを避けられない**ので、接続のたびに回帰は積み直しになる（区間ごとに ppm は出るので致命傷ではない）。手元の個体のシリアルは CH343 の **UART ブリッジ側**で `s3-usbcdc` は不要だった | [log/2026-08-04-soak-running.md](log/2026-08-04-soak-running.md) |
| 2026-08-04 | **母艦の現物が ESP32-S3-WROOM-1 N16R8 に確定し、`NtpTimebase` を書いた。** `firmware/platformio.ini` + `firmware/lib/Timebase/`（回帰は Arduino 非依存でホストの g++ テストが緑）+ フェーズ1.5 の soak スケッチ。**`residual_ns` の意味を「回帰の傾きの 1σ を ns/s に直したもの」に確定**（経路ノイズそのものではない。ダッシュボードの不確かさ帯と整合する定義はこれしかない）。**不変条件をインタフェースの実装で守る**: 観測が 8点/600秒に満たないうちは `source()` が `kNominal` を返し `fsMicroHz()` は公称値を返す（フラグの正しさではなく、数値を出さないことで守る）。**新発見: N16R8 では GPIO 33〜37 が使えない**（PSRAM 有効化の有無と無関係にモジュール内部で octal PSRAM に配線済み。S3 を採った理由である MCLK ピンの自由度がそのぶん狭い）。**この soak が測るのは ESP32 の水晶であって `fs` ではない**ので、リスク10 は片方しか埋まらない | [log/2026-08-04-ntp-timebase.md](log/2026-08-04-ntp-timebase.md) |
| 2026-08-03 | **`wire_gridfreq.py`（パーサ）を書いた。形式の契約が書き手と読み手の往復で閉じた。** `lambda/wire_gridfreq.py` + テスト20件が緑で、**ゴールデンフィクスチャを firmware と Lambda の両側から主張している**。**「読めない」(`WireFormatError`)と「壊れている」(`CrcMismatch`)を別の型にした**（後者だけ隔離して次へ進むのが正しい）。**`NAMZ` の magic は名指しで弾く**（設定ミスとして報告できて初めて fail-fast の値打ちが出る）。**未知の `timebase_source` を「規正済み」と名乗らせない**（保守的に外す）。依存は stdlib のみ。repo 直下に `.venv` を作った | [log/2026-08-03-wire-gridfreq-parser.md](log/2026-08-03-wire-gridfreq-parser.md) |
| 2026-08-03 | **`GFRQ` ヘッダの組み立てを実装した。このレポ最初のコード。** `firmware/lib/GridFreq/`（`WireFormat.h` + `GridFreqWire.h/.cpp`）で、ホストの g++ で走るテストが緑。**`crc32` は `zlib.crc32` と同じ版に確定**（版の食い違いは目視で守れないので既知ベクタをテストに置いた）。**`fillHeader()` の引数から「`Batch` や形式から出る値」を全部外した**（二重に持てるものを持たせなければ食い違いようがない）。**既定値は何も主張しない側に倒す**（`f_nominal_mhz` の既定は 50000 ではなく 0 = 未判別）。Python の `struct` 書式でも読めることを確認済み。**穴が1つ出た: `v_rms_mv` は 100V を mV で持てない**（u16 は最大 65.5V） | [log/2026-08-03-gfrq-wire-layer.md](log/2026-08-03-gfrq-wire-layer.md) |
| 2026-08-03 | **書きぶりの規約を変えた。`docs/*.md` に `> **訂正**:` を積み上げない。** 判断が覆ったら本体は新しい結論に書き換え、**経緯はログに書く**（本体に履歴が混ざると「どちらが今の話か」の判定を毎回強いる）。**例外は「意図的に採らなかった選択肢」で、これは本体に残す**。ただし履歴としてではなく**「なぜ採らないか」の肯定文**として書く。既存の訂正枠は全ドキュメントから外し、**ログに無かった5件は先にログへ回収してから消した** | [log/2026-08-03-design-doc-corrections.md](log/2026-08-03-design-doc-corrections.md) |
| 2026-08-03 | **`batch-uplink` v1.0.0 が出た。切り出し完了、`v1.1.0` は要らなくなった。** 一般化を Namazu 側で先に済ませてから移す順序に反転したため、**両プロジェクトが同じ v1.0.0 を指す**。**`Batch` の契約が確定**し、`GFRQ` の寸法(64Bヘッダ + 12Bレコード + tail無し)がそのまま載ることを確認済み。`finalize()` は不要になり `bytes()` は純粋な getter。**`sendAlert` が一般化された**ので速報本文を自由に設計できる。**設計書の「ArduinoJson が要る」は誤りで C++/Python とも依存ゼロ**。同日中に [batch-uplink.md](batch-uplink.md) と [wire-format.md](wire-format.md)（tail を持たない・`Batch` への載せかた）へ反映済み | [log/2026-08-03-batch-uplink-v1.0.0.md](log/2026-08-03-batch-uplink-v1.0.0.md) |
| 2026-08-03 | **母艦は ESP32-S3。ただし S3 必須ではないと確定した**（無印 ESP32 でも全要件を満たす）。S3 を採る理由は **MCLK 出力ピンの自由度だけ**（無印は GPIO 0/1/3 に限られ、ブートストラップピンかシリアルコンソールを諦めることになる）。**設計書の S3 に関する記述が2つ誤りだった: ETM は S3 に無い**（方式B は MCPWM capture のみ）、**APLL は S3 に無く無印 ESP32 にある**。どちらも結論を覆さない | [log/2026-08-03-mcu-selection.md](log/2026-08-03-mcu-selection.md) |
| 2026-08-03 | **GNSS を待たずに走らせる方針。時間基準を `NOMINAL`/`NTP`/`PPS` のプラグインにする。** wire format を源非依存に変更（`timebase_source` 等を予約領域から出したので PPS 到着時にヘッダは変わらない）。共有レポ名を `batch-uplink` に決定。**新発見: `fs` を決めているのが ESP32 の水晶か PCM1808 の缶発振器か未確定だった**（リスク10）。レポジトリを立てて設計書を13ドキュメントへ分割 | [log/2026-08-03-timebase-plugin.md](log/2026-08-03-timebase-plugin.md) |
| 2026-08-03 | **フェーズ0（紙の調査）が決着。** 東電PG/OCCTO は系統周波数を公開しておらず、当初の照合先は存在しなかった。代わりに [powerk95](https://powerk95.net/50Hz/) を発見し**外部照合先を確保**。**PCM1808 の HPF はデジタル**と確認しリスク2が消滅。先行実装（W53SA 氏）の構成が判明し、**方式B の動く先行例があると分かった** | [log/2026-08-03-phase0-external-reference.md](log/2026-08-03-phase0-external-reference.md) |
| 2026-08-03 | **AC入力部が確定。** Ideal Power DA-12-09 を 100V/50Hz・周囲30℃・無負荷で1時間通電し、温度・唸り・波形すべて合格。**無負荷出力は想定より高い 29.6 Vpp / 約 10.5 VAC** で分圧比を引き直す。副産物として手持ち測定器の信頼度の運用方針が確定（**オシロの周波数表示は使わない**） | [log/2026-08-03-ac-adapter.md](log/2026-08-03-ac-adapter.md) |

## 現在の状態

| | |
|---|---|
| 確定済み | AC入力部（実測済み）、wire format `GFRQ` v1、**[batch-uplink](https://github.com/nna774/batch-uplink) v1.0.0**（public・切り出し済み。`Batch` の契約が確定） |
| 手持ちハードウェア | **ESP32-S3-WROOM-1 N16R8 の DevKitC-1 系クローン**（本番用。**GPIO 33〜37 は octal PSRAM に取られていて使えない**）、**PCM1808 モジュール**（缶発振器なし版。2026-08-05 到着。**無改造で使える**。配線は [hardware.md](hardware.md)）、**無印 ESP32**（Namazu と同型の余り。予備機・差し替え先） |
| 未入手 | GNSS 受信機（**NEO-M8N を1枚発注済み**。→ [log/2026-08-04-gnss-order.md](log/2026-08-04-gnss-order.md)。**2台目は段階1の判定が出てから決める**）、**アクティブアンテナ（未購入。GPS/GLONASS 両対応のものを買え）**、DMM（HIOKI 3244-60） |
| 稼働中 | **フェーズ1.5 の soak が母艦上で走っている**（2026-08-04〜）。生ログは `soak/`（gitignore 対象）。捕捉は `tools/soak_capture.py <port> <path>`。**繋ぎ直すと基板がリセットされて回帰が積み直しになる**ので、用も無く繋ぎ直さないこと。**一昼夜ぶんの読みは済んでいる**（→ [log/2026-08-05-soak-first-day.md](log/2026-08-05-soak-first-day.md)）ので**急いで見る必要は無い** |
| コード | **`GFRQ` の書き手と読み手が揃った。** `firmware/lib/GridFreq/`（ヘッダの組み立て）と `lambda/wire_gridfreq.py`（パーサ）。契約は `testdata/gfrq_v1_golden.hex` で両側から固定してある。**時間基準は `firmware/lib/Timebase/`**（`TimebaseEstimator` / `NtpTimebase` / `MeasuringSntp`）で、回帰は Arduino 非依存。`firmware/src/main.cpp` は**フェーズ1.5 の soak 専用**で、v2 から **I2S を回して `fs` も同時に測る**（位相推定も送信もまだ無い）。**クラウド側は `lambda/ingest/handler.py` + `lambda/s3keys.py`**（`/alert` は未実装。`terraform/` も未着手） |
| 開発環境 | repo 直下の `.venv`（Namazu と同じ形）に pytest・platformio・**boto3・batch-uplink v1.0.0**。テストは `.venv/bin/python -m pytest lambda/tests` / `firmware/lib/GridFreq/test/run.sh` / `firmware/lib/Timebase/test/run.sh`。ビルドは `.venv/bin/pio run -d firmware`。**`firmware/src/secrets.h` は gitignore 対象**（雛形は `secrets.h.example`） |

### 着手可能なタスク

- ~~**`batch-uplink` の切り出し → v1.0.0**~~ **済み**（2026-08-03。Namazu 側で完結した）
- ~~**[batch-uplink.md](batch-uplink.md) を現物に合わせて直す**~~ **済み**（2026-08-03。
  `Batch` の確定契約・`sendAlert` の一般化・依存ゼロ・切り出し順序を反映。
  `wire-format.md` にも tail の扱いを明記した）
- ~~**`GFRQ` ヘッダの組み立てを書く**~~ **済み**（2026-08-03。`firmware/lib/GridFreq/`。
  テストは `firmware/lib/GridFreq/test/run.sh`）
- ~~**`NtpTimebase` を ESP32-S3 単体で書く**~~ **済み**（2026-08-04。`firmware/lib/Timebase/`）
- ~~**母艦を挿してフェーズ1.5 の soak を焼き、数日走らせる**~~ **走行中**（2026-08-04〜）
- ~~**`wire_gridfreq.py`（パーサ）を書く**~~ **済み**（2026-08-03。`lambda/wire_gridfreq.py`）
- ~~**`ingest` Lambda を書く**~~ **済み**（2026-08-04。`lambda/ingest/handler.py`）
- ~~**soak の結果を読む**~~ **一昼夜ぶんは済み**（2026-08-05。水晶 +3.8873 ppm、
  温度依存は有意でなく補正しない、`NtpTimebase` の実力は 0.2 ppm 級。
  → [log/2026-08-05-soak-first-day.md](log/2026-08-05-soak-first-day.md)）。
  **soak は止めていない**が、**主要な問いは片付いたので急ぎの用は無い**
- ~~**`fs` を測るファームを書く**~~ **済み**（2026-08-05。`firmware/src/main.cpp` v2。
  → [log/2026-08-05-fs-measurement-firmware.md](log/2026-08-05-fs-measurement-firmware.md)）
- **配線して `fs` を実測する** — **次の一手。** [hardware.md](hardware.md) の表の通りに繋いで焼く。
  見るのは3つ: ①**`l_pp`/`r_pp` が 0 でないこと**（0 なら DOUT が死んでいて以降は無意味）
  ②**`ovf` が 0 のままであること** ③**`fs_ppm` が `ppm`（水晶側）と一致すること**。
  **一致・不一致を語るのは半日待ってから**（`fs_resid_ns` が 0.1ppm 級に落ちるまで）。
  **これでリスク10 の残り半分が埋まる。**
  配線に手を付ける時点で soak の捕捉プロセスを落とすこと（`kill 54464 54813`）
- **アクティブアンテナを買う** — **GNSS 受信機より優先度が高い。**
  受信機は届くが、**アンテナが無いと段階1の判定を始められない**（測っているのは
  受信機の性能ではなく空の見え方で、それを決めるのはアンテナと設置場所だ）。
  **GPS/GLONASS 両対応** + SMA + 3〜5m ケーブル、2,000〜3,000円。→ [gnss.md](gnss.md)

### まだ触っていない領域

`tools/gridfreq/` の Python 参照実装、`lib/GridFreq/` の**位相推定側**（単一ビンDFT +
PPS規正。ワイヤ層だけが在る）、`terraform/`。**すべてフェーズ2（PPS同時サンプリング）が
通ってからでよい。** そこが成否の分岐点なので、先に作り込んでも無駄になりうる。

未決の問いは [open-questions.md](open-questions.md) にある。
