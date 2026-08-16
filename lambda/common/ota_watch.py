"""pull型OTAの停滞検知・達成検知（docs/ota.md §2）。

Namazu(`lambda/common/ota_watch.py`)からの移植。`pending_ota_version`は一度
伝えたら消す一回性の値ではなく、デバイスが実際にそのバージョンで起動するまで
サーバが持ち続ける「あるべき状態」。そのため、サーバ側からは「デバイスが取得に
成功したか」を直接は観測できない——というのが元々の前提だったが、firmwareが
毎バッチ`X-Elbz-Fw-Version`で現在版数を送ってくるので、「達成したか」はingestが
受信するバッチから分かる(`fw_version`と`pending_ota_version`の一致)。達成したら
`reached_target()`でこの一致を判定し、ingest側で`ota_target.clear_ota_target()`を
呼んでサーバ側の状態を解放する（さもないと`pending_ota_version`が達成後も残り
続け、時間経過だけを見る`evaluate_ota_stuck()`が成功後も「停滞」を誤検知する）。

それでも「達成前に何が起きているか」（証明書検証失敗か・ネットワーク不調か等）は
デバイスのシリアルログでしか分からないので、停滞検知（時間経過ベース）は
引き続き必要。代わりに「要求してから長時間経っても解消しない」ことをwatchdog
Lambdaが外側から検知してSlack通知する。原因は問わない。

Electabuzzには`ota_target.py`（Namazuの`ota_target`相当、`reached_target`/
`clear_ota_target`）が既にingest側にあるので、この層は停滞検知(`evaluate_ota_stuck`)
だけを持つ。
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


def evaluate_ota_stuck(item: dict, now_us: int, stuck_after_us: int,
                       renotify_after_us: int) -> str | None:
    """通知が要るなら "stuck"（初回）/"stuck_again"（再送）、不要なら None。

    DynamoDB抜きでテストできるよう、判定はこの純粋関数に集約する
    （devices.evaluate()と同じ考え方）。
    """
    pending = item.get("pending_ota_version")
    requested_at = int(item.get("pending_ota_requested_at_us", 0) or 0)
    if not pending or not requested_at:
        return None
    if now_us - requested_at < stuck_after_us:
        return None
    notified_at = int(item.get("ota_stuck_notified_at_us", 0) or 0)
    if not notified_at:
        return "stuck"
    if now_us - notified_at >= renotify_after_us:
        return "stuck_again"
    return None


def mark_ota_stuck_notified(device_id: int, at_us: int) -> None:
    _table().update_item(
        Key={"device_id": device_id},
        UpdateExpression="SET ota_stuck_notified_at_us = :t",
        ExpressionAttributeValues={":t": at_us},
    )
