"""確定検知したdetectイベントのDynamoDB管理(→ docs/cloud.md「detect」)。

Namazuの`lambda/common/events.py`と同じセッション方式(直近の活動から
`MERGE_GAP_US`以内のonsetは新規イベントにせず延長する)を踏襲するが、
デバイス速報とクラウド確定報の突合は無い——Electabuzzのdetectはクラウド側の
しきい値判定だけで完結するので(→ `lambda/common/grid_detect.py`)、単一段で足りる。

通知要否の判定は「新規セッションを作ったかどうか」だけで足りる（`record()`の
戻り値`is_new`）。watchdogのような定期再送は持たない——detectはバッチ到着で
起動するイベント駆動であり、継続中の逸脱を"再送"する専用の仕組みを別途持つ
理由が薄い(継続状況は`/events`のlast_usで追える)。
"""

from __future__ import annotations

import os
from decimal import Decimal

import boto3

# 直近イベントの活動終端(last_us)からこの時間内のonsetは同一セッションとして延長する。
MERGE_GAP_US = 60_000_000  # 60秒
# 新規セッションのevent_idを作る際の時刻粒度[us]（読みやすさのため。Namazuと同じ）。
BUCKET_US = 30_000_000  # 30秒

_table_cache = None


def _table():
    global _table_cache
    if _table_cache is None:
        _table_cache = boto3.resource("dynamodb").Table(os.environ["NAMZ_EVENTS_TABLE"])
    return _table_cache


def event_id(device_id: int, event_type: str, onset_us: int) -> str:
    return f"{device_id:04d}-{event_type}-{onset_us // BUCKET_US:d}"


def _latest_event(device_id: int, event_type: str) -> dict | None:
    """このdevice×event_typeの最新イベント(last_usが最大のもの)。

    単一デバイス想定の簡易scan(Namazuの`_latest_event`と同じ割り切り)。
    """
    items = [i for i in _table().scan(Limit=1000).get("Items", [])
             if int(i.get("device_id", -1)) == device_id and i.get("event_type") == event_type]
    if not items:
        return None
    return max(items, key=lambda x: int(x.get("last_us", x.get("onset_us", 0))))


def record(device_id: int, event_type: str, onset_us: int, last_us: int,
           peak_value: float) -> tuple[str, bool]:
    """検知1件を記録する。直近セッションへ延長できるならそちらを更新し、
    できなければ新規セッションを作る。

    戻り値: (event_id, is_new)。`is_new`がTrueの時だけ呼び出し側は通知すること
    （継続中の延長を毎回通知すると同じ逸脱でSlackが埋まる）。
    """
    latest = _latest_event(device_id, event_type)
    if latest:
        onset0 = int(latest.get("onset_us", 0))
        last0 = int(latest.get("last_us", onset0))
        if onset0 - MERGE_GAP_US <= onset_us <= last0 + MERGE_GAP_US:
            eid = latest["event_id"]
            new_last = max(last0, last_us)
            new_peak = max(float(latest.get("peak_value", 0.0)), peak_value)
            _table().update_item(
                Key={"event_id": eid},
                UpdateExpression="SET last_us = :l, peak_value = :p",
                ExpressionAttributeValues={":l": new_last, ":p": Decimal(str(new_peak))},
            )
            return eid, False

    eid = event_id(device_id, event_type, onset_us)
    _table().put_item(Item={
        "event_id": eid,
        "device_id": device_id,
        "event_type": event_type,
        "onset_us": onset_us,
        "last_us": last_us,
        "peak_value": Decimal(str(peak_value)),
    })
    return eid, True


def recent_events(limit: int = 50) -> list[dict]:
    """最近のイベントを`last_us`降順で返す(Namazuの`events.recent_events`と同じ
    簡易scan——実機1台・イベント数が少ない前提)。"""
    items = _table().scan(Limit=1000).get("Items", [])
    items.sort(key=lambda x: int(x.get("last_us", x.get("onset_us", 0))), reverse=True)
    return items[:limit]
