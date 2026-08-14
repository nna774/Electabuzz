#pragma once
// NMEA GGAセンテンスを解析し、fix品質を取り出す。→ docs/wire-format.md の `gnss_fix` フラグ
//
// **GGAだけを見る理由。** `wire-format.md`の`gnss_fix`フラグが必要としているのは
// 「測位できていたか」の1ビットだけで、GGAのfix quality(0=no fix)がそのまま使える。
// UBX-NAV-PVT等のバイナリを読みに行く必要はない——u-bloxは既定でNMEA出力を持っており、
// 一番簡単な経路で足りる情報を、わざわざ複雑な経路で取りに行かない。
//
// **UBX-MON-VER(チップの本物確認)はここでは扱わない。** u-centerでの一度きりの
// 確認で足りる作業であり、firmwareに常時実装する理由が無いと判断した
// (→ docs/log/2026-08-12-gnss-pps-wiring-plan.md)。
//
// Arduinoに依存しない。ホストのg++でテストできる。

#include <cstddef>

namespace gnss {

struct GgaFix {
  bool valid = false;  // GGAとして認識でき、チェックサムも一致した
  int fixQuality = 0;  // NMEAのfix quality (0=no fix, 1=GPS, 2=DGPS, 4=RTK fixed, 5=RTK float, 6=推定 等)

  bool hasFix() const { return valid && fixQuality > 0; }
};

// NMEAセンテンス1行(`$`始まり、チェックサム`*XX`まで。末尾の`\r\n`は無くてよい。
// `NmeaLineReader::line()`の出力をそのまま渡せる)を解析する。
// GGAセンテンス(`$??GGA,...`。talker IDはGP/GN/GL/GA/GB/GQ等どれでもよい)かつ
// チェックサムが一致した場合のみ true を返し、out へ書く。
// GGA以外・チェックサム不一致・壊れた入力は false(out.valid=falseのまま)。
bool parseGga(const char* line, size_t len, GgaFix& out);

}  // namespace gnss
