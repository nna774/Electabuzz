// Electabuzz ファームウェア — フェーズ1.5「時間基準の実測」
//
// **ADC を待たずに走らせる soak だ。** PCM1808 も GNSS も要らない。数日走らせて
// 手元の ESP32-S3 の水晶の実 ppm と安定度を取ることだけが目的（リスク10 の片方）。
//
// 測っているのは esp_timer のティック源、すなわち **ESP32 の 40MHz 水晶**である。
// I2S の MCLK を ESP32 から出す構成ならこの水晶が fs を決めるので結果はそのまま
// 効くが、PCM1808 モジュールの缶発振器が master になる構成では効かない。
// **どちらが master かはまだ決まっていない。** → docs/timebase.md
//
// NtpTimebase はティック源を問わないので、PCM1808 が来たら
// ticksNow() を I2S の累積サンプル数に、config.h の kTickNominalMicroHz を
// 48000 系に差し替えるだけで同じ回帰が使える。**この soak は捨て仕事にならない。**
//
// 出力は CSV。生の標本まで残したいなら tee しておけ:
//   pio device monitor | tee soak-$(date +%Y%m%d).csv
// ただし**取りこぼしても結論は失われない。** 回帰は RAM 上で積み上がっていて、
// 毎行に現在の推定が丸ごと載る。失うのは生の標本だけだ。

#include <Arduino.h>
#include <WiFi.h>
#include <esp_timer.h>

#include "MeasuringSntp.h"
#include "NtpTimebase.h"
#include "config.h"
#include "secrets.h"

namespace {

// **単調増加するティック源。** システム時刻ではない。
// esp_timer は NTP に触られないので、これが「生の水晶」に一番近い。
uint64_t ticksNow() { return static_cast<uint64_t>(esp_timer_get_time()); }

timebase::NtpTimebase gTimebase(kTickNominalMicroHz);
timebase::MeasuringSntp gSntp;
size_t gServerIndex = 0;
uint32_t gNextQueryMs = 0;
uint32_t gAttempts = 0;

// %llu が newlib の設定で死んでいても数日ぶんの記録を失わないよう、自前で書く。
const char* u64str(uint64_t v, char* buf, size_t n) {
  char tmp[21];
  size_t i = 0;
  do {
    tmp[i++] = static_cast<char>('0' + (v % 10));
    v /= 10;
  } while (v != 0 && i < sizeof(tmp));
  size_t j = 0;
  while (i > 0 && j + 1 < n) buf[j++] = tmp[--i];
  buf[j] = '\0';
  return buf;
}

void ensureWifi() {
  if (WiFi.status() == WL_CONNECTED) return;
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);  // 省電力で受信が遅れると往復遅延の分布が汚れる
  WiFi.begin(kWifiSsid, kWifiPass);
  const uint32_t deadline = millis() + kWifiConnectTimeoutMs;
  while (WiFi.status() != WL_CONNECTED && static_cast<int32_t>(millis() - deadline) < 0) {
    delay(200);
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("# wifi connected ip=%s rssi=%d\n", WiFi.localIP().toString().c_str(),
                  WiFi.RSSI());
    gSntp.begin(ticksNow);
  } else {
    Serial.println("# wifi connect failed");
    delay(kWifiRetryDelayMs);
  }
}

void logLine(const char* server, bool ok, const char* err, const timebase::SntpSample& s) {
  char b1[24], b2[24], b3[24];
  const double ppm =
      (static_cast<double>(gTimebase.fsMicroHz()) / static_cast<double>(kTickNominalMicroHz) - 1.0) *
      1e6;
  Serial.printf("%s,%s,%s,%s,%s,%d,%s,%u,%u,%.1f,%s,%.4f,%u,%u,%u,%.1f,%d\n",
                u64str(ticksNow(), b1, sizeof(b1)),
                ok ? u64str(s.unixUs, b2, sizeof(b2)) : "",
                ok ? u64str(s.ticks, b3, sizeof(b3)) : "",
                ok ? String(static_cast<uint32_t>(s.rttTicks)).c_str() : "",
                server, ok ? 1 : 0, err,
                gTimebase.obsCount(), gTimebase.rejectedCount(), gTimebase.spanSeconds(),
                gTimebase.source() == timebase::Source::kNtp ? "NTP" : "NOMINAL",
                ppm, gTimebase.residualNs(), gTimebase.fitRmsNs(), gTimebase.minRttUs(),
                temperatureRead(), WiFi.RSSI());
}

}  // namespace

void setup() {
  Serial.begin(kSerialBaud);
  delay(500);
  Serial.println();
  Serial.println("# electabuzz timebase soak v1");
  Serial.printf("# chip=%s rev=%d cpu=%uMHz xtal=%uMHz flash=%uMB\n", ESP.getChipModel(),
                ESP.getChipRevision(), getCpuFrequencyMhz(), getXtalFrequencyMhz(),
                ESP.getFlashChipSize() / (1024 * 1024));
  Serial.printf("# tick source: esp_timer (nominal %s uHz)\n",
                [] { static char b[24]; return u64str(kTickNominalMicroHz, b, sizeof(b)); }());
  Serial.println("# boot_us,unix_us,ticks,rtt_ticks,server,ok,err,"
                 "n,rejected,span_s,source,ppm,resid_ns,fit_rms_ns,min_rtt_us,temp_c,rssi");
  ensureWifi();
}

void loop() {
  ensureWifi();
  if (WiFi.status() != WL_CONNECTED) {
    delay(kWifiRetryDelayMs);
    return;
  }

  if (static_cast<int32_t>(millis() - gNextQueryMs) < 0) {
    delay(50);
    return;
  }

  const char* server = kNtpServers[gServerIndex];
  gServerIndex = (gServerIndex + 1) % kNtpServerCount;
  ++gAttempts;

  timebase::SntpSample s{};
  const bool got = gSntp.query(server, kNtpTimeoutMs, s);
  if (got) {
    // 採否は NtpTimebase が決める（RTT・単調性・外れ値）。ここでは判定しない。
    gTimebase.addObservation(s.ticks, s.unixUs, s.rttTicks);
    logLine(server, true, "", s);
  } else {
    logLine(server, false, gSntp.lastError(), s);
  }

  // 一定間隔で叩き続けると経路の周期的な混雑と同期しうるので散らす。
  gNextQueryMs = millis() + (kNtpIntervalSeconds + random(kNtpJitterSeconds)) * 1000;
}
