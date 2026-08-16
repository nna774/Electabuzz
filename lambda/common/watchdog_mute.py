"""退役・一時停止したデバイスをwatchdogの欠測監視から外す「mute」。

Namazu(`lambda/common/watchdog_mute.py`)からの移植。実機は1台構成だが、将来
試験機(ハード試験のたびに繋いでは黙る機体)を扱う場面や退役に備え、Namazuと同じ
設計をそのまま持ち込む: mute中はwatchdogが完全に無視するが、ingestが実際に
バッチを受信した瞬間に自動でunmuteされる。つまり「試験を始めて送信が来た時点で
監視が復帰し、試験中に落ちれば通常通り通知が来る。試験が終わって黙ったら1回だけ
欠測通知が来るので、そこで手元CLI(`tools/mute_device.py`)で再度muteする」という
運用になる。

Namazu固有の概念と同じ理由でこちらの`lambda/common`側に持つ。
"""

from __future__ import annotations

import os

import boto3

_table_cache = None


def _table():
    global _table_cache
    if _table_cache is None:
        _table_cache = boto3.resource("dynamodb").Table(os.environ["NAMZ_DEVICES_TABLE"])
    return _table_cache


def is_muted(item: dict) -> bool:
    """watchdogがこのデバイスを無視すべきか（副作用なし・テスト用）。"""
    return bool(item.get("watchdog_muted"))


def mute(device_id: int) -> None:
    """監視対象外にする（手元CLI専用）。"""
    _table().update_item(
        Key={"device_id": device_id},
        UpdateExpression="SET watchdog_muted = :t",
        ExpressionAttributeValues={":t": True},
    )


def clear_mute(device_id: int) -> None:
    """監視対象に戻す。ingestがバッチを受信するたび無条件で呼んでよい
    （mute中でなければ何もしない、REMOVEは対象属性が無くても失敗しない）。"""
    _table().update_item(
        Key={"device_id": device_id},
        UpdateExpression="REMOVE watchdog_muted",
    )
