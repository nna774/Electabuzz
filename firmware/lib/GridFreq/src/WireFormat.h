#pragma once
// GFRQ ワイヤ形式 v1 のレイアウト。docs/wire-format.md と一致させること。
// ESP32・Lambda(Python) ともリトルエンディアン前提。

#include <cstddef>
#include <cstdint>

// "GFRQ"。NAMZ と別の magic にするのは fail-fast のためだ。kIngestUrl を誤設定して
// 地震計の ingest へ POST してしまっても、magic が違えば即座に弾かれる。
// 値は Namazu の kWireMagic と同じ流儀で**バイト列を大端読みした数**で書く
// （リトルエンディアンで書き出すので線上のバイト順は 'Q','R','F','G' になる）。
// 両実装が同じ値を使うことだけが要件で、線上で読める向きに並ぶ必要はない。
static constexpr uint32_t kGfrqMagic = 0x47465251;
static constexpr uint8_t kGfrqVersion = 1;
static constexpr size_t kGfrqHeaderSize = 64;

// record_format: レコードの形。増えたらここに足す。ヘッダの header_len と合わせて
// 「読み手が知らない形を知らないと分かる」ようにするための番号。
enum GfrqRecordFormat : uint8_t {
  kGfrqRecordCyclesQ16 = 0,  // 12バイト。cycles_q16 / v_rms_mv / flags
};

// timebase_source: このバッチの時間基準が何だったか。
// **これが無いと「このデータは規正済みか」が後から永久に判別できない。省くな。**
enum GfrqTimebaseSource : uint8_t {
  kGfrqTbNominal = 0,  // 公称値。TE を描いてはいけない
  kGfrqTbNtp = 1,
  kGfrqTbPps = 2,
  kGfrqTbPpsNtp = 3,
};

// バッチ単位のフラグ（ヘッダの flags）。
enum GfrqBatchFlag : uint16_t {
  kGfrqFlagPpsLocked = 1u << 0,       // このバッチの区間で PPS を捕捉できていた
  kGfrqFlagGnssFix = 1u << 1,         // GNSS が測位できていた（PPS の質の傍証）
  kGfrqFlagDiscontinuity = 1u << 2,   // 直前のバッチと累積位相が繋がっていない
  kGfrqFlagPowerFail = 1u << 3,       // 商用電源の断を検出した区間を含む
  kGfrqFlagTbExtrapolated = 1u << 4,  // 時間基準が外挿（holdover）だった
};

// レコード単位のフラグ（レコードの flags）は**まだ1ビットも割り当てていない**。
// 何を品質として立てるかは位相推定の実装が決めることで、それが無い今に決めると
// 「存在しない要件への一般化」になる。フィールドは確保してあるので、DSP 側が
// 立てたいものを持ち込んだ時点でここに定義を足せばよい。

#pragma pack(push, 1)
struct GfrqHeader {
  uint32_t magic;             // 0
  uint8_t version;            // 4
  uint8_t record_format;      // 5
  uint16_t header_len;        // 6  自己記述。知らないフィールドを飛ばせる
  uint64_t batch_start_us;    // 8  先頭レコードのUNIX時刻[us]（UTC、NTP由来）
  uint32_t device_id;         // 16
  uint32_t record_count;      // 20
  uint32_t record_rate_mhz;   // 24 **出力レコード**レート[milli-Hz]。ADCレートではない
  uint32_t session_id;        // 28 起動ごとに単調増加。不連続の識別子
  uint32_t f_nominal_mhz;     // 32 判別結果（50000 / 60000）
  uint64_t fs_measured_uhz;   // 36 実効ADCサンプルレートの推定値[uHz]
  uint32_t tb_obs_count;      // 44 時間基準の観測数（PPSエッジ数 or NTP標本数）
  uint32_t tb_residual_ns;    // 48 時間基準推定の1σ[ns/s]。源に依らない自己申告
  uint16_t flags;             // 52 GfrqBatchFlag
  uint8_t timebase_source;    // 54 GfrqTimebaseSource
  int8_t soc_temp_c;          // 55 事後の fs(T) 補正の材料
  uint32_t reserved;          // 56
  uint32_t crc32;             // 60 レコード列のCRC（ヘッダと tail は含めない）
};

struct GfrqRecord {
  uint64_t cycles_q16;  // セッション開始からの**絶対**累積位相。2^-16 サイクル
  uint16_t v_rms_mv;    // 電圧異常・停電判定用
  uint16_t flags;       // レコード単位の品質フラグ（割り当ては未定。上記）
};
#pragma pack(pop)

static_assert(sizeof(GfrqHeader) == kGfrqHeaderSize, "GfrqHeader must be 64 bytes");
static_assert(sizeof(GfrqRecord) == 12, "GfrqRecord must be 12 bytes");

// 仕様書が offset で書いている以上、構造体の宣言順に頼らず offset で固定する。
static_assert(offsetof(GfrqHeader, header_len) == 6, "header_len offset");
static_assert(offsetof(GfrqHeader, batch_start_us) == 8, "batch_start_us offset");
static_assert(offsetof(GfrqHeader, record_count) == 20, "record_count offset");
static_assert(offsetof(GfrqHeader, fs_measured_uhz) == 36, "fs_measured_uhz offset");
static_assert(offsetof(GfrqHeader, timebase_source) == 54, "timebase_source offset");
static_assert(offsetof(GfrqHeader, crc32) == 60, "crc32 offset");
