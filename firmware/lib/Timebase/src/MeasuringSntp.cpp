#include "MeasuringSntp.h"

#include <Arduino.h>
#include <string.h>

#if __has_include(<esp_random.h>)
#include <esp_random.h>
#else
#include <esp_system.h>
#endif

namespace timebase {
namespace {

constexpr uint16_t kNtpPort = 123;
constexpr size_t kPacketSize = 48;
// NTP epoch(1900-01-01) から UNIX epoch(1970-01-01) までの秒数。
constexpr uint64_t kNtpToUnix = 2208988800ULL;

uint32_t rd32be(const uint8_t* p) {
  return (static_cast<uint32_t>(p[0]) << 24) | (static_cast<uint32_t>(p[1]) << 16) |
         (static_cast<uint32_t>(p[2]) << 8) | static_cast<uint32_t>(p[3]);
}

void wr32be(uint8_t* p, uint32_t v) {
  p[0] = static_cast<uint8_t>(v >> 24);
  p[1] = static_cast<uint8_t>(v >> 16);
  p[2] = static_cast<uint8_t>(v >> 8);
  p[3] = static_cast<uint8_t>(v);
}

}  // namespace

bool MeasuringSntp::begin(TicksFn ticksNow, uint16_t localPort) {
  ticksNow_ = ticksNow;
  if (ticksNow_ == nullptr) {
    err_ = "no ticks fn";
    return false;
  }
  // 送信元ポートを固定しない。off-path から返答を偽装しにくくする常道。
  const uint16_t port = localPort != 0 ? localPort : static_cast<uint16_t>(49152 + (esp_random() % 16000));
  if (udp_.begin(port) != 1) {
    err_ = "udp begin";
    return false;
  }
  err_ = "";
  return true;
}

void MeasuringSntp::end() { udp_.stop(); }

bool MeasuringSntp::query(const char* server, uint32_t timeoutMs, SntpSample& out) {
  if (ticksNow_ == nullptr) {
    err_ = "not begun";
    return false;
  }

  uint8_t pkt[kPacketSize];
  memset(pkt, 0, sizeof(pkt));
  pkt[0] = 0x23;  // LI=0, VN=4, Mode=3(client)

  // Transmit Timestamp に乱数を入れておき、返答の Originate Timestamp と突き合わせる。
  // 古い応答や別サーバの取り違えをここで落とす。値そのものに意味は無い。
  nonceHi_ = esp_random();
  nonceLo_ = esp_random();
  wr32be(&pkt[40], nonceHi_);
  wr32be(&pkt[44], nonceLo_);

  // 送信直前・受信直後にティックを読む。この2点の中点をサーバ時刻に対応させる。
  if (udp_.beginPacket(server, kNtpPort) != 1) {
    err_ = "resolve";
    return false;
  }
  udp_.write(pkt, sizeof(pkt));
  const uint64_t t1 = ticksNow_();
  if (udp_.endPacket() != 1) {
    err_ = "send";
    return false;
  }

  const uint32_t deadline = millis() + timeoutMs;
  int len = 0;
  uint64_t t4 = 0;
  for (;;) {
    len = udp_.parsePacket();
    if (len > 0) {
      t4 = ticksNow_();
      break;
    }
    if (static_cast<int32_t>(millis() - deadline) >= 0) {
      err_ = "timeout";
      return false;
    }
    delay(2);
  }
  if (len < static_cast<int>(kPacketSize)) {
    err_ = "short packet";
    return false;
  }
  if (udp_.read(pkt, sizeof(pkt)) != static_cast<int>(kPacketSize)) {
    err_ = "read";
    return false;
  }

  const uint8_t mode = pkt[0] & 0x07;
  const uint8_t li = pkt[0] >> 6;
  const uint8_t stratum = pkt[1];
  if (mode != 4) {  // server
    err_ = "not a server reply";
    return false;
  }
  if (stratum == 0 || stratum > 15) {
    // stratum 0 は Kiss-o'-Death。**問い合わせ間隔を疑え。**
    err_ = "bad stratum";
    return false;
  }
  if (li == 3) {
    // サーバ自身が同期していない。規正されていない時刻に回帰しても意味が無い。
    err_ = "server unsynchronized";
    return false;
  }
  if (rd32be(&pkt[24]) != nonceHi_ || rd32be(&pkt[28]) != nonceLo_) {
    err_ = "nonce mismatch";
    return false;
  }

  const uint32_t txSec = rd32be(&pkt[40]);
  const uint32_t txFrac = rd32be(&pkt[44]);
  if (txSec == 0) {
    err_ = "zero timestamp";
    return false;
  }
  if (txSec < kNtpToUnix) {
    // 2036年のロールオーバー後は上位が巻き戻る。そのとき黙って過去を返させない。
    err_ = "pre-1970 timestamp";
    return false;
  }

  out.unixUs = (static_cast<uint64_t>(txSec) - kNtpToUnix) * 1000000ULL +
               (static_cast<uint64_t>(txFrac) * 1000000ULL >> 32);
  out.rttTicks = t4 - t1;
  out.ticks = t1 + out.rttTicks / 2;
  err_ = "";
  return true;
}

}  // namespace timebase
