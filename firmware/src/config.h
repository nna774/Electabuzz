#pragma once
// 動作パラメータの定数。秘密情報は secrets.h（gitignore 対象）に置く。

#include <cstdint>

// --- シリアル ---
static constexpr uint32_t kSerialBaud = 115200;

// --- 時間基準の実測（フェーズ1.5）---
//
// **公称レートであって真値ではない。** esp_timer は µs 刻みなので公称 1MHz。
static constexpr uint64_t kTickNominalMicroHz = 1000000ULL * 1000000ULL;

// **`fs` の公称値。真値ではない。** これは I2S ドライバへの「要求」であって、
// 実際に何 Hz で出てくるかは NtpTimebase が測って答える。
// **この定数を「サンプルレート」として計算に使うな**（不変条件 → docs/timebase.md）。
// 使ってよいのは (a) ドライバへの要求 (b) 回帰の初期値 (c) 30ms 程度の内挿、の3つだけだ。
static constexpr uint32_t kFsNominalHz = 48000;
static constexpr uint64_t kFsNominalMicroHz = static_cast<uint64_t>(kFsNominalHz) * 1000000ULL;

// --- I2S / PCM1808 ---
//
// **ピンは docs/hardware.md の表と一致させること。** 選定理由もあちらにある。
// GPIO 33〜37 は octal PSRAM、26〜32 は flash、43/44 はコンソール、19/20 は USB、
// 0/3/45/46 はストラップ。避けた結果がこれだ。
static constexpr int kI2sPinMclk = 16;  // PCM1808 の SCK（SCKI）。BCK ではない
static constexpr int kI2sPinBclk = 17;  // PCM1808 の BCK
static constexpr int kI2sPinLrck = 18;  // PCM1808 の LRC
static constexpr int kI2sPinData = 15;  // PCM1808 の OUT（ESP32 から見て入力）

// DMA は余裕を持たせる。**溢れたら fs の回帰が壊れる**（読めなかったフレームは
// 数えられないので、ティック源が実時間に対して遅れる）。8×512 で約 85ms ぶん。
static constexpr int kI2sDmaBufCount = 8;
static constexpr int kI2sDmaBufFrames = 512;
// 1回の i2s_read で掴む量。フレーム = 2ch × 32bit = 8 バイト。
static constexpr size_t kI2sReadFrames = 512;
// I2S を吸い出す間隔。WiFi や SNTP が詰まっても止まらないよう専用タスクに置く。
static constexpr uint32_t kI2sPumpIntervalMs = 5;

// 問い合わせ間隔。回帰の確度を決めるのは主に**時間幅**であって密度ではないので、
// 短くしても大して得をしない。公開 NTP サーバへの礼儀の側を優先して長めに取る。
// 2台を交互に叩くので、各サーバから見た間隔はこの倍になる。
static constexpr uint32_t kNtpIntervalSeconds = 128;
static constexpr uint32_t kNtpJitterSeconds = 64;  // 同期して叩かないための散らし
static constexpr uint32_t kNtpTimeoutMs = 2000;

// 経路を独立にしたいので別組織のサーバを2台。片方が詰まっても回帰が止まらない。
static constexpr const char* kNtpServers[] = {
    "ntp.nict.jp",
    "ntp.jst.mfeed.ad.jp",
};
static constexpr size_t kNtpServerCount = sizeof(kNtpServers) / sizeof(kNtpServers[0]);

// --- WiFi ---
static constexpr uint32_t kWifiConnectTimeoutMs = 20000;
static constexpr uint32_t kWifiRetryDelayMs = 5000;

// --- NAMZ_GRIDFREQ_TEST（フェーズ1疎通確認。tools/capture_serial.py 用）---
//
// 48kHz の生サンプルはそのままではシリアル(115200baud)の帯域を超える。
// boxcar平均で間引く（Namazuの地震計がオーバーサンプル平均で使っているのと同じ手法。
// → docs/hardware.md）。48で割ると実効レート1000Hzで、50Hz確認には十分な上、
// ナイキストの余裕もある。**この間引きはTE級の精度を主張しない、粗いチェック用**
static constexpr uint32_t kGridFreqTestDecimate = 200;

// --- NAMZ_GRIDFREQ_RECORD（フェーズ2を待たずに実測・記録・送信を開始するモード）---
// → docs/log/2026-08-07-goertzel-cpp-port.md
static constexpr uint32_t kMaxRamBatches = 4;
static constexpr const char* kSpillDir = "/gfrq_spill";
// timesync（システム時刻用の別SNTP、batch_start_us用）が一度に補正してよい上限。
// 超えたらslewでなくstepで一発補正する。Namazuと同じ値。
static constexpr uint32_t kTimeSyncStepThresholdSeconds = 10;

