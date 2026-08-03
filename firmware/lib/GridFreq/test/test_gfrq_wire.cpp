// GFRQ v1 を Batch に載せる層のテスト。
//
// 構造体の宣言を読み直すのではなく、**出来上がったバイト列を offset で読む**。
// docs/wire-format.md が offset で書かれている以上、検証もその形でないと
// 「構造体と同じ間違いをした」ことに気づけない。

#include <cctype>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <vector>

#include "GridFreqWire.h"

// ゴールデンフィクスチャの在処は run.sh が渡す。
#ifndef GFRQ_GOLDEN_PATH
#define GFRQ_GOLDEN_PATH "../../../../testdata/gfrq_v1_golden.hex"
#endif

static int gFailures = 0;

static void check(const char* name, bool ok) {
  printf("%s %s\n", ok ? "ok  " : "FAIL", name);
  if (!ok) ++gFailures;
}

static void checkEq(const char* name, unsigned long long got,
                    unsigned long long want) {
  if (got == want) { printf("ok   %s\n", name); return; }
  printf("FAIL %s: want %llu, got %llu\n", name, want, got);
  ++gFailures;
}

static void checkEqHex(const char* name, uint32_t got, uint32_t want) {
  if (got == want) { printf("ok   %s\n", name); return; }
  printf("FAIL %s: want 0x%08X, got 0x%08X\n", name, want, got);
  ++gFailures;
}

// リトルエンディアンでの読み出し。構造体を経由しないのが眼目。
static uint16_t rd16(const uint8_t* p, size_t off) {
  return static_cast<uint16_t>(p[off] | (p[off + 1] << 8));
}
static uint32_t rd32(const uint8_t* p, size_t off) {
  uint32_t v = 0;
  for (int i = 3; i >= 0; --i) v = (v << 8) | p[off + i];
  return v;
}
static uint64_t rd64(const uint8_t* p, size_t off) {
  uint64_t v = 0;
  for (int i = 7; i >= 0; --i) v = (v << 8) | p[off + i];
  return v;
}

// '#' から行末までコメント、空白は全て無視。フィクスチャの書式は
// testdata/gfrq_v1_golden.hex の頭に書いてある。
static bool loadHex(const char* path, std::vector<uint8_t>& out) {
  FILE* fp = std::fopen(path, "rb");
  if (!fp) { printf("FAIL フィクスチャを開けない: %s\n", path); return false; }
  int hi = -1;
  for (int c = std::fgetc(fp); c != EOF; c = std::fgetc(fp)) {
    if (c == '#') {
      while (c != EOF && c != '\n') c = std::fgetc(fp);
      continue;
    }
    if (std::isspace(c)) continue;
    int v;
    if (c >= '0' && c <= '9') v = c - '0';
    else if (c >= 'a' && c <= 'f') v = c - 'a' + 10;
    else if (c >= 'A' && c <= 'F') v = c - 'A' + 10;
    else { printf("FAIL フィクスチャに16進でない文字: '%c'\n", c); std::fclose(fp); return false; }
    if (hi < 0) { hi = v; continue; }
    out.push_back(static_cast<uint8_t>((hi << 4) | v));
    hi = -1;
  }
  std::fclose(fp);
  if (hi >= 0) { printf("FAIL フィクスチャの16進が奇数桁\n"); return false; }
  return true;
}

