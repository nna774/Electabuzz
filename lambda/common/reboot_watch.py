"""稼働時間ヘッダ(`X-Elbz-Uptime-Us`)から起動時刻を逆算し、再起動検知を生存台帳へ
反映する層。

Namazu(`lambda/common/device_meta.py`)の`boot_epoch_us`算出をそのまま踏襲するが、
`reset_reason`ヘッダ(`X-Namz-Reset-Reason`相当)は持たない——Electabuzzのfirmwareが
送るヘッダは`X-Elbz-Fw-Version`/`X-Elbz-Heap-Free`/`X-Elbz-Uptime-Us`の3つだけで
(→ docs/ota.md)、reset reasonは今は送っていない。

再起動そのもの(`boot_epoch_us`の変化)はwatchdogがSlackへ通知する。Electabuzzの
pull型OTAは`tools/request_ota.py`の手動許可でしか動かないので、それを経ない再起動は
WDTパニック等の異常を示している可能性がある(Namazu側での実例 →
docs/log/2026-08-08-wdt-panic-hypothesis.md と同種の懸念)。
"""

from __future__ import annotations

import os

import boto3

_table_cache = None

# 再起動検知の閾値（TimeSyncのドリフト許容。Namazuのdevice_meta.pyと同じ値）。
# boot_epoch_us の逆算値がこれを超えてズレていたら「再起動があった」とみなす。
BOOT_EPOCH_DRIFT_THRESHOLD_US = 120_000_000  # ±2分


def _table():
    global _table_cache
    if _table_cache is None:
        _table_cache = boto3.resource("dynamodb").Table(os.environ["NAMZ_DEVICES_TABLE"])
    return _table_cache


def should_update_boot_epoch(prev_boot_epoch_us, new_boot_epoch_us: int) -> bool:
    """ブートepochを書き換えるべきか(=再起動を検知したか)を判定する（副作用なし）。

    未記録(prev=None、初回受信)なら無条件で書く。既に記録済みなら
    BOOT_EPOCH_DRIFT_THRESHOLD_USを超えてズレた時だけ「再起動があった」とみなす。
    """
    if prev_boot_epoch_us is None:
        return True
    return abs(new_boot_epoch_us - int(prev_boot_epoch_us)) > BOOT_EPOCH_DRIFT_THRESHOLD_US


def record_boot_epoch(device_id: int, boot_epoch_us: int) -> None:
    """起動時刻(boot_epoch_us = batch_start_us - uptime_us)を記録する。

    呼び出し側(ingest)がBOOT_EPOCH_DRIFT_THRESHOLD_USを超えたズレ（＝再起動）を
    検知した時だけ呼ぶ想定。この差分検知自体が再起動検知になる。
    """
    _table().update_item(
        Key={"device_id": device_id},
        UpdateExpression="SET boot_epoch_us = :b",
        ExpressionAttributeValues={":b": int(boot_epoch_us)},
    )


def evaluate_reboot(item: dict) -> str | None:
    """再起動を通知すべきかを判定する（副作用なし・テスト用）。

    `boot_epoch_notified_us`（前回watchdogが見て通知処理を終えた値）と現在の
    `boot_epoch_us`を比べる。初見（前回値が無い）は基準を作るだけで通知しない
    ——監視を始めた瞬間に「起動していた」ことを再起動と誤認しないため。

    返り値:
      - None       … 変化なし
      - "baseline" … 初回観測。記録だけする(通知しない)
      - "rebooted" … 前回watchdogが見た値と変わった。通知する
    """
    boot = item.get("boot_epoch_us")
    if boot is None:
        return None
    last = item.get("boot_epoch_notified_us")
    if last is None:
        return "baseline"
    if int(boot) != int(last):
        return "rebooted"
    return None


def mark_reboot_notified(device_id: int, boot_epoch_us: int) -> None:
    """このboot_epoch_usまでwatchdogが処理済みであることを記録する（watchdog専用）。"""
    _table().update_item(
        Key={"device_id": device_id},
        UpdateExpression="SET boot_epoch_notified_us = :b",
        ExpressionAttributeValues={":b": int(boot_epoch_us)},
    )
