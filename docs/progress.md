# 進捗

新しいものが上。各行の詳細は `log/` の該当ファイルにある。
**このファイルは索引だ。判断の理由は各ログに、現在の結論は各設計ドキュメントにある。**

| 日付 | 何が決まったか | 詳細 |
|---|---|---|
| 2026-08-08 | **AFEのC1(アンチエイリアスLPF)を15nFの受動1次RCで確定した。** ノードA(R1/R2接続点、PCM1808 L INへの配線元)からGNDへコンデンサ1個(表示コード`153`)を実装。`env:gridfreqtest`を焼き直し30秒キャプチャした結果、**C1未実装時に見られていた「トランス接続直後の数分間フルスケールに張り付く」ノイズ挙動が消失**(7202サンプル中クリッピング0件)、基本波50.015Hz・THD 0.0%を維持していることを確認した。計算値は18nFだったが在庫の15nF(許容範囲15〜22nFの下限)をそのまま採用——fc≈1.84kHzとやや高めに出るが50Hzでの位相シフトは1.6°の固定値で無視できる。`docs/hardware.md`のAFE回路図・C1の項を確定値に更新した。**残るAFEの未確定事項はTVSのみ** | [log/2026-08-08-c1-lpf-verification.md](log/2026-08-08-c1-lpf-verification.md) |
| 2026-08-07 | **ダッシュボードv1を作ってapplyし、実データで動作確認した。** `lambda/api/handler.py`(`/recent`のみ)・`lambda/store_gridfreq.py`(累積位相の差分から瞬時周波数を計算)・`dashboard/`(vanilla JS + Canvas)・`terraform/dashboard.tf`(S3+CloudFront、カスタムドメイン無し)。**「測れなかった区間を測れたように見せない」ため、`session_id`変化・想定外の間隔・`GfrqFlagDiscontinuity`のいずれかに該当する隣接点はfreqをnullにして系列を途切れさせる**——特にdiscontinuityは、タイムスタンプの間隔チェックだけでは検出できない罠だった(ファーム側`resetWindow()`がワイヤ上のレコード列を詰めて出すため)。テスト8件追加(計45件)全緑、`apply`実行(8 add/2 change)、**実際にブラウザで系統周波数のグラフ(49.98〜50.04Hz程度)が表示されることを確認した**。追加の実費は月100円未満の見込み | [log/2026-08-07-dashboard-v1.md](log/2026-08-07-dashboard-v1.md) |
| 2026-08-07 | **ingest分のterraformをapplyし、`firmware/src/secrets.h`を埋めた。** 7リソース作成成功、`ingest_url`が出た(`electabuzz-ingest`のFunction URL)。WiFiはNamazuの`tools/devices.json`から転記、HMAC鍵は新規に乱数生成して`secrets.h`と`terraform.tfvars`で揃えた。**2号機の予定は無いのでper-device鍵は使わずフラット構成。** OTA(NamazuがNVS化した理由)は検討したが**今はやらないと判断**——OTA自体が無い今はNVS化の利点が効かない。要望は[open-questions.md](open-questions.md)へメモした。`pio run -e record`は引き続き緑。**残るタスクは実機に焼いて確認するだけ** | [log/2026-08-07-terraform-apply-and-secrets.md](log/2026-08-07-terraform-apply-and-secrets.md) |
| 2026-08-07 | **`terraform/`を新規に立て、ingest分(バケット・IAM・Lambda・Function URL)を書いた。** state はNamazuと同じ保存先バケットの別key(`electabuzz.tfstate`)で独立。detect/rollup/api/watchdog/CloudFrontは対応するLambda本体が無いのでまだ書いていない。`build_lambda.sh`で`ingest.zip`(`handler.py`+`s3keys.py`+`wire_gridfreq.py`+`batch_uplink`v1.6.0)を生成できることを確認、`terraform validate`も緑。**`apply`はまだ実行していない**(費用が生じる操作なので明示の許可が要る) | [log/2026-08-07-terraform-ingest-stack.md](log/2026-08-07-terraform-ingest-stack.md) |
| 2026-08-07 | **Goertzelをfirmwareへ移植し、フェーズ2(PPS)を待たずにGFRQの記録・送信を実装した。** `firmware/lib/Goertzel/`(標準的な2次IIR再帰、状態2個。48000サンプルのバッファもtrig大量呼び出しも不要)。`NAMZ_GRIDFREQ_RECORD`ビルドモードで、`fs`がNtpTimebaseで規正できてから(NTPで600秒以上)Goertzelを起動し、`timebase_source=NTP`と正直に申告してGFRQバッチを`Uploader`で送る。**「PPSが効くのは結果を絶対時刻へ固定する後段の較正だけ」という整理に基づき、C++移植をフェーズ2待ちにしていた前回の判断を覆した。** `batch-uplink`のpinもv1.0.0→v1.6.0に上げた(Namazu側の後方互換な追加のみで、Namazu自身のpinも既にv1.6.0だった)。ホストの単体テスト(GridFreq/Timebase/Goertzel)・`pio run`全env(s3/gridfreqtest/record)は緑、**実機には未投入** | [log/2026-08-07-goertzel-cpp-port.md](log/2026-08-07-goertzel-cpp-port.md) |
| 2026-08-07 | **Goertzel(単一ビンDFT)のPython参照実装を、フェーズ2(PPS同時サンプリング)を待たずに書いた。** `tools/gridfreq/goertzel.py`は`docs/signal-processing.md`の設計(z(k)=Σx[n]exp(-j2πf_nom n/fs)、位相unwrap、累積位相)をそのまま実装。`tools/gen_synthetic.py`(合成波形)と`tools/backtest_gridfreq.py`(検証)も新規。合成波形(高調波+ノイズ+現実的なドリフト)で±1mHz(`timebase.md`の目標精度)以内を確認、今日の実キャプチャに通すとゼロクロス法(std 304mHz)より桁違いに安定(std 17.8mHz)した。**Goertzel自体はPPSの取り込み方式(方式A/B)に依存しないという判断で、意図的に既存の「フェーズ2待ち」方針を上書きした。** C++移植・firmware組み込みは引き続き未着手 | [log/2026-08-07-goertzel-reference.md](log/2026-08-07-goertzel-reference.md) |
| 2026-08-07 | **アクティブアンテナを発注した。** GPS+BD+GLONASS対応品（XYANT/NOWEPOCH、SMA Male、3m RG174、周波数1561-1608MHz、836円）を2本。現物ラベルの周波数表記で帯域を確認した上で選定し、**候補として挙がった「GPS専用」「L1/L2/L5マルチバンド」「dBiとdBを混同した誇大表記」の品は現物写真で判別して除外**した。2本にしたのは送料無料ライン(1,500円)への到達と予備確保が理由で、**2台目のGNSS受信機を買う計画があるわけではない**（それは段階1の判定後に決める既定路線のまま） | [log/2026-08-07-antenna-order.md](log/2026-08-07-antenna-order.md) |
| 2026-08-07 | **AFEの`Vcc/2`バイアス網は不要と確定した。** DMMでモジュール入力(node A)のDC電位を実測すると数mV(ほぼ0V)——モジュール側は外部パッドまで独自バイアスを引き出しておらず、チップ内部で自己バイアスできていると判断できる(同日確認した綺麗な50Hz波形・THD 0.0%とも整合)。**副産物として、OPアンプが必要だった2つの理由(急峻なフィルタ・低インピーダンスなバイアス供給)が両方消えた。** C1は当初案のSallen-Key(2次・要OPアンプ)ではなく、**受動1次RC(node A→GNDにコンデンサ1個、≈18nF、fc≈1.5kHz)で足りる見込み**——ただしまだ配線・実測はしていない机上の見立て。TVSは引き続き別枠の未確定事項 | [hardware.md](hardware.md) |
| 2026-08-07 | **`NAMZ_GRIDFREQ_TEST`ビルドで50Hzの疎通を確認した。** `tools/capture_serial.py`/`tools/spectrum.py`(新規)でI2S生サンプルをFFT・ゼロクロス法で解析。基本波50.026Hz、THD 0.0%、ゼロクロス中央値49.934Hz(std 0.30Hz)——実配線から本物の50Hzが拾えていることを確認した。**タイムスタンプに壁時計(`ticksNow()`)を使うとDMAのバースト処理を実時刻と取り違えるバグがあり、フレームカウンタ起点の仮想時刻に直した。** また間引き幅48(実効1000Hz)ではC1未実装のノイズが89〜109Hz帯にエイリアシングして出たが、間引きを200(実効240Hz)に伸ばして無相関ノイズだけを`1/√N`で落としたら50Hzが勝った。`docs/roadmap.md`フェーズ1が完了した | [log/2026-08-07-gridfreq-test-mode.md](log/2026-08-07-gridfreq-test-mode.md) |
| 2026-08-07 | **AFEを実配線してfsを実測し、リスク10（fsを駆動しているのは水晶かモジュール搭載の缶発振器か）を解消した。** `gXtal`(水晶ppm)と`gFs`(fs実測ppm)は一致しないが、差分が8点にわたり31.7〜32.9ppmとほぼ一定——`timebase.md`が予告していた「48kHzは160MHz系PLLの分数分周器で作られ、水晶とは無関係な数十ppmのずれが乗る」という予測と定量的に一致し、**差分が一定であること自体がESP32のMCLKがSCKIを駆動している証拠**になった。トランス接続直後は`l_pp`/`r_pp`がフルスケールに張り付いたが、DMM実測(約0.6VAC)とは整合しており、C1(LPF)未実装のハイインピーダンスノードが広帯域ノイズを拾っていただけと判断（R1=100kΩの電流制限設計により破壊リスクは無い）。`ovf`は全区間0で配線・DMAとも健全 | [log/2026-08-07-fs-wiring-verification.md](log/2026-08-07-fs-wiring-verification.md) |
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
| 確定済み | AC入力部（実測済み）、wire format `GFRQ` v1、**[batch-uplink](https://github.com/nna774/batch-uplink) v1.6.0**（public・切り出し済み。`Batch` の契約が確定。pinはNamazu側の後方互換な追加でv1.0.0から上げてある → [log/2026-08-07-goertzel-cpp-port.md](log/2026-08-07-goertzel-cpp-port.md)）、**AFEのC1(LPF)は15nFで確定・実装・実測確認済み**（→ [log/2026-08-08-c1-lpf-verification.md](log/2026-08-08-c1-lpf-verification.md)） |
| 手持ちハードウェア | **ESP32-S3-WROOM-1 N16R8 の DevKitC-1 系クローン**（本番用。**GPIO 33〜37 は octal PSRAM に取られていて使えない**）、**PCM1808 モジュール**（缶発振器なし版。2026-08-05 到着。**無改造で使える**。配線は [hardware.md](hardware.md)）、**無印 ESP32**（Namazu と同型の余り。予備機・差し替え先） |
| 未入手 | **アクティブアンテナ（GPS+BD+GLONASS対応品を2本発注済み。→ [log/2026-08-07-antenna-order.md](log/2026-08-07-antenna-order.md)。到着待ち）**、GNSS 受信機2台目（1台目は NEO-M8N を発注済み → [log/2026-08-04-gnss-order.md](log/2026-08-04-gnss-order.md)。**段階1の判定が出てから決める**）、AFEのTVS（**OPアンプ・C1は不要/確定になった**。→ [hardware.md](hardware.md)）。**DMM（HIOKI 3244-60）は入手済み**（2026-08-03〜、実測に使用中。この行は取得漏れの記述ミスだったので訂正） |
| 稼働中 | フェーズ1.5のsoakは2026-08-07時点で停止済み（水晶soakの一昼夜ぶんの結果は確保済み。→ [log/2026-08-05-soak-first-day.md](log/2026-08-05-soak-first-day.md)）。**代わりに実配線でのfs実測が完了し、リスク10を解消した**（→ [log/2026-08-07-fs-wiring-verification.md](log/2026-08-07-fs-wiring-verification.md)） |
| コード | **`GFRQ` の書き手と読み手が揃った。** `firmware/lib/GridFreq/`（ヘッダの組み立て）と `lambda/wire_gridfreq.py`（パーサ）。契約は `testdata/gfrq_v1_golden.hex` で両側から固定してある。**時間基準は `firmware/lib/Timebase/`**（`TimebaseEstimator` / `NtpTimebase` / `MeasuringSntp`）で、回帰は Arduino 非依存。**位相推定は `firmware/lib/Goertzel/`**（単一ビンDFTの2次IIR再帰。Python参照実装`tools/gridfreq/goertzel.py`のC++移植）。`firmware/src/main.cpp` は3つのビルドモードを持つ: 既定(`env:s3`。soak専用、位相推定も送信もしない)、`NAMZ_GRIDFREQ_TEST`(`env:gridfreqtest`。疎通確認用の生サンプルダンプ)、**`NAMZ_GRIDFREQ_RECORD`(`env:record`。フェーズ2を待たずにGoertzel+GFRQ+`Uploader`を実際に動かす。`timebase_source=NTP`)**。**`env:record`は実機に投入済みで、`fs`ロック後に実際にバッチを送れていることを確認した**（→ [log/2026-08-07-terraform-apply-and-secrets.md](log/2026-08-07-terraform-apply-and-secrets.md)）。**クラウド側は `lambda/ingest/handler.py` + `lambda/api/handler.py`(`/recent`) + `lambda/store_gridfreq.py`**（`/alert`・detect・rollupは未実装）。**`dashboard/`(vanilla JS + Canvas)も実データで動作確認済み**（→ [log/2026-08-07-dashboard-v1.md](log/2026-08-07-dashboard-v1.md)）。**`terraform/`はingest+api+dashboard分を書いて`apply`済み**。**`firmware/src/secrets.h`も埋めてある**（gitignore対象なのでworktreeからのコピーが要る）。detect/rollup/watchdogは対応するLambdaが無いのでterraformも未着手 |
| 開発環境 | repo 直下の `.venv`（Namazu と同じ形）に pytest・platformio・**boto3・batch-uplink v1.6.0**。テストは `.venv/bin/python -m pytest lambda/tests` / `firmware/lib/GridFreq/test/run.sh` / `firmware/lib/Timebase/test/run.sh` / `firmware/lib/Goertzel/test/run.sh`。ビルドは `.venv/bin/pio run -d firmware`(`-e s3`/`-e gridfreqtest`/`-e record`)。**`firmware/src/secrets.h` は gitignore 対象**（雛形は `secrets.h.example`。`env:record`を使うには`kDeviceId`/`kIngestUrl`/`kHmacSecret`を埋める） |

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
- ~~**配線して `fs` を実測する**~~ **済み**（2026-08-07。[hardware.md](hardware.md) の確定部分を
  実配線し、①`l_pp`/`r_pp`が非0 ②`ovf`が0のまま ③`gFs`と`gXtal`のppm**差分が一定**
  （単純な一致ではない——`gFs`には水晶と無関係な分周器由来の数十ppmが乗る、と
  [timebase.md](timebase.md)が予告していた通り）の3点を確認。**リスク10を解消した。**
  → [log/2026-08-07-fs-wiring-verification.md](log/2026-08-07-fs-wiring-verification.md)
- ~~**アクティブアンテナを買う**~~ **発注済み**（2026-08-07。GPS+BD+GLONASS対応品を2本、
  836円/本。→ [log/2026-08-07-antenna-order.md](log/2026-08-07-antenna-order.md)）。
  **到着したら段階1の判定（捕捉衛星数・fix安定性のログ取り）に進める**
- ~~**Goertzelをfirmwareへ移植し、GFRQを実際に送る**~~ **済み**（2026-08-07。
  `firmware/lib/Goertzel/` + `env:record`。`timebase_source=NTP`で送信するところまで
  実装したが**実機投入はまだ**。→ [log/2026-08-07-goertzel-cpp-port.md](log/2026-08-07-goertzel-cpp-port.md)）
- ~~**`terraform/`を新規に立て、ingest分を書く**~~ **済み**（2026-08-07。
  バケット・IAM・Lambda・Function URL。
  → [log/2026-08-07-terraform-ingest-stack.md](log/2026-08-07-terraform-ingest-stack.md)）
- ~~**`terraform apply`して`secrets.h`を埋める**~~ **済み**（2026-08-07。
  `ingest_url`が出た。WiFi・`kDeviceId`・HMAC鍵も埋めた(フラット構成、per-device鍵は未使用)。
  → [log/2026-08-07-terraform-apply-and-secrets.md](log/2026-08-07-terraform-apply-and-secrets.md)）
- ~~**`env:record`を実機で焼いて確認する**~~ **済み**（2026-08-07。soakを止めて
  焼いた。`fs`ロック後にGoertzelが起動し、実際に`series/`へバッチが着弾することを
  S3/APIから確認した。→ [log/2026-08-07-terraform-apply-and-secrets.md](log/2026-08-07-terraform-apply-and-secrets.md)）
- ~~**ダッシュボードv1を作る**~~ **済み**（2026-08-07。`/recent`のみのapi + vanilla JSの
  ダッシュボード。実データ(49.98〜50.04Hz程度)がグラフに出ることをブラウザで確認した。
  → [log/2026-08-07-dashboard-v1.md](log/2026-08-07-dashboard-v1.md)）
- ~~**AFEのC1(LPF)を実装・確定する**~~ **済み**（2026-08-08。15nFを実装、
  `env:gridfreqtest`での再測定でクリッピング消失・THD 0.0%維持を確認。
  → [log/2026-08-08-c1-lpf-verification.md](log/2026-08-08-c1-lpf-verification.md)）

### まだ触っていない領域

**フェーズ2(PPS同時サンプリング)そのもの**（GNSS本体が未到着）。時刻偏差(TE)の絶対値・
欠測区間の可視化はPPS到着後。**`terraform/`はingest+api+dashboard分のみ**——detect/rollup/watchdogに対応する
Lambdaがまだ無いので、それらのterraformも未着手（→ [log/2026-08-07-terraform-ingest-stack.md](log/2026-08-07-terraform-ingest-stack.md)）。
**位相推定(Goertzel)のC++移植とGFRQ送信は2026-08-07にフェーズ2を待たずに完了した**
（→ [log/2026-08-07-goertzel-cpp-port.md](log/2026-08-07-goertzel-cpp-port.md)。
理由: Goertzel自体はLチャンネルの生サンプルだけで完結する計算で、PPSをどう絶対時刻に
固定するか(方式A/Bの選択)には依存しないと判断したため）。**残るのは実機投入による
実地確認**（上記タスク）と、フェーズ2が通った後の`timebase_source`切り替え。

未決の問いは [open-questions.md](open-questions.md) にある。