// --- pull型OTA（→ docs/ota.md）---
//
// ダッシュボード配信で使っている既存のS3+CloudFrontに`ota/`プレフィックスで
// 相乗りする。秘密ではなく公開URL（ダッシュボード自体が認証なし公開）なので、
// NVSではなくコンパイル時定数で持つ——secrets.hに置く必要がない
// （デバイス個体差ではなくデプロイ差に属する値で、Electabuzzは2号機の予定が
// 無いフラット構成なので、ここに直接書いても複数デバイスへの秘密流出は起きない）。
// terraformでdashboardを作り直すとURLが変わるので、その時だけ更新が要る。
static constexpr const char* kOtaBaseUrl = "https://d749zv0enwqn1.cloudfront.net";
// バージョン不一致を見つけてから取得に失敗した場合の再試行間隔。
// バックオフ無しだとloop()の周期(50ms)ごとに取得を再試行し、そのたびにRAMキューを
// spillへ退避する処理が走り続けて実測に影響しうる（Namazuが実機で踏んだ不具合と
// 同じ原因。→ docs/ota.md「実機で踏んだ不具合」）。
static constexpr int64_t kOtaRetryBackoffUs = 60LL * 1000000LL;

// --- ステータス表示LED（2026-08-09 実機確認。→ docs/log/2026-08-09-led-button-hardware-probe.md）---
//
// オンボードのWS2812アドレッサブルRGB LED。GPIO48で実機確認済み。
// `neopixelWrite()`（Arduino-ESP32コア組み込み、追加ライブラリ不要）で駆動する。
static constexpr int kWs2812Pin = 48;
// 常時点灯前提なので眩しすぎない値に絞る（0〜255）。実機で40は眩しすぎると
// フィードバックがあり、15に下げた(2026-08-09)。
static constexpr uint8_t kWs2812Brightness = 15;
// 回転速度の倍率（LedStatus.h参照）。素の対応(gain=1)は実系統の変動幅
// (数十mHzオーダー)に対して回転が遅すぎるため底上げする。20なら
// 「1回転=0.05サイクル(50Hz系で1msの時刻偏差相当)」まで感度が上がる。
static constexpr uint32_t kCyclesToHueGain = 20;

// 外付けの単色LED、4本。WS2812は周波数偏差の連続値表示(回転)に使うので、
// こちらは独立した二値状態それぞれに1本ずつ割り当てて役割を分ける
// （1本に複数の意味を詰め込むと色や点滅パターンの解釈が要る。複数あるなら
// 単純にON/OFFだけで済ませた方が遠目でも判別しやすい）。
// いずれもdocs/hardware.mdの除外リスト（33-37/26-32/43-44/19-20/0-3-45-46/15-18）
// に当たらない、本コード内で他に未使用のGPIO。
// 4・5・6・7は基板シルクで隣接した1列に並んでおり、実配線がしやすい
// (2026-08-09、現物写真で確認)。4本ともここに揃えてある。
static constexpr int kLedTimebaseLockPin = 4;    // 緑LED前提。fsがNTPでロック済み(HIGH)/NOMINAL(LOW)
static constexpr int kLedSpillBacklogPin = 5;    // 黄LED前提。LittleFSへのspillが溜まっている(HIGH)
// 青LED前提。WS2812の回転方向だけでは「今速いか遅いか」が瞬時に読めない
// というフィードバックを受けて追加(2026-08-09)。基準周波数より速い(HIGH)/
// 遅いか同じ(LOW)。WS2812とセットで見れば「速さ(色)」と「向き(この点灯)」が揃う。
static constexpr int kLedFastSlowPin = 6;
static constexpr int kLedWifiPin = 7;            // 赤LED前提。切断中(HIGH)/接続中は消灯

// GPIO8は同じ列(4/5/6/7の続き)にあり配線しやすいので、フェーズ2(PPS)の
// 「PPSロック済み」を示すLED用に割り当てた(2026-08-12)。**PPS信号自体は既存I2Sの
// Rチャンネルに載る設計(→ docs/timebase.md)なので新規GPIOは要らない**——
// 要るのはロック状態を示す表示用の1本だけ。他用途に転用しないこと。
static constexpr int kLedPpsLockPin = 8;  // 緑LED前提。gPps.source()==kPps(HIGH)/未ロック(LOW)

// --- GNSS UART (→ docs/hardware.md「GNSS(NEO-M8N) 配線」節。設計案・実配線はまだ) ---
//
// **`env:record`のGoertzel/gFs用ピン(15-18)・LED用ピン(4-8)・WS2812(48)・
// 除外リスト(33-37/26-32/43-44/19-20/0-3-45-46)のいずれにも当たらない未使用GPIO。**
static constexpr int kGnssUartRxPin = 14;        // GPIO14(ESP32 RX)← GNSSモジュールのTXD
static constexpr int kGnssUartTxPin = 13;        // GPIO13(ESP32 TX)→ GNSSモジュールのRXD
static constexpr uint32_t kGnssUartBaud = 9600;  // u-bloxの既定ボーレート

