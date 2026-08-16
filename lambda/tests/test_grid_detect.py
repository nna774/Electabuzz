"""grid_detect.analyze / samples_from_batches の純粋関数テスト（DynamoDB・Slackに触れない）。"""

import pytest

from common import grid_detect as gd
from wire_gridfreq import CYCLES_Q16_SCALE, Batch, BatchFlag, Header, Record


def _header(*, batch_start_us=0, session_id=1, record_count=3, flags=0, device_id=1):
    return Header(
        version=1, record_format=0, header_len=64, batch_start_us=batch_start_us,
        device_id=device_id, record_count=record_count, record_rate_mhz=1000,
        session_id=session_id, f_nominal_mhz=50_000, fs_measured_uhz=48_000_000_000,
        tb_obs_count=0, tb_residual_ns=0, flags=flags, timebase_source=2,
        soc_temp_c=25, crc32=0,
    )


def _batch(*, start_us, freqs_hz, session_id=1, flags=0, v_rms_mv=10_500):
    """cycles_q16をfreqs_hzから逆算して1秒刻みのバッチを作る(先頭の絶対値は0起点)。"""
    records = []
    cycles = 0.0
    for f in freqs_hz:
        cycles += f  # 1秒刻みなのでΔcycles = f
        records.append(Record(cycles_q16=int(round(cycles * CYCLES_Q16_SCALE)),
                               v_rms_mv=v_rms_mv, flags=0))
    h = _header(batch_start_us=start_us, session_id=session_id, record_count=len(records), flags=flags)
    return Batch(header=h, records=tuple(records))


# --- samples_from_batches ---

def test_freq_hz_recovered_from_cycles():
    b = _batch(start_us=0, freqs_hz=[50.0, 50.0, 50.02])
    samples = gd.samples_from_batches([b])
    assert samples[0].freq_hz is None  # 直前の点が無い最初のレコード
    assert samples[1].freq_hz == pytest.approx(50.0)
    assert samples[2].freq_hz == pytest.approx(50.02)


def test_discontinuity_batch_suppresses_freq_and_next_batch_first_record():
    b1 = _batch(start_us=0, freqs_hz=[50.0, 50.0], flags=int(BatchFlag.DISCONTINUITY))
    b2 = _batch(start_us=2_000_000, freqs_hz=[50.0, 50.0])
    samples = gd.samples_from_batches([b1, b2])
    assert all(s.freq_hz is None for s in samples[:2])  # discontinuityバッチ内は全てNone
    assert samples[2].freq_hz is None  # 次バッチの先頭も、直前の点を引き継げないのでNone
    assert samples[3].freq_hz is not None  # b2内部同士は普通に計算できる


def test_session_change_breaks_continuity():
    b1 = _batch(start_us=0, freqs_hz=[50.0, 50.0], session_id=1)
    b2 = _batch(start_us=2_000_000, freqs_hz=[50.0, 50.0], session_id=2)
    samples = gd.samples_from_batches([b1, b2])
    assert samples[2].freq_hz is None  # 再起動でセッションが変わった直後


def test_power_fail_flag_carried_per_record():
    b = _batch(start_us=0, freqs_hz=[50.0, 50.0], flags=int(BatchFlag.POWER_FAIL))
    samples = gd.samples_from_batches([b])
    assert all(s.power_fail for s in samples)


# --- analyze: 周波数逸脱 ---

THRESH = dict(
    f_nominal_hz=50.0, freq_dev_threshold_hz=0.1, freq_dev_hold_records=3,
    voltage_dev_fraction=0.1, voltage_dev_hold_records=3, nominal_v_rms_mv=10_500.0,
    rocof_threshold_hz_per_s=0.2,
)


def _samples(freqs, *, v=10_500, power_fail=False, start_us=0):
    return [gd.Sample(t_us=start_us + i * 1_000_000, freq_hz=f, v_rms_mv=v, power_fail=power_fail)
            for i, f in enumerate(freqs)]


def test_freq_deviation_detected_when_run_reaches_hold():
    samples = _samples([50.0, 50.2, 50.25, 50.3, 50.0])  # 3件連続で閾値(0.1Hz)超過
    dets = gd.analyze(samples, **THRESH)
    freq_dets = [d for d in dets if d.event_type == gd.FreqDeviation]
    assert len(freq_dets) == 1
    d = freq_dets[0]
    assert d.onset_us == 1_000_000 and d.last_us == 3_000_000
    assert d.peak_value == pytest.approx(0.3)


def test_freq_deviation_ignored_when_run_shorter_than_hold():
    samples = _samples([50.0, 50.2, 50.25, 50.0, 50.0])  # 2件だけ
    dets = gd.analyze(samples, **THRESH)
    assert not [d for d in dets if d.event_type == gd.FreqDeviation]


def test_freq_deviation_ignores_none_samples():
    samples = _samples([50.0, None, None, None, 50.0])
    dets = gd.analyze(samples, **THRESH)
    assert not [d for d in dets if d.event_type == gd.FreqDeviation]


def test_freq_deviation_skipped_when_nominal_undetermined():
    # f_nominal_mhz=0(未判別)。基準が無い以上、判定してはいけない
    # (→ docs/wire-format.md「測っていない値がもっともらしく記録されるのが最悪」)。
    samples = _samples([50.0, 52.0, 52.0, 52.0, 50.0])
    dets = gd.analyze(samples, **{**THRESH, "f_nominal_hz": 0.0})
    assert not [d for d in dets if d.event_type == gd.FreqDeviation]
    # RoCoF・電圧異常はf_nominalと無関係なので判定は継続する
    assert [d for d in dets if d.event_type == gd.RoCoF]


# --- analyze: RoCoF ---

def test_rocof_detected_on_large_jump():
    samples = _samples([50.0, 50.5])  # 1秒で0.5Hz変化 > 閾値0.2Hz/s
    dets = gd.analyze(samples, **THRESH)
    rocof_dets = [d for d in dets if d.event_type == gd.RoCoF]
    assert len(rocof_dets) == 1
    assert rocof_dets[0].peak_value == pytest.approx(0.5)


def test_rocof_not_detected_under_threshold():
    samples = _samples([50.0, 50.1])  # 0.1Hz/s < 0.2Hz/s
    dets = gd.analyze(samples, **THRESH)
    assert not [d for d in dets if d.event_type == gd.RoCoF]


def test_rocof_skips_none_pairs():
    samples = _samples([50.0, None])
    dets = gd.analyze(samples, **THRESH)
    assert not [d for d in dets if d.event_type == gd.RoCoF]


# --- analyze: 電圧異常 ---

def test_voltage_anomaly_detected():
    samples = _samples([50.0] * 5, v=12_000)  # 10500 -> 12000 は+14.3%、閾値10%超
    dets = gd.analyze(samples, **THRESH)
    v_dets = [d for d in dets if d.event_type == gd.VoltageAnomaly]
    assert len(v_dets) == 1
    assert v_dets[0].peak_value == pytest.approx((12_000 - 10_500) / 10_500)


def test_voltage_anomaly_suppressed_during_power_fail():
    samples = _samples([50.0] * 5, v=12_000, power_fail=True)
    dets = gd.analyze(samples, **THRESH)
    assert not [d for d in dets if d.event_type == gd.VoltageAnomaly]
