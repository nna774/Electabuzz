import struct
import zlib

import pytest
from conftest import GOLDEN_PATH, load_hex

import wire_gridfreq as wire


def build(records=None, *, magic=wire.MAGIC, version=1, record_format=0,
          header_len=64, start_us=1_750_000_000_123_456, device_id=1,
          record_count=None, rate_mhz=1000, session_id=1, f_nominal_mhz=50_000,
          fs_uhz=48_000_000_000, tb_obs=0, tb_res=0, flags=0, source=0, temp=25,
          crc=None, pad=b"", trailing=b""):
    """firmware の GridFreqWire と同じバイト列を作る。

    壊れた入力を作れることが眼目なので、全フィールドを差し替えられるようにしてある。
    """
    if records is None:
        records = [(0, 10_500, 0), (3_276_800, 10_500, 0)]
    payload = b"".join(struct.pack(wire.RECORD_FMT, *r) for r in records)
    header = struct.pack(
        wire.HEADER_FMT, magic, version, record_format, header_len, start_us,
        device_id, len(records) if record_count is None else record_count,
        rate_mhz, session_id, f_nominal_mhz, fs_uhz, tb_obs, tb_res, flags,
        source, temp, 0, zlib.crc32(payload) if crc is None else crc)
    return header + pad + payload + trailing


# --- ゴールデンフィクスチャ ---
# firmware 側が「このパラメータからこのバイト列が出る」ことを主張し、
# こちらは「そのバイト列を仕様どおりに読める」ことを主張する。
# 往復して初めて契約が閉じる。→ docs/wire-format.md

def test_golden_header():
    b = wire.parse(load_hex(GOLDEN_PATH))
    h = b.header
    assert h.version == 1
    assert h.record_format == 0
    assert h.header_len == 64
    assert h.batch_start_us == 1_750_000_000_123_456
    assert h.device_id == 2
    assert h.record_count == 30
    assert h.record_rate_mhz == 1000
    assert h.session_id == 7
    assert h.f_nominal_mhz == 50_000
    assert h.fs_measured_uhz == 47_998_123_456
    assert h.tb_obs_count == 3600
    assert h.tb_residual_ns == 120
    assert h.timebase_source == wire.TimebaseSource.PPS
    assert h.soc_temp_c == 41
    assert h.crc32 == 0xE849A2B8
    assert h.batch_flags == (wire.BatchFlag.PPS_LOCKED | wire.BatchFlag.GNSS_FIX)


def test_golden_records():
    b = wire.parse(load_hex(GOLDEN_PATH))
    assert len(b.records) == 30
    assert all(r.v_rms_mv == 10_500 and r.flags == 0 for r in b.records)
    # 公称50Hzちょうど = 1秒あたり 50 × 65536
    assert [r.cycles_q16 for r in b.records] == [3_276_800 * i for i in range(30)]
    assert b.records[1].cycles == 50.0


def test_golden_derived():
    b = wire.parse(load_hex(GOLDEN_PATH))
    ts = b.timestamps_us()
    assert ts[0] == 1_750_000_000_123_456
    assert ts[1] - ts[0] == 1_000_000  # 1Hz
    assert len(ts) == 30
    assert b.header.fs_measured_hz == pytest.approx(47_998.123456)
    assert b.header.f_nominal_hz == 50.0
    # ちょうど公称周波数で刻んでいるので TE は動かない
    assert b.te_seconds() == pytest.approx([0.0] * 30, abs=1e-12)


def test_te_follows_frequency_deviation():
    # 1秒あたり 50.01 サイクル進む = +10mHz。TE は毎秒 0.2ms ずつ増える。
    #
    # 許容は形式の分解能そのもの（2^-16 サイクル = 50Hz で 0.31µs）。
    # これより細かく合わせろと要求しても、レコードにその情報が入っていない。
    quantum_s = 1 / wire.CYCLES_Q16_SCALE / 50
    recs = [(round(50.01 * i * wire.CYCLES_Q16_SCALE), 10_500, 0) for i in range(4)]
    b = wire.parse(build(records=recs))
    assert b.te_seconds() == pytest.approx([0.0, 2e-4, 4e-4, 6e-4], abs=quantum_s)


