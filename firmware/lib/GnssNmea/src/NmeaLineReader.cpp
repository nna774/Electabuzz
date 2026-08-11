#include "NmeaLineReader.h"

namespace gnss {

void NmeaLineReader::reset() {
  len_ = 0;
  overflowed_ = false;
  // overflowCount_ は残す。診断値なので、行が切り替わるたびに0に戻すと
  // 「あふれが起きているか」が見えなくなる（NtpTimebase::rejected_と同じ方針）。
}

bool NmeaLineReader::feed(char c) {
  if (c == '\n') {
    // '\r'が直前にあれば取り除く。
    if (len_ > 0 && buf_[len_ - 1] == '\r') --len_;
    buf_[len_] = '\0';

    const bool wasOverflowed = overflowed_;
    len_ = 0;
    overflowed_ = false;

    // あふれていた行は「見失った行」として捨てる。呼び出し側には知らせず
    // (壊れた1行のために全体を止めない)、次の行から復帰する。
    return !wasOverflowed;
  }

  if (overflowed_) {
    // あふれ中は`\n`が来るまで読み捨てる。
    return false;
  }

  if (len_ >= kMaxLineLen) {
    overflowed_ = true;
    ++overflowCount_;
    return false;
  }

  buf_[len_++] = c;
  return false;
}

}  // namespace gnss
