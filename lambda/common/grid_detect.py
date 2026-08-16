"""周波数逸脱・RoCoF・電圧異常の確定判定(→ docs/cloud.md「detect」)。

Namazuのdetect(地震の震度をFFT窓で再計算する)とは判定の性質が違う。GFRQは
既に1Hzで瞬時周波数の元になる累積位相を運んでいるので、窓を再解析する必要が
無く、レコード単位のしきい値判定で足りる。

副作用の無い純粋関数に判定ロジックを集約する（`lambda/common/power_fail_watch.py`
と同じ設計。DynamoDB・Slackに触らずテストできる）。
"""

from __future__ import annotations

from dataclasses import dataclass

import wire_gridfreq

# 周波数逸脱・電圧異常の連続run検出をレコード単位(≒秒)で行う。
FreqDeviation = "freq_deviation"
RoCoF = "rocof"
VoltageAnomaly = "voltage_anomaly"


@dataclass(frozen=True)
class Sample:
    """1レコードぶんの、判定に必要な量だけを持つ軽量な形。"""

    t_us: int
    freq_hz: float | None  # 隣接レコードとの差分から求めた瞬時周波数。計算不能ならNone
    v_rms_mv: int
    power_fail: bool  # このレコードが属するバッチのpower_failフラグ(バッチ単位)


@dataclass(frozen=True)
class Detection:
    event_type: str  # FreqDeviation / RoCoF / VoltageAnomaly
    onset_us: int
    last_us: int
    peak_value: float
    """freq_deviation: |f-f_nom|のピーク[Hz] / rocof: |df/dt|のピーク[Hz/s] /
    voltage_anomaly: |v-v_nom|/v_nomのピーク(比率)"""


def samples_from_batches(batches: list[wire_gridfreq.Batch]) -> list[Sample]:
    """`batch_start_us`順に並んだバッチ列からSample列を作る。

    周波数の求め方は`lambda/api/handler.py`の`_series_payload`と同じ規則
    （理論値`nominal_dt`を分母に使う・DISCONTINUITYを立てたバッチ内では計算しない・
    session_idが変わったら前の点を引き継がない）。**測れなかった区間を測れたように
    見せない**という設計原則(→ docs/timebase.md)を破らないため、api側の実装済み・
    実機確認済みのロジックをそのまま複製している——detectとapiを同時に一般化して
    共通化はしない(→ CLAUDE.md「切り出しと一般化を同時にやるな」と同じ理由。
    まずは動いているapi側に手を入れず、判定ロジックだけ別に持つ)。
    """
    samples: list[Sample] = []
    prev_session = None
    prev_t = None
    prev_cycles = None

    for b in batches:
        h = b.header
        suspect = bool(h.batch_flags & wire_gridfreq.BatchFlag.DISCONTINUITY)
        power_fail = bool(h.batch_flags & wire_gridfreq.BatchFlag.POWER_FAIL)
        nominal_dt = 1000.0 / h.record_rate_mhz if h.record_rate_mhz > 0 else None

        for t, r in zip(b.timestamps_us(), b.records):
            f = None
            if (not suspect and nominal_dt and prev_t is not None
                    and prev_session == h.session_id):
                dt_actual = (t - prev_t) / 1e6
                if 0.5 * nominal_dt <= dt_actual <= 2.0 * nominal_dt:
                    f = (r.cycles - prev_cycles) / nominal_dt

            samples.append(Sample(t_us=t, freq_hz=f, v_rms_mv=r.v_rms_mv, power_fail=power_fail))

            if not suspect:
                prev_session, prev_t, prev_cycles = h.session_id, t, r.cycles
            else:
                prev_session, prev_t, prev_cycles = None, None, None

    return samples


def _runs(flags: list[bool]) -> list[tuple[int, int]]:
    """Trueが連続する半開区間[start, end)を列挙する。"""
    runs = []
    start = None
    for i, f in enumerate(flags):
        if f and start is None:
            start = i
        elif not f and start is not None:
            runs.append((start, i))
            start = None
    if start is not None:
        runs.append((start, len(flags)))
    return runs


def analyze(
    samples: list[Sample],
    *,
    f_nominal_hz: float,
    freq_dev_threshold_hz: float,
    freq_dev_hold_records: int,
    voltage_dev_fraction: float,
    voltage_dev_hold_records: int,
    nominal_v_rms_mv: float,
    rocof_threshold_hz_per_s: float,
) -> list[Detection]:
    """しきい値判定。`samples`は時系列順(1つの`analyze()`呼び出しは1デバイスぶん)。

    周波数逸脱・電圧異常は「しきい値を跨いだ連続run」がhold件数以上続いたときだけ
    確定する(単発のノイズで騒がないため)。RoCoFはそれ自体が変化率の測定なので、
    単発の跨ぎをそのまま検知として扱う(→ docs/cloud.md「新規 detect_gridfreq」)。

    電圧異常はpower_fail中(AC入力断、→ watchdogが別途通知)は評価しない——
    入力が無い時の電圧はほぼ0Vで、「異常な低電圧」として二重に騒ぐ理由が無い。
    """
    detections: list[Detection] = []

    # f_nominal_hz<=0は「未判別」(→ docs/wire-format.md)。基準が無いのに逸脱は
    # 判定できないので、このバッチでは周波数逸脱の判定を丸ごとスキップする
    # (RoCoF・電圧異常はf_nominalに依存しないので影響しない)。
    if f_nominal_hz > 0:
        freq_breach = [
            s.freq_hz is not None and abs(s.freq_hz - f_nominal_hz) > freq_dev_threshold_hz
            for s in samples
        ]
        for start, end in _runs(freq_breach):
            if end - start < freq_dev_hold_records:
                continue
            peak = max(abs(samples[i].freq_hz - f_nominal_hz) for i in range(start, end))
            detections.append(Detection(FreqDeviation, samples[start].t_us, samples[end - 1].t_us, peak))

    if nominal_v_rms_mv > 0:
        volt_breach = [
            (not s.power_fail)
            and abs(s.v_rms_mv - nominal_v_rms_mv) / nominal_v_rms_mv > voltage_dev_fraction
            for s in samples
        ]
        for start, end in _runs(volt_breach):
            if end - start < voltage_dev_hold_records:
                continue
            peak = max(
                abs(samples[i].v_rms_mv - nominal_v_rms_mv) / nominal_v_rms_mv
                for i in range(start, end)
            )
            detections.append(Detection(VoltageAnomaly, samples[start].t_us, samples[end - 1].t_us, peak))

    for prev, cur in zip(samples, samples[1:]):
        if prev.freq_hz is None or cur.freq_hz is None:
            continue
        dt_s = (cur.t_us - prev.t_us) / 1e6
        if dt_s <= 0:
            continue
        rocof = (cur.freq_hz - prev.freq_hz) / dt_s
        if abs(rocof) > rocof_threshold_hz_per_s:
            detections.append(Detection(RoCoF, prev.t_us, cur.t_us, abs(rocof)))

    return detections
