// NmeaLineReader(バイト列→行組み立て)のテスト。Arduinoに依存しないのでホストの
// g++で走る。実際のUART入力(main.cpp側、未実装)はこのクラスへバイトを1個ずつ
// 流し込むだけになるので、ここで検証するのは行の切り出しとあふれからの復帰。

#include <cstdio>
#include <cstring>
#include <string>

#include "NmeaLineReader.h"

static int gFailures = 0;

static void check(const char* name, bool ok) {
  printf("%s %s\n", ok ? "ok  " : "FAIL", name);
  if (!ok) ++gFailures;
}

int main() {
  // --- 1. 1行を正しく切り出すか(\r\n終端、\rは除く) ---
  {
    gnss::NmeaLineReader r;
    const std::string in = "$GNGGA,hello*47\r\n";
    bool gotLine = false;
    for (char c : in) {
      if (r.feed(c)) gotLine = true;
    }
    check("\\nで行が確定する", gotLine);
    check("行の中身が正しい(\\rは除く)", std::strcmp(r.line(), "$GNGGA,hello*47") == 0);
  }

  // --- 2. 複数行を続けて正しく切り出せるか ---
  {
    gnss::NmeaLineReader r;
    const std::string in = "$AAA*00\r\n$BBB*11\r\n$CCC*22\r\n";
    std::string lines[8];
    int n = 0;
    for (char c : in) {
      if (r.feed(c)) lines[n++] = r.line();
    }
    check("3行とも切り出せる", n == 3);
    check("1行目", lines[0] == "$AAA*00");
    check("2行目", lines[1] == "$BBB*11");
    check("3行目", lines[2] == "$CCC*22");
  }

  // --- 3. バッファ超過(あふれ)からの復帰 ---
  {
    gnss::NmeaLineReader r;
    // kMaxLineLen(128)を超える長い行を1本流し込む。
    std::string longLine(200, 'X');
    std::string in = "$" + longLine + "*00\r\n$GOOD*99\r\n";
    std::string lines[8];
    int n = 0;
    for (char c : in) {
      if (r.feed(c)) lines[n++] = r.line();
    }
    check("あふれた行は破棄され、後続の行だけ拾える", n == 1 && lines[0] == "$GOOD*99");
    check("あふれ回数が記録される", r.overflowCount() == 1);
  }

  // --- 4. reset()で状態が初期化されるか(overflowCountは残る) ---
  {
    gnss::NmeaLineReader r;
    std::string longLine(200, 'X');
    std::string in1 = "$" + longLine;  // \nを送らずreset()する(行の途中で切る想定)
    for (char c : in1) r.feed(c);
    check("あふれが記録されている", r.overflowCount() == 1);

    r.reset();

    const std::string in2 = "$FRESH*01\r\n";
    bool gotLine = false;
    for (char c : in2) {
      if (r.feed(c)) gotLine = true;
    }
    check("reset後は新しい行を正しく読める", gotLine && std::strcmp(r.line(), "$FRESH*01") == 0);
    check("あふれ回数(診断値)はresetで消えない", r.overflowCount() == 1);
  }

  if (gFailures == 0) {
    printf("all tests passed\n");
    return 0;
  }
  printf("%d test(s) failed\n", gFailures);
  return 1;
}
