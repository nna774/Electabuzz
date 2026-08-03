#pragma once
// 動作パラメータの定数。秘密情報は secrets.h（gitignore 対象）に置く。

#include <cstdint>

// --- シリアル ---
static constexpr uint32_t kSerialBaud = 115200;

// --- 時間基準の実測（フェーズ1.5）---
//
// **公称レートであって真値ではない。** esp_timer は µs 刻みなので公称 1MHz。
// PCM1808 が来たらティック源を I2S の累積サンプル数に差し替え、ここを 48000 系の
// 値にする。NtpTimebase はティック源を問わないので、変えるのはここと ticksNow だけ。
static constexpr uint64_t kTickNominalMicroHz = 1000000ULL * 1000000ULL;

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
