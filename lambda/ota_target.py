"""pull型OTAの配信対象(pending_ota_version)の達成検知・解放（→ docs/ota.md）。

`pending_ota_version`は`tools/request_ota.py`が立てる「あるべき状態」。デバイスが
実際にそのバージョンで起動するまで(=毎バッチの`X-Elbz-Fw-Version`ヘッダが一致する
まで)ingestが`X-Elbz-Ota-Version`ヘッダとして返し続け、一致したらここでクリアする。

Namazuの`lambda/common/ota_watch.py`と同じ考え方——書き込み関数はプロジェクト固有の
概念なので共有ライブラリ(batch-uplink)には置かない。**停滞検知(時間経過ベースの
再通知)は移植していない**——Electabuzzにはwatchdog Lambda自体が無く、「気づかず
放置される」ことへの保険を先取りする理由が無い(→ docs/open-questions.md)。
今は`tools/request_ota.py list`で手元から照会する運用に留める。
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


def reached_target(item: dict) -> bool:
    """このバッチの`fw_version`が`pending_ota_version`に追いついたか。"""
    pending = item.get("pending_ota_version")
    return bool(pending) and item.get("fw_version") == pending


def clear_ota_target(device_id: int, matched_version: str) -> None:
    """達成済みの`pending_ota_version`をサーバ側から解放する。

    要求してからここまでの間に別バージョンが新たに要求されているかもしれないので、
    読んだ時の値のまま変わっていない場合だけ消す(condition不成立はレースで新しい
    要求が割り込んだだけなので無視してよい)。
    """
    try:
        _table().update_item(
            Key={"device_id": device_id},
            UpdateExpression="REMOVE pending_ota_version, pending_ota_requested_at_us",
            ConditionExpression="pending_ota_version = :v",
            ExpressionAttributeValues={":v": matched_version},
        )
    except _table().meta.client.exceptions.ConditionalCheckFailedException:
        pass
