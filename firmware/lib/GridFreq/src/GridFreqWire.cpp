#include "GridFreqWire.h"

#include <cstring>

namespace gridfreq {

Batch* newBatch() {
  return new Batch(kRecordsPerBatch, sizeof(GfrqRecord), kGfrqHeaderSize,
                   /*tailCapacity=*/0);
}

bool addRecord(Batch& b, uint64_t cyclesQ16, uint16_t vRmsMv, uint16_t flags) {
  GfrqRecord r{};
  r.cycles_q16 = cyclesQ16;
  r.v_rms_mv = vRmsMv;
  r.flags = flags;
  return b.addRecord(&r, sizeof(r));
}

uint32_t crc32(const void* data, size_t len) {
  const uint8_t* p = static_cast<const uint8_t*>(data);
  uint32_t c = 0xFFFFFFFFu;
  for (size_t i = 0; i < len; ++i) {
    c ^= p[i];
    for (int k = 0; k < 8; ++k) {
      // 分岐を書かないのは速度のためではなく、条件の取り違えを目視で潰せるから。
      c = (c >> 1) ^ (0xEDB88320u & (0u - (c & 1u)));
    }
  }
  return c ^ 0xFFFFFFFFu;
}

void fillHeader(Batch& b, const HeaderFields& f) {
  GfrqHeader h{};
  h.magic = kGfrqMagic;
  h.version = kGfrqVersion;
  h.record_format = kGfrqRecordCyclesQ16;
  h.header_len = kGfrqHeaderSize;
  h.batch_start_us = b.startUs();
  h.device_id = f.device_id;
  h.record_count = b.recordCount();
  h.record_rate_mhz = kRecordRateMilliHz;
  h.session_id = f.session_id;
  h.f_nominal_mhz = f.f_nominal_mhz;
  h.fs_measured_uhz = f.fs_measured_uhz;
  h.tb_obs_count = f.tb_obs_count;
  h.tb_residual_ns = f.tb_residual_ns;
  h.flags = f.flags;
  h.timebase_source = f.timebase_source;
  h.soc_temp_c = f.soc_temp_c;
  h.reserved = 0;
  // CRC の対象は records() から recordsSize() バイト。ヘッダは自分を含めようがなく、
  // tail は GFRQ v1 では存在しない。将来 tail を使うことにしたら、
  // **範囲を広げるのではなく別フィールドを足すこと**（既存データの検証が壊れる）。
  h.crc32 = crc32(b.records(), b.recordsSize());
  std::memcpy(b.headerPtr(), &h, sizeof(h));
}

}  // namespace gridfreq