int main() {
  // --- crc32 が zlib.crc32 と同じ版であること ---
  // ここが違うと Lambda 側が全バッチを壊れていると判定する。既知ベクタで固定する。
  {
    checkEqHex("crc32(\"123456789\")", gridfreq::crc32("123456789", 9), 0xCBF43926u);
    checkEqHex("crc32(空)", gridfreq::crc32("", 0), 0u);
    checkEqHex("crc32(\"a\")", gridfreq::crc32("a", 1), 0xE8B7BE43u);
    const uint8_t zeros[4] = {0, 0, 0, 0};
    checkEqHex("crc32(00000000)", gridfreq::crc32(zeros, 4), 0x2144DF1Cu);
  }

  // --- 寸法。1バッチ = 64 + 30×12 = 424 バイト ---
  {
    Batch* b = gridfreq::newBatch();
    check("valid", b->valid());
    b->begin(0);
    checkEq("空でもヘッダぶんはある", b->size(), 64);
    bool allAdded = true;
    for (uint32_t i = 0; i < gridfreq::kRecordsPerBatch; ++i) {
      allAdded = allAdded && gridfreq::addRecord(*b, i, 10500, 0);
    }
    check("30件積める", allAdded);
    check("30件で満杯", b->isFull());
    check("満杯なら拒否", !gridfreq::addRecord(*b, 0, 0, 0));
    checkEq("バッチ長", b->size(), 424);
    checkEq("tail は使わない", b->tailRemaining(), 0);
    delete b;
  }

  // --- ヘッダが仕様どおりの offset に載る ---
  {
    Batch* b = gridfreq::newBatch();
    b->begin(1750000000123456ull);
    gridfreq::addRecord(*b, 0, 0, 0);
    gridfreq::addRecord(*b, 3276800, 10500, 0);  // 50サイクルぶん進む

    gridfreq::HeaderFields f;
    f.device_id = 0x0102;
    f.session_id = 42;
    f.f_nominal_mhz = 50000;
    f.fs_measured_uhz = 47998123456ull;  // 47998.123456 Hz
    f.tb_obs_count = 1234;
    f.tb_residual_ns = 900;
    f.flags = kGfrqFlagPpsLocked | kGfrqFlagGnssFix;
    f.timebase_source = kGfrqTbPps;
    f.soc_temp_c = -5;
    gridfreq::fillHeader(*b, f);

    const uint8_t* p = b->bytes();
    checkEqHex("magic", rd32(p, 0), 0x47465251u);
    check("magic のバイト順", p[0] == 'Q' && p[1] == 'R' && p[2] == 'F' && p[3] == 'G');
    checkEq("version", p[4], 1);
    checkEq("record_format", p[5], 0);
    checkEq("header_len", rd16(p, 6), 64);
    checkEq("batch_start_us は Batch::startUs()", rd64(p, 8), 1750000000123456ull);
    checkEq("device_id", rd32(p, 16), 0x0102);
    checkEq("record_count は Batch::recordCount()", rd32(p, 20), 2);
    checkEq("record_rate_mhz は 1Hz", rd32(p, 24), 1000);
    checkEq("session_id", rd32(p, 28), 42);
    checkEq("f_nominal_mhz", rd32(p, 32), 50000);
    checkEq("fs_measured_uhz", rd64(p, 36), 47998123456ull);
    checkEq("tb_obs_count", rd32(p, 44), 1234);
    checkEq("tb_residual_ns", rd32(p, 48), 900);
    checkEq("flags", rd16(p, 52), 0x0003);
    checkEq("timebase_source", p[54], 2);
    check("soc_temp_c は符号付き", static_cast<int8_t>(p[55]) == -5);
    checkEq("reserved は0で埋まる", rd32(p, 56), 0);

    // レコードの並び（2件目の 12 バイト）
    const uint8_t* r = b->records() + 12;
    checkEq("cycles_q16", rd64(r, 0), 3276800);
    checkEq("v_rms_mv", rd16(r, 8), 10500);
    checkEq("record flags", rd16(r, 10), 0);
    delete b;
  }

  // --- crc32 の対象は records() だけ ---
  {
    Batch* b = gridfreq::newBatch();
    b->begin(1000);
    for (int i = 0; i < 3; ++i) gridfreq::addRecord(*b, i, 100, 0);

    gridfreq::HeaderFields f;
    f.device_id = 1;
    gridfreq::fillHeader(*b, f);
    const uint32_t crc = rd32(b->bytes(), 60);
    checkEqHex("crc は records() 上で再計算できる",
               gridfreq::crc32(b->records(), b->recordsSize()), crc);

    // ヘッダの中身を変えても crc は動かない（自分を含めていない）
    f.device_id = 999;
    gridfreq::fillHeader(*b, f);
    checkEqHex("ヘッダを変えても crc は同じ", rd32(b->bytes(), 60), crc);

    // レコードを1ビット変えたら crc は動く
    gridfreq::HeaderFields g;
    Batch* c = gridfreq::newBatch();
    c->begin(1000);
    for (int i = 0; i < 3; ++i) gridfreq::addRecord(*c, i, 100, i == 2 ? 1 : 0);
    gridfreq::fillHeader(*c, g);
    check("レコードが違えば crc も違う", rd32(c->bytes(), 60) != crc);
    delete c;
    delete b;
  }

  // --- ヘッダを書いてもレコードは侵されない ---
  {
    Batch* b = gridfreq::newBatch();
    b->begin(5);
    gridfreq::addRecord(*b, 0xAABBCCDDEEFF0011ull, 0x2233, 0x4455);
    gridfreq::HeaderFields f;
    gridfreq::fillHeader(*b, f);
    checkEq("レコードが無傷", rd64(b->records(), 0), 0xAABBCCDDEEFF0011ull);
    checkEq("レコードの直前がヘッダ末尾", static_cast<size_t>(b->records() - b->bytes()), 64);
    delete b;
  }

  // --- begin() で巻き戻すと前のヘッダが残らない ---
  // 送信基盤は bytes() をそのまま POST する。前バッチの残骸が頭に残っていると、
  // 「30件のはずが2件」のようなバッチが黙って着弾する。
  {
    Batch* b = gridfreq::newBatch();
    b->begin(1);
    for (int i = 0; i < 5; ++i) gridfreq::addRecord(*b, i, 0, 0);
    gridfreq::HeaderFields f;
    gridfreq::fillHeader(*b, f);
    b->begin(2);
    checkEq("magic が消えている", rd32(b->bytes(), 0), 0);
    gridfreq::addRecord(*b, 0, 0, 0);
    gridfreq::fillHeader(*b, f);
    checkEq("record_count が積み直した数になる", rd32(b->bytes(), 20), 1);
    checkEq("batch_start_us が更新される", rd64(b->bytes(), 8), 2);
    delete b;
  }

  // --- ゴールデンフィクスチャと1バイトも違わない ---
  // 版・CRC の範囲・オフセット・エンディアン・パディングの有無を一度に固定する。
  // ここが落ちたときは、まず**フィクスチャではなく実装を疑え**。
  // 書き換えてよいのは形式を変えたとき（version を上げるとき）だけだ。
  {
    std::vector<uint8_t> want;
    if (loadHex(GFRQ_GOLDEN_PATH, want)) {
      Batch* b = gridfreq::newBatch();
      b->begin(1750000000123456ull);
      for (uint32_t i = 0; i < gridfreq::kRecordsPerBatch; ++i) {
        gridfreq::addRecord(*b, 3276800ull * i, 10500, 0);  // 公称50Hzちょうど
      }
      gridfreq::HeaderFields f;
      f.device_id = 2;
      f.session_id = 7;
      f.f_nominal_mhz = 50000;
      f.fs_measured_uhz = 47998123456ull;
      f.tb_obs_count = 3600;
      f.tb_residual_ns = 120;
      f.flags = kGfrqFlagPpsLocked | kGfrqFlagGnssFix;
      f.timebase_source = kGfrqTbPps;
      f.soc_temp_c = 41;
      gridfreq::fillHeader(*b, f);

      checkEq("フィクスチャの長さ", want.size(), b->size());
      size_t diff = want.size();
      if (want.size() == b->size()) {
        for (size_t i = 0; i < want.size(); ++i) {
          if (want[i] != b->bytes()[i]) { diff = i; break; }
        }
        if (diff == want.size()) {
          printf("ok   ゴールデンフィクスチャと一致\n");
        } else {
          printf("FAIL ゴールデンフィクスチャと不一致: offset %zu で want 0x%02X, got 0x%02X\n",
                 diff, want[diff], b->bytes()[diff]);
          ++gFailures;
        }
      }
      checkEqHex("フィクスチャの crc32", rd32(b->bytes(), 60), 0xE849A2B8u);
      delete b;
    } else {
      ++gFailures;
    }
  }

  // --- 既定値は「何も主張しない」側に倒れている ---
  {
    gridfreq::HeaderFields f;
    checkEq("timebase_source の既定は NOMINAL", f.timebase_source, 0);
    checkEq("f_nominal_mhz の既定は未判別(0)", f.f_nominal_mhz, 0);
  }

  printf("\n%s (%d failure%s)\n", gFailures ? "FAILED" : "PASSED", gFailures,
         gFailures == 1 ? "" : "s");
  return gFailures ? 1 : 0;
}
