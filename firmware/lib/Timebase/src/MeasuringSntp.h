#pragma once
// 測定専用の SNTP クライアント。**システム時刻を一切触らない。**
//
// なぜ batch-uplink の timesync（lwIP の SNTP, SNTP_SYNC_MODE_SMOOTH）を使えないか:
// あちらはシステム時刻の進む速さ自体を制御対象にしている。それに回帰したら、
// 測っているのは水晶ではなく slew ループだ。→ docs/timebase.md
//
// 自前にしたことで手に入るものが2つある。
//   - **往復遅延が見える。** 大きい標本を捨てられる（lwIP の SNTP は見せてくれない）
//   - **ローカル側の時刻をティックで取れる。** I2S のサンプル数でも esp_timer の µs でも
//     同じ形で扱えるので、PCM1808 が来ても呼び出し側が ticksNow を差し替えるだけで済む
//
// バッチのタイムスタンプ用のシステム時刻は従来どおり SMOOTH のままでよい。役割を分ける。

#include <WiFiUdp.h>

#include <cstdint>

namespace timebase {

struct SntpSample {
  // 往復の中点 (t1+t4)/2 に対応するローカルティック。
  // サーバ時刻はこの瞬間のものとみなす（経路が対称なら真値、非対称なら
  // 一定バイアスとして切片に乗るだけで、回帰の傾きには乗らない）。
  uint64_t ticks;
  uint64_t unixUs;   // サーバの送信時刻 [µs]
  uint64_t rttTicks; // 往復遅延（ticks と同じ単位）
};

class MeasuringSntp {
 public:
  // ticksNow: 単調増加するローカルティックを返す関数。
  //   PCM1808 が来る前は esp_timer の µs、来たら I2S の累積サンプル数を渡す。
  using TicksFn = uint64_t (*)();

  bool begin(TicksFn ticksNow, uint16_t localPort = 0);
  void end();

  // 1回問い合わせる。成功したら true。
  bool query(const char* server, uint32_t timeoutMs, SntpSample& out);

  // 直近の失敗理由（成功時は ""）。ログに出して原因を切り分けるため。
  const char* lastError() const { return err_; }

 private:
  WiFiUDP udp_;
  TicksFn ticksNow_ = nullptr;
  uint32_t nonceHi_ = 0;
  uint32_t nonceLo_ = 0;
  const char* err_ = "";
};

}  // namespace timebase
