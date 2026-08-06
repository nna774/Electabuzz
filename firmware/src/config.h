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
