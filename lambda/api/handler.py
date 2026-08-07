"""api Lambda: ダッシュボード向けの読み取りAPI（認証なし・CORS許可）。

Lambda Function URL (payload v2.0)。Namazu の
[api/handler.py](https://github.com/nna774/NamazuHaUrokoGaNai/blob/master/lambda/api/handler.py)
と同じ役回りだが、Electabuzz には detect/events も生存台帳もまだ無いので
`/recent` だけを持つ（→ docs/cloud.md, docs/roadmap.md フェーズ8/9）。

    GET /recent?minutes=5&start=<us>   直近N分（既定5、上限 MAX_RECENT_MINUTES）の
                                        瞬時周波数の時系列。start指定で[start-minutes,start]

"latest"（系列の末尾点）に時間基準の品質（timebase_source・fs_measured_hz・
tb_residual_ns）を載せる。これがダッシュボードの「今の状態」表示の全てで、
生存台帳が無い今は**このAPIが最後に何かを返せているかどうか自体が
生存確認になる**（`t_us`の最後の値の鮮度をUI側で見る）。
"""

from __future__ import annotations

import json
import math
import os
import time

import boto3

import store_gridfreq
import wire_gridfreq

_S3 = None


def _s3():
    global _S3
    if _S3 is None:
        _S3 = boto3.client("s3")
    return _S3


BUCKET_ENV = "ELBZ_BUCKET"
# /recent の分数上限。上限が無いと巨大値でS3 LIST/GETを大量発行してハング/課金する
# （認証なし公開のため要ガード。→ Namazuのapiと同じ理由）。
MAX_RECENT_MINUTES = 30.0
# CORSヘッダは Function URL の cors 設定に任せる（ここで access-control-* を返すと
# 二重になりブラウザが弾く）。ここは content-type のみ。
HEADERS = {"content-type": "application/json"}


def _json(code: int, obj) -> dict:
    return {"statusCode": code, "headers": HEADERS, "body": json.dumps(obj)}


def handler(event, context):
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    if method == "OPTIONS":
        return {"statusCode": 204, "headers": {}, "body": ""}
    path = event.get("rawPath", "/").rstrip("/")
    q = event.get("queryStringParameters") or {}
    try:
        if path.endswith("/recent"):
            return _recent(q)
        return _json(404, {"error": "not found"})
    except Exception as e:  # noqa: BLE001
        print(f"api error: {e!r}")
        return _json(500, {"error": str(e)})


def _recent(q):
    try:
        minutes = float(q.get("minutes", "5"))
    except (TypeError, ValueError):
        minutes = 5.0
    if not math.isfinite(minutes):
        minutes = 5.0
    minutes = max(0.1, min(minutes, MAX_RECENT_MINUTES))  # 巨大値によるS3スキャン暴走を防ぐ

    span_us = int(minutes * 60 * 1e6)
    end_us = int(time.time() * 1e6)
    start = q.get("start")
    if start:
        try:
            end_us = int(float(start))
        except (TypeError, ValueError):
            pass
    start_us = end_us - span_us

    bucket = os.environ[BUCKET_ENV]
    batches = store_gridfreq.load_batches_in_range(_s3(), bucket, start_us, end_us)
    return _json(200, _series_payload(batches, start_us, end_us))


def _series_payload(batches: list[wire_gridfreq.Batch], start_us: int, end_us: int) -> dict:
    t_us: list[int] = []
    freq_hz: list[float | None] = []
    latest = None

    # 隣接レコード間で周波数(=cyclesの差分/経過時間)を計算するための「直前の点」。
    # session_id が変わる(再起動)・間隔が想定(record_rate_mhz)から大きく外れる・
    # DISCONTINUITY が立ったバッチをまたぐ、のいずれかでは前の点を引き継がず
    # (=Noneのまま)、その点の周波数はNoneにする。**測れなかった区間を
    # 測れたように見せない**——GfrqFlagDiscontinuity/GoertzelEstimator::resetWindow()
    # と同じ原則(→ docs/timebase.md)。
    prev_session = None
    prev_t = None
    prev_cycles = None

    for b in batches:
        h = b.header
        # DISCONTINUITY を立てたバッチは、内部の隣接レコード間隔が record_rate_mhz
        # どおりである保証が無い(ファーム側 resetWindow() は該当窓を無出力にするだけで、
        # ワイヤ上のレコード列は詰まって見える)。このバッチ内では周波数を計算しない。
        suspect = bool(h.batch_flags & wire_gridfreq.BatchFlag.DISCONTINUITY)
        nominal_dt = 1000.0 / h.record_rate_mhz if h.record_rate_mhz > 0 else None

        for t, r in zip(b.timestamps_us(), b.records):
            in_range = start_us <= t <= end_us
            f = None
            if (not suspect and nominal_dt and prev_t is not None
                    and prev_session == h.session_id):
                dt = (t - prev_t) / 1e6
                if 0.5 * nominal_dt <= dt <= 2.0 * nominal_dt:
                    f = (r.cycles - prev_cycles) / dt

            if in_range:
                t_us.append(t)
                freq_hz.append(round(f, 6) if f is not None else None)
                latest = {
                    "t_us": t,
                    "freq_hz": round(f, 6) if f is not None else None,
                    "f_nominal_hz": h.f_nominal_hz,
                    "timebase_source": h.source_name,
                    "is_disciplined": h.is_disciplined,
                    "fs_measured_hz": round(h.fs_measured_hz, 4),
                    "tb_residual_ns": h.tb_residual_ns,
                    "soc_temp_c": h.soc_temp_c,
                    "session_id": h.session_id,
                    "device_id": h.device_id,
                }

            if not suspect:
                prev_session, prev_t, prev_cycles = h.session_id, t, r.cycles
            else:
                prev_session, prev_t, prev_cycles = None, None, None

    return {
        "start_us": start_us, "end_us": end_us, "n": len(t_us),
        "t_us": t_us, "freq_hz": freq_hz, "latest": latest,
    }
