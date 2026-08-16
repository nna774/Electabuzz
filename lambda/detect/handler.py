"""detect Lambda: `series/`への新規バッチ到着ごとに、周波数逸脱・RoCoF・電圧異常を
判定してDynamoDBに記録し、新規セッションだけSlack通知する(→ docs/cloud.md「detect」)。

Namazuのdetect(地震の震度をFFT窓で再計算する)とは判定の性質が違う。GFRQは
既に1Hzで瞬時周波数の元になる累積位相を運んでいるので、窓を再解析する必要が
無く、レコード単位のしきい値判定で足りる(→ `lambda/common/grid_detect.py`)。

- S3のObjectCreated(`series/*`)で起動
- 直前バッチの最後の1レコードだけを追加取得し、境界をまたぐ周波数計算の連続性を
  確保する。**それより過去には遡らない**——遡ると、数十秒前に既に確定済みの
  runを毎回再解析してSlackを埋める（`grid_events.record`のセッションマージが
  時間切れ後は「新規」と判断してしまうため）
- しきい値判定そのものは`grid_detect.analyze`(副作用の無い純粋関数)に委ねる
- 新規セッションだけ通知する。継続中の延長は`/events`のlast_usで追える
  （watchdogのような定期再送は持たない——detectはイベント駆動で、継続を
  再送する専用の仕組みを別に持つ理由が薄い）
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import os
from urllib.parse import unquote_plus

import boto3

from batch_uplink import notify

import s3keys
import store_gridfreq
import wire_gridfreq
from common import grid_detect, grid_events

s3 = boto3.client("s3")

FREQ_DEV_THRESHOLD_HZ = float(os.environ.get("ELBZ_FREQ_DEV_THRESHOLD_HZ", "0.1"))
FREQ_DEV_HOLD_RECORDS = int(os.environ.get("ELBZ_FREQ_DEV_HOLD_RECORDS", "3"))
ROCOF_THRESHOLD_HZ_PER_S = float(os.environ.get("ELBZ_ROCOF_THRESHOLD_HZ_PER_S", "0.2"))
VOLTAGE_DEV_FRACTION = float(os.environ.get("ELBZ_VOLTAGE_DEV_FRACTION", "0.1"))
VOLTAGE_DEV_HOLD_RECORDS = int(os.environ.get("ELBZ_VOLTAGE_DEV_HOLD_RECORDS", "3"))
# hardware.mdの実測基準点(トランス二次側、AC100V入力時)を既定にしている。
# AFE換算は1点校正のみの暫定値なので、この閾値も暫定——実測で校正すること。
NOMINAL_V_RMS_MV = float(os.environ.get("ELBZ_NOMINAL_V_RMS_MV", "10300"))

JST = dt.timezone(dt.timedelta(hours=9))

EVENT_TITLES = {
    grid_detect.FreqDeviation: "周波数逸脱を検知",
    grid_detect.RoCoF: "急激な周波数変化(RoCoF)を検知",
    grid_detect.VoltageAnomaly: "電圧異常を検知",
}
PEAK_LABELS = {
    grid_detect.FreqDeviation: lambda v: f"{v * 1000:.1f} mHz",
    grid_detect.RoCoF: lambda v: f"{v * 1000:.1f} mHz/s",
    grid_detect.VoltageAnomaly: lambda v: f"{v * 100:.1f} %",
}


def handler(event, context):
    for rec in event.get("Records", []):
        key = unquote_plus(rec["s3"]["object"]["key"])
        if not key.startswith(f"{s3keys.SERIES_PREFIX}/"):
            continue
        try:
            _process(key)
        except Exception as e:  # noqa: BLE001
            print(f"detect error on {key}: {e!r}")


def _process(key: str) -> None:
    bucket = os.environ["ELBZ_BUCKET"]
    body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    batch = wire_gridfreq.parse(body)
    h = batch.header

    prev_tail = _prev_boundary_sample_batch(bucket, h)
    batches = ([prev_tail] if prev_tail is not None else []) + [batch]
    samples = grid_detect.samples_from_batches(batches)

    detections = grid_detect.analyze(
        samples,
        f_nominal_hz=h.f_nominal_hz,
        freq_dev_threshold_hz=FREQ_DEV_THRESHOLD_HZ,
        freq_dev_hold_records=FREQ_DEV_HOLD_RECORDS,
        voltage_dev_fraction=VOLTAGE_DEV_FRACTION,
        voltage_dev_hold_records=VOLTAGE_DEV_HOLD_RECORDS,
        nominal_v_rms_mv=NOMINAL_V_RMS_MV,
        rocof_threshold_hz_per_s=ROCOF_THRESHOLD_HZ_PER_S,
    )

    n = notify.from_env()
    for d in detections:
        eid, is_new = grid_events.record(
            h.device_id, d.event_type, d.onset_us, d.last_us, d.peak_value)
        if not is_new:
            continue  # 継続中のセッションへの延長。再送しない
        label = PEAK_LABELS[d.event_type](d.peak_value)
        n.notify(
            EVENT_TITLES[d.event_type],
            f"device *{h.device_id:04d}* で検知。ピーク値 *{label}*。",
            {"デバイス": f"{h.device_id:04d}", "検知時刻": _fmt_time(d.onset_us), "イベント": eid},
        )


def _prev_boundary_sample_batch(bucket: str, h: wire_gridfreq.Header) -> wire_gridfreq.Batch | None:
    """直前バッチの最後の1レコードだけを、1レコードの疑似バッチとして返す。

    周波数計算(`grid_detect.samples_from_batches`)がバッチ境界をまたいで連続性を
    保てるようにするためだけの取得で、直前バッチ全体は読まない——読むと、その
    バッチ内で既に確定済みのrunを毎回このバッチの到着のたびに再評価してしまい、
    `grid_events.record`が(セッションマージの時間窓を過ぎていれば)「新規」と
    誤判定してSlackを埋める。
    """
    keys = store_gridfreq.list_series_keys_in_range(
        s3, bucket, h.batch_start_us - 40_000_000, h.batch_start_us - 1)
    want = f"{h.device_id:04d}-"
    keys = [k for k in keys if k.rsplit("/", 1)[-1].startswith(want)]
    if not keys:
        return None
    prev = wire_gridfreq.parse(s3.get_object(Bucket=bucket, Key=keys[-1])["Body"].read())
    if not prev.records:
        return None
    last_t = prev.timestamps_us()[-1]
    last_r = prev.records[-1]
    tail_header = dataclasses.replace(prev.header, batch_start_us=last_t, record_count=1)
    return wire_gridfreq.Batch(header=tail_header, records=(last_r,))


def _fmt_time(us: int) -> str:
    return dt.datetime.fromtimestamp(us / 1e6, JST).strftime("%Y-%m-%d %H:%M:%S JST")