// --- PPSエッジ検出(R ch)。→ firmware/lib/PpsEdge/ ---
//
// **`kPpsEdgeThreshold`は未校正のプレースホルダである。** R ch AFE(まだ実配線して
// いない)を配線し、実際のPPSパルス波形(振幅・立ち上がり時定数)を捕捉してから
// 較正すること(→ docs/log/2026-08-12-pps-edge-detector-impl.md)。今の値は
// 「型を合わせるためだけの仮の数字」で、実測の裏付けが無い。
static constexpr double kPpsEdgeThreshold = 100000.0;  // TODO: 実測後に決める
// PPSは1Hzなので、その半分の秒数ぶんを不応期に取る(→ PpsEdgeDetector.h)。
static constexpr uint64_t kPpsEdgeRefractorySamples = kFsNominalHz / 2;

// --- AFE: ADCコード → v_rms_mv(トランス二次側の実効値) 換算 (2026-08-14) ---
//
// `v_rms_mv`の基準点はトランス二次側[mV]と決定済み(→ docs/wire-format.md,
// docs/log/2026-08-13-vrms-basis-point-decision.md)。**壁側への換算はここに
// 持たない**——巻数比は個体差があり未校正なので、ワイヤフォーマットには
// 分圧比だけで完結する量を乗せる(壁側が要る場面はdownstream側の仕事)。
//
// ここの定数は`fs`と違って実測で追い続けている量ではなく、固定の回路設計値
// (R1/R2)とデータシート値・実測1点(VCC)から逆算するだけの**近似**。
static constexpr double kAfeR1Ohms = 100000.0;                    // docs/hardware.md
static constexpr double kAfeR2Ohms = 6800.0;                      // docs/hardware.md
static constexpr double kAdcInputImpedanceOhms = 60000.0;         // PCM1808 datasheet typ.
// R2とADC入力インピーダンス(ADCが分圧網を負荷する分)の並列合成。
static constexpr double kAfeR2EffOhms =
    (kAfeR2Ohms * kAdcInputImpedanceOhms) / (kAfeR2Ohms + kAdcInputImpedanceOhms);
// 実効分圧比 k = R2eff/(R1+R2eff) ≒ 0.0576(docs/hardware.md記載の値と一致)。
static constexpr double kAfeDividerRatio = kAfeR2EffOhms / (kAfeR1Ohms + kAfeR2EffOhms);
// DevKitの5Vピン実測値(2026-08-05、テスタ。→ docs/hardware.md。2026-08-15に
// DC再実測して4.83Vとほぼ同じ値を確認済み——経年ドリフトは無罪と確定した)。
// フルスケールが0.6×VCCで決まるため、電源の取りかたを変えたらここも直すこと。
static constexpr double kAdcVccVolts = 4.84;
// PCM1808は24bit符号付き。i2s_readは32bit枠にMSB詰めで来るのを>>8で戻すので
// フルスケール振幅は2^23(main.cppのpumpI2s()参照)。
static constexpr double kAdcFullScaleCode = 8388608.0;  // 2^23

// R1/R2/VCCの理論値だけで組んだ上の換算式は、実測(DMM)と比べると系統的に低く出る
// ことが分かった(2026-08-15)。3つの容疑者を実測で順に消去した:
//   1. 分圧網(R1/R2/ADC入力インピーダンス) — node A(PCM1808のL IN、分圧後・
//      GND基準)をDMMで直接実測して0.577Vと確認。二次側実測10.21V(PR #45)
//      との比は≒0.0565で、理論分圧比kAfeDividerRatio(≒0.0576)とのズレは
//      1.8%(抵抗の公称誤差の範囲)。**無罪。**
//   2. VCCの経年ドリフト — 2026-08-05実測4.84Vに対し2026-08-15にDC再実測して
//      4.83V。ほぼ同じ。**無罪。**
//   3. Goertzelの振幅推定式(`ampCode = 2×magnitude/N`) — 合成正弦波で1%以内の
//      一致を確認済み(firmware/lib/Goertzel/test/test_goertzel.cpp)。**無罪。**
// 残る容疑は「フルスケールコード(2^23)が本当に0.6×VCCのVpp入力レンジに
// 対応するか」という**データシートの解釈そのもの**だけになった——オーディオ
// 用ADCでは0.6×VCCがheadroomを見込んだ公称値で、物理クリップ点はもっと外側、
// というケースがありうる。オシロでの波形直接確認かデータシートの当該項目の
// 読み直しをしないと最終確定はできないので、それまでは実測との比をそのまま
// 経験係数として掛ける。導出: docs/log/2026-08-15-afe-empirical-calibration.md。
// **1点校正でしかない。** 複数回・複数条件(負荷変動・気温)での再検証はこれから。
static constexpr double kAdcAmplitudeCalFactor = 1.182;
