#pragma once
// GFRQ ワイヤ形式を Batch に載せる薄い層。Namazu の lib/NamzWire と同じ役回り。
//
// Batch（batch-uplink v1.0.0）はレイアウトを知らない汎用バッファなので、
// 「64バイトヘッダの中身」「12バイトレコードの並び」「crc32 の対象範囲」は
// こちら側の責務になる。形式そのものの定義は WireFormat.h、
// 仕様と判断理由は docs/wire-format.md にある。
//
// この層は Arduino に依存しない。ホストの g++ で test/run.sh が走る。

#include <cstddef>
#include <cstdint>

#include "Batch.h"
#include "WireFormat.h"

namespace gridfreq {

// 30秒バッチ = 1Hz のレコード30件。tail は持たない（header_len の自己記述で
// 拡張路は確保済みなので、使う当てのない尻尾を今から予約しない）。
static constexpr uint32_t kRecordsPerBatch = 30;
static constexpr uint32_t kRecordRateMilliHz = 1000;  // 出力レコードレート 1Hz

// このプロジェクト用に寸法を与えた Batch を作る。所有権は呼び出し側。
Batch* newBatch();

// 1秒ぶんのレコードを1件積む。
// cyclesQ16 は**絶対**累積位相（差分ではない）。欠測しても復元できるようにするため。
bool addRecord(Batch& b, uint64_t cyclesQ16, uint16_t vRmsMv, uint16_t flags);

// ヘッダのうち、呼び出し側にしか分からない値。
// Batch から出る値（batch_start_us / record_count / crc32）と、形式が決めている定数
// （magic / version / record_format / header_len / record_rate_mhz）はここに無い。
// 「二重に持てるもの」を持たせないことで、食い違いようがなくしてある。
struct HeaderFields {
  uint32_t device_id = 0;
  uint32_t session_id = 0;
  // 判別結果を必ず入れること。既定の 0 は「未判別」として後段が弾ける値であり、
  // 設置先が 50Hz 地域だからといって 50000 を既定にはしない
  // （測っていない値がもっともらしく記録されるのが最悪だ）。
  uint32_t f_nominal_mhz = 0;
  uint64_t fs_measured_uhz = 0;
  uint32_t tb_obs_count = 0;
  uint32_t tb_residual_ns = 0;
  uint16_t flags = 0;                      // GfrqBatchFlag の OR
  uint8_t timebase_source = kGfrqTbNominal;  // 何も主張しない側を既定にする
  int8_t soc_temp_c = 0;
};

// 64バイトヘッダを書く。**レコードを積み終えた後・Uploader へ渡す前**に呼ぶ。
// その時点で recordCount() も records() も確定しているので、record_count も
// crc32 もここで書ける。逆に、積む途中で呼んでも意味のあるヘッダにはならない。
void fillHeader(Batch& b, const HeaderFields& f);

// CRC-32/ISO-HDLC（poly 0xEDB88320、init/final 0xFFFFFFFF）。
// Python 側の zlib.crc32 とバイト等価になる版を選んである。テーブルを持たないのは
// 1バッチ360バイトに対して 8シフト/バイトが無視できるからで、1KBのテーブルを
// フラッシュに置く理由が無い。
uint32_t crc32(const void* data, size_t len);

}  // namespace gridfreq
