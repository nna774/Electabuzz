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
# 最新セッションへのポインタ項目のevent_id接頭辞。イベント本体と同じテーブルに置く。
LATEST_POINTER_PREFIX = "latest#"

_table_cache = None


def _table():
    global _table_cache
    if _table_cache is None:
        _table_cache = boto3.resource("dynamodb").Table(os.environ["NAMZ_EVENTS_TABLE"])
    return _table_cache


def event_id(device_id: int, event_type: str, onset_us: int) -> str:
    return f"{device_id:04d}-{event_type}-{onset_us // BUCKET_US:d}"


def latest_pointer_id(device_id: int, event_type: str) -> str:
    """device×event_typeごとの最新セッションを指すポインタ項目のキー。"""
    return f"{LATEST_POINTER_PREFIX}{device_id:04d}-{event_type}"


def is_pointer(item: dict) -> bool:
    return str(item.get("event_id", "")).startswith(LATEST_POINTER_PREFIX)


def _scan_all() -> list[dict]:
    items: list[dict] = []
    kwargs: dict = {}
    while True:
        resp = _table().scan(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            return items
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def _latest_event(device_id: int, event_type: str) -> dict | None:
    """このdevice×event_typeの最新セッション。

    ポインタ項目から`GetItem`で引く。ポインタがまだ無い(導入前から記録がある)
    ときだけ全件scanで探し、見つけたらポインタを作る。
    """
    ptr = _table().get_item(Key={"event_id": latest_pointer_id(device_id, event_type)}).get("Item")
    if ptr:
        return _table().get_item(Key={"event_id": ptr["latest_event_id"]}).get("Item")
    items = [i for i in _scan_all()
             if not is_pointer(i)
             and int(i.get("device_id", -1)) == device_id and i.get("event_type") == event_type]
    if not items:
        return None
    latest = max(items, key=lambda x: int(x.get("last_us", x.get("onset_us", 0))))
    _put_pointer(device_id, event_type, latest["event_id"])
    return latest


def _put_pointer(device_id: int, event_type: str, eid: str) -> None:
    _table().put_item(Item={
        "event_id": latest_pointer_id(device_id, event_type),
        "latest_event_id": eid,
    })


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
    _put_pointer(device_id, event_type, eid)
    return eid, True


def recent_events(limit: int = 50) -> list[dict]:
    """最近のイベントを`last_us`降順で返す(全件scan。件数が増えたらGSIが要る)。"""
    items = [i for i in _scan_all() if not is_pointer(i)]
    items.sort(key=lambda x: int(x.get("last_us", x.get("onset_us", 0))), reverse=True)
    return items[:limit]
