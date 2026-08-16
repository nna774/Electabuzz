"""GFRQ v1 のパース。docs/wire-format.md / firmware WireFormat.h と一致させること。

Namazu の `lambda/common/wire.py` とは**別実装**である（コードは共有しない）。
動いている地震計のパース経路に手を入れないための判断で、64バイトの固定ヘッダと
12バイトの固定レコードという単純な形式なら二重実装の費用は小さい。
→ docs/batch-uplink.md

**依存は stdlib だけ。** 1バッチ30レコードに numpy を持ち出す理由が無く、
持ち込まなければ ingest Lambda の zip に platform wheel の面倒が入らない。
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from enum import IntEnum, IntFlag

MAGIC = 0x47465251  # "GFRQ" を大端読みした値。線上のバイト順は 'Q','R','F','G'
NAMZ_MAGIC = 0x4E414D5A  # 地震計。誤送信を名指しで弾くためだけに知っている
VERSION = 1

HEADER_FMT = "<IBBHQIIIIIQIIHBbII"
HEADER_SIZE = struct.calcsize(HEADER_FMT)
RECORD_FMT = "<QHH"
RECORD_SIZE = struct.calcsize(RECORD_FMT)

assert HEADER_SIZE == 64, HEADER_SIZE
assert RECORD_SIZE == 12, RECORD_SIZE

RECORD_FORMAT_CYCLES_Q16 = 0
CYCLES_Q16_SCALE = 1 << 16  # 累積位相の固定小数点。2^-16 サイクル刻み


class WireFormatError(ValueError):
    """GFRQ として読めない。"""


class CrcMismatch(WireFormatError):
    """レコード列の CRC が合わない。

    形式は合っているのに中身が壊れている、という他と別の事故なので型を分ける。
    呼び出し側が「隔離して次へ進む」判断をできるようにするためだ。
    """


class TimebaseSource(IntEnum):
    """このバッチの時間基準が何だったか。→ docs/timebase.md"""

    NOMINAL = 0  # 公称値。TE を描いてはいけない
    NTP = 1
    PPS = 2
    PPS_NTP = 3


class BatchFlag(IntFlag):
    PPS_LOCKED = 1 << 0
    GNSS_FIX = 1 << 1
    DISCONTINUITY = 1 << 2
    POWER_FAIL = 1 << 3
    TB_EXTRAPOLATED = 1 << 4


@dataclass(frozen=True)
class Header:
    version: int
    record_format: int
    header_len: int
    batch_start_us: int
    device_id: int
    record_count: int
    record_rate_mhz: int
    session_id: int
    f_nominal_mhz: int
    fs_measured_uhz: int
    tb_obs_count: int
    tb_residual_ns: int
    flags: int
    timebase_source: int
    soc_temp_c: int
    crc32: int

    @property
    def batch_flags(self) -> BatchFlag:
        """既知のビットだけを IntFlag として返す（未知ビットは flags に生で残る）。"""
        known = 0
        for f in BatchFlag:
            known |= int(f)
        return BatchFlag(self.flags & known)

    @property
    def source_name(self) -> str:
        try:
            return TimebaseSource(self.timebase_source).name
        except ValueError:
            return f"UNKNOWN({self.timebase_source})"

    @property
    def is_disciplined(self) -> bool:
        """時間基準が規正されていたか。**知らない源は False にする。**

        古いパーサが新しい源（未知の番号）のデータを読んだとき、「規正済みだ」と
        名乗る方に倒れると、設計書の一線（測れなかった区間を測れたように見せない）が
        パーサ側から破れる。分からないなら主張しない。
        """
        return self.timebase_source in (
            TimebaseSource.NTP,
            TimebaseSource.PPS,
            TimebaseSource.PPS_NTP,
        )

    @property
    def is_pps_disciplined(self) -> bool:
        """PPS由来の規正か(NTP単独は含まない)。

        TE絶対値表示のアンカー(→ docs/cloud.md「TE絶対値表示のアンカー」)はv1では
        PPS限定にする——NTPロック(600秒)よりPPSロック(30秒)の方が実運用では
        先に来ることが多く、NTP限定の状態が長く続かない見込みが高いため
        (→ docs/log/2026-08-17-te-absolute-display-design.md)。
        """
        return self.timebase_source in (TimebaseSource.PPS, TimebaseSource.PPS_NTP)

    @property
    def f_nominal_hz(self) -> float:
        return self.f_nominal_mhz / 1000.0

    @property
    def fs_measured_hz(self) -> float:
        """実効ADCサンプルレートの推定値[Hz]。**公称値ではない。**"""
        return self.fs_measured_uhz / 1e6


@dataclass(frozen=True)
class Record:
    cycles_q16: int
    v_rms_mv: int
    flags: int

    @property
    def cycles(self) -> float:
        """セッション開始からの絶対累積位相[サイクル]。"""
        return self.cycles_q16 / CYCLES_Q16_SCALE


@dataclass(frozen=True)
class Batch:
    header: Header
    records: tuple[Record, ...]

    def timestamps_us(self) -> list[int]:
        """各レコードの UNIX時刻[us]。

        式は NAMZ v1 と同じ `batch_start_us + i × 1e6/rate`
        （wire.py:37-40 の踏襲）。**rate は出力レコードレートであって
        ADC のサンプルレートではない。** 後者は fs_measured_uhz にある。

        整数で計算するのは、同じ入力から必ず同じ値が出るようにするためだ
        （浮動小数の丸めが処理系で揺れると、S3 キーや突き合わせが揺れる）。
        """
        rate = self.header.record_rate_mhz
        if rate <= 0:
            raise WireFormatError(f"bad record_rate_mhz {rate}")
        start = self.header.batch_start_us
        return [start + (i * 10**9 + rate // 2) // rate for i in range(len(self.records))]

    def te_seconds(self) -> list[float]:
        """系統時刻偏差の**バッチ内の相対変化**[秒]。

        絶対の TE はセッションを跨いだ基準が要るので、ここでは出さない
        （cycles は「セッション開始からの絶対値」であって「標準時からのずれ」ではない）。
        提示してよいかは header.timebase_source が決める。→ docs/timebase.md

        **バッチ内に閉じているのでうるう秒の1秒ジャンプを踏まない。** 時刻は
        batch_start_us からの式で作っており、区間の途中で UTC を読み直さないからだ。
        危ないのはバッチを跨いで繋ぐ側であって、そちらは連続時系で扱うこと。
        """
        f_nom = self.header.f_nominal_hz
        if f_nom <= 0:
            raise WireFormatError(f"bad f_nominal_mhz {self.header.f_nominal_mhz}")
        ts = self.timestamps_us()
        c0, t0 = self.records[0].cycles, ts[0]
        return [
            (r.cycles - c0) / f_nom - (t - t0) / 1e6
            for r, t in zip(self.records, ts)
        ]


def parse(data: bytes) -> Batch:
    if len(data) < HEADER_SIZE:
        raise WireFormatError(f"too short for header: {len(data)}")

    (magic, version, record_format, header_len, batch_start_us, device_id,
     record_count, record_rate_mhz, session_id, f_nominal_mhz, fs_measured_uhz,
     tb_obs_count, tb_residual_ns, flags, timebase_source, soc_temp_c,
     _reserved, crc) = struct.unpack(HEADER_FMT, data[:HEADER_SIZE])

    if magic != MAGIC:
        # 独自 magic にしてある目的がこれだ。kIngestUrl の誤設定で地震計のバッチが
        # 流れてきても、意味不明なデータとして raw/ に混入する前に名指しで落ちる。
        if magic == NAMZ_MAGIC:
            raise WireFormatError(
                "NAMZ batch (地震計) が GFRQ の ingest に届いている: "
                "デバイスの kIngestUrl 誤設定を疑え")
        raise WireFormatError(f"bad magic {magic:#010x}")
    if version != VERSION:
        raise WireFormatError(f"unsupported version {version}")
    if record_format != RECORD_FORMAT_CYCLES_Q16:
        raise WireFormatError(f"unknown record_format {record_format}")
    if header_len < HEADER_SIZE:
        raise WireFormatError(f"header_len {header_len} < {HEADER_SIZE}")

    header = Header(
        version=version, record_format=record_format, header_len=header_len,
        batch_start_us=batch_start_us, device_id=device_id,
        record_count=record_count, record_rate_mhz=record_rate_mhz,
        session_id=session_id, f_nominal_mhz=f_nominal_mhz,
        fs_measured_uhz=fs_measured_uhz, tb_obs_count=tb_obs_count,
        tb_residual_ns=tb_residual_ns, flags=flags,
        timebase_source=timebase_source, soc_temp_c=soc_temp_c, crc32=crc,
    )

    # header_len を信じてレコード列の頭を決める。これが自己記述にしてある意味で、
    # 知らないフィールドがヘッダ末尾に足されても**このパーサは壊れない**。
    need = record_count * RECORD_SIZE
    end = header_len + need
    if len(data) < end:
        raise WireFormatError(f"payload short: {len(data)} < {end}")
    if len(data) > end:
        # GFRQ v1 に tail は無い。余りがあるのは連結・切り詰め等の事故なので、
        # 黙って読み飛ばさない（tail を使う版を作るなら version を上げる）。
        raise WireFormatError(f"unexpected trailing {len(data) - end} bytes")

    payload = data[header_len:end]
    actual = zlib.crc32(payload)
    if actual != crc:
        raise CrcMismatch(f"crc32 mismatch: header {crc:#010x}, actual {actual:#010x}")

    records = tuple(
        Record(*struct.unpack_from(RECORD_FMT, payload, i * RECORD_SIZE))
        for i in range(record_count)
    )
    return Batch(header=header, records=records)
