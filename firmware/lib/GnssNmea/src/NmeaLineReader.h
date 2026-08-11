#pragma once
// GNSS UART(Serial1)から届くバイト列を1行(NMEAセンテンス)ずつに組み立てる。
// → docs/log/2026-08-12-gnss-pps-wiring-plan.md
//
// **Arduinoに依存しない。** `Serial1.read()`が返す1バイトをそのまま`feed()`に
// 渡せる形にしてあるので、実際のUART読み出しループ(main.cpp側、未実装)は
// このクラスへバイトを流し込むだけの薄い糖衣になる。ホストのg++でテストできる
// のはこの境界を意図的に引いてあるからだ(→ PpsEdgeDetector/PpsTimebaseと同じ方針)。
//
// **固定長バッファで動く。動的確保はしない。** NMEAセンテンスは仕様上82バイト以内
// (先頭`$`〜末尾`<CR><LF>`まで)なので、余裕を見て`kMaxLineLen`を確保しておけば足りる。
// あふれた場合は「行を見失った」とみなして次の`\n`まで静かに読み捨て、次の行から
// 復帰する——1行壊れても以後の受信を止めないための設計。

#include <cstddef>
#include <cstdint>

namespace gnss {

class NmeaLineReader {
 public:
  // `$`から`\r\n`直前までを収める。NMEA仕様上82バイト以内なので余裕を見て128。
  static constexpr size_t kMaxLineLen = 128;

  // 1バイト食わせる。行末(`\n`)を検出したら true を返す。そのときの行の中身は
  // line()/lineLen() で取れる(次のfeed()を呼ぶまで有効)。`\r`は末尾から除く。
  bool feed(char c);

  const char* line() const { return buf_; }
  size_t lineLen() const { return len_; }

  // あふれ(バッファ超過で読み捨てた行)の累計。診断用。
  uint32_t overflowCount() const { return overflowCount_; }

  void reset();

 private:
  char buf_[kMaxLineLen + 1] = {};
  size_t len_ = 0;
  bool overflowed_ = false;
  uint32_t overflowCount_ = 0;
};

}  // namespace gnss
