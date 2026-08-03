#pragma once
// 時間基準の推定器インタフェース。→ docs/timebase.md
//
// この設計の核心は「fs を定数として持たず、測って報告する量にする」ことだ。
// 実装は NOMINAL / NTP / PPS の3種で、どれも同じ4つを答えられる。
// **確度の自己申告 (residualNs) を必ず持たせる**のがこのインタフェースの要点で、
// 「自分の測定がどこまで正しいかを示せない測定器は、測定器ではない」。

#include <cstdint>

namespace timebase {

// GFRQ ヘッダの timebase_source と同じ値でなければならない。
// （firmware/lib/GridFreq/src/WireFormat.h の GfrqTimebaseSource）
enum class Source : uint8_t {
  kNominal = 0,  // 公称値。規正されていない
  kNtp = 1,
  kPps = 2,
  kPpsNtp = 3,
};

class TimebaseEstimator {
 public:
  virtual ~TimebaseEstimator() = default;

  // ティック源の実効レート [µHz]。ティックが I2S のサンプルなら fs そのもの。
  virtual uint64_t fsMicroHz() const = 0;

  // レート推定の 1σ を「1秒あたり何 ns の時刻偏差になるか」で表したもの [ns/s]。
  // ダッシュボードはこれ×経過時間を不確かさ帯として描く。
  virtual uint32_t residualNs() const = 0;

  // 推定に使った観測数。
  virtual uint32_t obsCount() const = 0;

  // **規正できていないなら kNominal を返すこと。** ここが嘘をつくと
  // 「測れなかった区間を測れたように見せない」の一線がファームウェア側から破れる。
  virtual Source source() const = 0;
};

}  // namespace timebase
