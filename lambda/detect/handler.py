"""detect Lambda: `series/`への新規バッチ到着ごとに、周波数逸脱・RoCoF・電圧異常を
判定してDynamoDBに記録し、新規セッションだけSlack通知する(→ docs/cloud.md「detect」)。

Namazuのdetect(地震の震度をFFT窓で再計算する)とは判定の性質が違う。GFRQは
既に1Hzで瞬時周波数の元になる累積位相を運んでいるので、窓を再解析する必要が
無く、レコード単位のしきい値判定で足りる(→ `lambda/common/grid_detect.py`)。

- S3のObjectCreated(`series/*`)で起動
- 直前バッチの最後の1レコードだけを追加取得し、境界をまたぐ周波数計算の連続性を
  確保する。**それより過去には遡らない**——遡ると、数十秒前に既に確定済みの
  runを毎回再解析してSlackを埋める（`grid_events.record`のセッションマージが
  時間切れ後は「新規」と判断してしまうため）。直前バッチのキーは生存台帳の
  `prev_batch_key`(`batch_uplink.devices`、`track_prev_key=True`)から`GetItem`で
  引く。以前はS3の`ListObjectsV2`で探していたが、バッチ到着(実測30秒間隔)の
  たびに無期限でListが飛び続けコストを底上げしていたため置き換えた
- しきい値判定そのものは`grid_detect.analyze`(副作用の無い純粋関数)に委ねる
- 新規セッションだけ通知する。継続中の延長は`/events`のlast_usで追える
  （watchdogのような定期再送は持たない——detectはイベント駆動で、継続を
  再送する専用の仕組みを別に持つ理由が薄い）
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import math
import os
from urllib.parse import unquote_plus

import boto3

from batch_uplink import devices, notify

import s3keys
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

# dashboard/app.jsのEVENT_VIEW_MINUTES(#minutesが選べるプリセット)と同じ値。
EVENT_VIEW_MINUTES = (1, 5, 15, 30)


def _event_view_window(onset_us: int, last_us: int) -> tuple[int, int]:
    """イベントが収まる表示範囲(分)と、dashboardの`#live?...&s=`用の終端時刻(epoch秒)を計算する。
    dashboard/app.jsのeventViewWindow()(イベント行クリック時の自動ジャンプ)と同じ式——
    通知のリンク先とdashboard上の操作で見える範囲を一致させるため、計算をここに複製する。"""
    duration_s = max(1.0, (last_us - onset_us) / 1e6)
    padding_s = max(30.0, duration_s * 0.5)
    needed_minutes = (duration_s + padding_s * 2) / 60
    minutes = next((m for m in EVENT_VIEW_MINUTES if m >= needed_minutes), EVENT_VIEW_MINUTES[-1])
    end_sec = math.ceil(last_us / 1e6 + padding_s)
    return minutes, end_sec


def _event_link(eid: str, onset_us: int, last_us: int) -> str:
    """イベントIDを、そのイベントが収まる範囲でdashboardのグラフを開くSlack mrkdwnリンクにする。
    NAMZ_DASHBOARD_URL未設定ならIDのまま返す(watchdogの_device_fieldと同じ考え方)。"""
    base = os.environ.get("NAMZ_DASHBOARD_URL", "").rstrip("/")
    if not base:
        return eid
    minutes, end_sec = _event_view_window(onset_us, last_us)
    return f"<{base}/#live?m={minutes}&auto=0&s={end_sec}|{eid}>"


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
            {"デバイス": f"{h.device_id:04d}", "検知時刻": _fmt_time(d.onset_us),
             "イベント": _event_link(eid, d.onset_us, d.last_us)},
        )


def _prev_boundary_sample_batch(bucket: str, h: wire_gridfreq.Header) -> wire_gridfreq.Batch | None:
    """直前バッチの最後の1レコードだけを、1レコードの疑似バッチとして返す。

    周波数計算(`grid_detect.samples_from_batches`)がバッチ境界をまたいで連続性を
    保てるようにするためだけの取得で、直前バッチ全体は読まない——読むと、その
    バッチ内で既に確定済みのrunを毎回このバッチの到着のたびに再評価してしまい、
    `grid_events.record`が(セッションマージの時間窓を過ぎていれば)「新規」と
    誤判定してSlackを埋める。

    直前バッチのキーは生存台帳(`NAMZ_DEVICES_TABLE`)の`prev_batch_key`から
    `GetItem`一発で分かる(ingestが`record_batch(..., track_prev_key=True)`で
    バッチ受信のたびにアトミックに更新している)。以前は`ListObjectsV2`で
    時間窓を探しに行っていたが、バッチ到着(実測30秒間隔)のたびに無期限で
    Listが飛び続けS3コストを底上げしていたため置き換えた
    (→ docs/log/2026-08-23-detect-listobjectsv2-cost-and-prev-batch-key-design.md)。

    `ingest`は`series/`へのS3 PUT(このLambdaを起動する側)の**後**に
    `devices.record_batch`を呼んでいるので、稀に`prev_batch_key`がまだ
    このバッチぶんに更新されていない(＝1つ前の値のまま)状態でここに来る
    ことがありうる。実害は無い——その場合は単に古いキーが返るので、下の
    `batch_start_us`チェックで弾かれ、Listだった頃の「直前バッチが見つからない」
    場合と同じ`None`扱いに落ちる。
    """
    item = devices.get_device(h.device_id)
    key = item.get("prev_batch_key") if item else None
    if not key:
        return None
    try:
        prev = wire_gridfreq.parse(s3.get_object(Bucket=bucket, Key=key)["Body"].read())
    except Exception:  # noqa: BLE001
        return None
    if not prev.records or prev.header.batch_start_us >= h.batch_start_us:
        return None
    last_t = prev.timestamps_us()[-1]
    last_r = prev.records[-1]
    tail_header = dataclasses.replace(prev.header, batch_start_us=last_t, record_count=1)
    return wire_gridfreq.Batch(header=tail_header, records=(last_r,))


def _fmt_time(us: int) -> str:
    return dt.datetime.fromtimestamp(us / 1e6, JST).strftime("%Y-%m-%d %H:%M:%S JST")
