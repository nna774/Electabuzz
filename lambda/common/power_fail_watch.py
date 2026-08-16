"""AC入力断(GFRQ `flags`の`power_fail`ビット)を生存台帳へ反映し、watchdogが
状態遷移を判定する層。

Namazuには無いElectabuzz固有の概念（→ docs/open-questions.md「AC入力線の入力断
検知・物理固定」）。`kGfrqFlagPowerFail`はバッチ単位のフラグ(その30秒区間に断を
検出した窓を含む)なので、「今も断が続いているか」の判定はここでは持たない——
ingestが毎バッチ最新の値をそのまま生存台帳へ上書きし(`record()`)、watchdogが
`batch_uplink.devices.evaluate_lag()`と同じ形の純粋関数(`evaluate()`)で通知要否を
判定する。

**線が抜けたのか停電したのかは区別しない。** AFE単体の信号では原理的に区別できないと
判明している(→ docs/open-questions.md、docs/risks.md リスク13)。「AC入力が見えない」で
一本化し、原因の切り分けは人間が現地で行う。

書き手はNamazu固有の概念(`lambda/common/ota_watch.py`等)と同じ理由でこちらの
`lambda/common`側に持つ。
"""

from __future__ import annotations

import os

import boto3

from batch_uplink import devices

_table_cache = None


def _table():
    global _table_cache
    if _table_cache is None:
        _table_cache = boto3.resource("dynamodb").Table(os.environ["NAMZ_DEVICES_TABLE"])
    return _table_cache


def record(device_id: int, power_fail: bool) -> None:
    """このバッチの`power_fail`フラグを生存台帳へ反映する(毎バッチ呼んでよい)。

    最新バッチの値でそのまま上書きする。デバイスが送信を続ける限り常に"今"の
    状態を保つ——欠測中に古い値が残り続けても`evaluate()`側がoffline中は黙るので
    実害は無い。
    """
    _table().update_item(
        Key={"device_id": device_id},
        UpdateExpression="SET power_fail = :p",
        ExpressionAttributeValues={":p": power_fail},
    )


def evaluate(item: dict, now_us: int, offline_after_us: int,
            renotify_after_us: int) -> str | None:
    """AC入力断の状態遷移を判定し、取るべき通知アクションを返す（副作用なし・テスト用）。

    `batch_uplink.devices.evaluate_lag()`と同じ設計——**欠測中は黙る**（offline側の
    通知が担当。データが来ていないのに古いpower_fail状態だけで通知し続けるのを防ぐ）。

    返り値:
      - None                  … 何もしない
      - "power_fail"          … 初めて断を検知した
      - "power_fail_again"    … 断が続いており再送間隔を過ぎた
      - "power_fail_recovery" … 断通知後に復帰した
    """
    if devices.staleness_us(item, now_us) > offline_after_us:
        return None  # 欠測中は欠測通知の担当。power_fail は黙る
    active = bool(item.get("power_fail"))
    notified_at = item.get("power_fail_notified_at_us")
    notified = notified_at is not None
    if active:
        if not notified:
            return "power_fail"
        if now_us - int(notified_at) >= renotify_after_us:
            return "power_fail_again"
        return None
    if notified:
        return "power_fail_recovery"
    return None


def mark_notified(device_id: int, at_us: int) -> None:
    """AC入力断の通知を送ったことを記録（watchdog専用）。"""
    _table().update_item(
        Key={"device_id": device_id},
        UpdateExpression="SET power_fail_notified_at_us = :t",
        ExpressionAttributeValues={":t": at_us},
    )


def clear_notified(device_id: int) -> None:
    """AC入力断の通知状態を解除（復帰時にwatchdogが呼ぶ）。"""
    _table().update_item(
        Key={"device_id": device_id},
        UpdateExpression="REMOVE power_fail_notified_at_us",
    )