# --- 弾くべきものを弾く ---

def test_rejects_namz_batch_by_name():
    # 独自 magic にしてある目的そのもの。誤送信は名指しで落ちる。
    with pytest.raises(wire.WireFormatError, match="地震計"):
        wire.parse(build(magic=wire.NAMZ_MAGIC))


def test_rejects_bad_magic():
    with pytest.raises(wire.WireFormatError, match="bad magic"):
        wire.parse(build(magic=0xDEADBEEF))


def test_rejects_unknown_version_and_format():
    with pytest.raises(wire.WireFormatError, match="version"):
        wire.parse(build(version=2))
    with pytest.raises(wire.WireFormatError, match="record_format"):
        wire.parse(build(record_format=1))


def test_rejects_short_input():
    with pytest.raises(wire.WireFormatError, match="too short"):
        wire.parse(build()[:32])
    with pytest.raises(wire.WireFormatError, match="payload short"):
        wire.parse(build()[:-1])


def test_rejects_trailing_bytes():
    # GFRQ v1 に tail は無い。余りは連結・切り詰めの事故なので黙って読み飛ばさない。
    with pytest.raises(wire.WireFormatError, match="trailing"):
        wire.parse(build(trailing=b"\x00"))


def test_rejects_header_len_below_spec():
    with pytest.raises(wire.WireFormatError, match="header_len"):
        wire.parse(build(header_len=32))


def test_crc_mismatch_is_its_own_type():
    # 形式は合っているのに中身が壊れている、は別の事故。隔離できるよう型を分ける。
    with pytest.raises(wire.CrcMismatch):
        wire.parse(build(crc=0x00000000))
    assert issubclass(wire.CrcMismatch, wire.WireFormatError)


def test_record_count_larger_than_payload():
    with pytest.raises(wire.WireFormatError, match="payload short"):
        wire.parse(build(record_count=99))


# --- 前方互換 ---

def test_longer_header_is_skipped_not_broken():
    """header_len を自己記述にしてある意味はこれだ。

    ヘッダ末尾にフィールドが増えた版のデータを、このパーサが**壊れずに**読める
    （version が上がれば弾くが、レイアウトの拡張それ自体では壊れない）。
    """
    data = build(header_len=80, pad=b"\xAB" * 16)
    b = wire.parse(data)
    assert b.header.header_len == 80
    assert len(b.records) == 2
    assert b.records[1].cycles_q16 == 3_276_800


def test_unknown_flag_bits_are_preserved_not_lost():
    b = wire.parse(build(flags=0x8001))
    assert b.header.flags == 0x8001                      # 生値は保つ
    assert b.header.batch_flags == wire.BatchFlag.PPS_LOCKED  # 既知ビットだけ解釈


# --- 時間基準の主張 ---

def test_unknown_timebase_source_does_not_claim_disciplined():
    """知らない源を「規正済み」と名乗ってはいけない。

    古いパーサが新しい源のデータを読んだとき、ここが True に倒れると
    「測れなかった区間を測れたように見せない」という一線がパーサ側から破れる。
    """
    b = wire.parse(build(source=9))
    assert b.header.is_disciplined is False
    assert b.header.source_name == "UNKNOWN(9)"


@pytest.mark.parametrize("source,disciplined", [
    (wire.TimebaseSource.NOMINAL, False),
    (wire.TimebaseSource.NTP, True),
    (wire.TimebaseSource.PPS, True),
    (wire.TimebaseSource.PPS_NTP, True),
])
def test_is_disciplined(source, disciplined):
    b = wire.parse(build(source=int(source)))
    assert b.header.is_disciplined is disciplined
    assert b.header.source_name == source.name


def test_negative_soc_temp():
    b = wire.parse(build(temp=-5))
    assert b.header.soc_temp_c == -5
