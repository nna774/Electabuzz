"""TE(系統時刻偏差)絶対値表示のためのセッションアンカー永続化(DynamoDB)。

→ docs/cloud.md「TE絶対値表示のアンカー」、docs/storage.md「セッションの扱い」、
経緯は docs/log/2026-08-17-te-absolute-display-design.md。

`cycles_q16`はセッション内の絶対値だが、`fs`未規正のNOMINAL区間や
AC入力断(power_fail)を跨ぐと実経過時間と1:1で対応しなくなる。そのため
アンカー(`t0_us`, `cycles0`)は「PPSロック中(`timebase_source`=PPS/PPS_NTP)、
かつ直前にdiscontinuity/power_failが起きていない連続区間(run)」ごとに作る。
1セッションに複数行になりうる。

テーブルの形は`grid_events.py`と同じ流儀に揃える——hash_keyのみ(`anchor_id`)、
「実機1台前提なので`scan`+Pythonの絞り込みで足りる」という割り切りも合わせる。
Query(range key)ではなく`scan`にしているのは効率のためではなく一貫性のためで、
デバイス台数が増えたら見直す前提はgrid_events.py側と共通。
"""

from __future__ import annotations

import os
from decimal import Decimal

import boto3

_table_cache = None


def _table():
    global _table_cache
    if _table_cache is None:
        _table_cache = boto3.resource("dynamodb").Table(os.environ["ELBZ_TE_ANCHORS_TABLE"])
    return _table_cache


def anchor_id(device_id: int, session_id: int, t0_us: int) -> str:
    return f"{device_id:04d}-{session_id}-{t0_us}"


def _rows_for_session(device_id: int, session_id: int) -> list[dict]:
    """このdevice×sessionのアンカー行を全部返す(`grid_events._latest_event`と
    同じ「実機1台なのでscanで足りる」割り切り)。"""
    return [i for i in _table().scan(Limit=1000).get("Items", [])
            if int(i.get("device_id", -1)) == device_id
            and int(i.get("session_id", -1)) == session_id]


def _latest_open_row(device_id: int, session_id: int) -> dict | None:
    open_rows = [i for i in _rows_for_session(device_id, session_id) if i.get("run_open")]
    if not open_rows:
        return None
    return max(open_rows, key=lambda x: int(x["t0_us"]))


def close_open_run(device_id: int, session_id: int) -> None:
    """開いているrunがあれば閉じる(discontinuity/power_fail検出時に呼ぶ)。

    新規行は作らない——このバッチ自体は信用できないので種にしない。開いている
    行が無ければ何もしない(idempotent。同じ断線中に複数バッチ届いても安全)。
    """
    latest = _latest_open_row(device_id, session_id)
    if latest is None:
        return
    _table().update_item(
        Key={"anchor_id": latest["anchor_id"]},
        UpdateExpression="SET run_open = :f",
        ExpressionAttributeValues={":f": False},
    )


def open_run_if_needed(device_id: int, session_id: int, t0_us: int, cycles0: float,
                        tb_residual_ns: int) -> None:
    """PPS規正済み・suspectでないバッチが来た時に呼ぶ。

    既に開いているrunがあれば何もしない(そのrunの範囲内なので新しいアンカーは
    要らない)。無ければ、このバッチの最初のレコードを新しいアンカーとして開く。
    """
    if _latest_open_row(device_id, session_id) is not None:
        return
    _table().put_item(Item={
        "anchor_id": anchor_id(device_id, session_id, t0_us),
        "device_id": device_id,
        "session_id": session_id,
        "t0_us": t0_us,
        "cycles0": Decimal(str(cycles0)),
        "run_open": True,
        "tb_residual_ns": tb_residual_ns,
    })


def anchors_for_session(device_id: int, session_id: int) -> list[dict]:
    """api側が読む: このdevice×sessionのアンカーを`t0_us`昇順で返す。

    各要素は`{"t0_us": int, "cycles0": float}`。`run_open`はここでは返さない
    ——読み出し側(`_series_payload`)は「`t0_us`がバッチの時刻以下で最大の行」を
    使うだけで、runが開いているかどうかは書き込み側だけの関心事だから。
    """
    rows = sorted(_rows_for_session(device_id, session_id), key=lambda x: int(x["t0_us"]))
    return [{"t0_us": int(r["t0_us"]), "cycles0": float(r["cycles0"])} for r in rows]
