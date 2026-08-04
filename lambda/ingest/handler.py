"""ingest Lambda: デバイスからの GFRQ バッチ POST を受けて S3 へ置く。

Lambda Function URL (payload v2.0) 前提。Namazu の
[ingest/handler.py](https://github.com/nna774/NamazuHaUrokoGaNai/blob/master/lambda/ingest/handler.py)
を踏襲するが、**別スタック・別関数**である（→ docs/cloud.md）。

    POST /   : 30秒バッチ (application/octet-stream, HMAC署名) → S3 series/ へ

`/alert` は**意図的に実装していない。** 周波数側のイベント定義（逸脱・RoCoF・
停電）も通知先も未確定で、今書くと確定した頃には作り直しになる。→ docs/cloud.md

## 設定（環境変数）

**`batch_uplink` が読む変数は `NAMZ_` のまま、こちらの独自変数は `ELBZ_`。**
共有ライブラリ側の名前を改名すると稼働中の地震計が壊れるので、
**名前は地震計由来のまま、値だけ Electabuzz のスタックのものを渡す。**
→ docs/batch-uplink.md

| 名前 | 読む主体 | 用途 |
|---|---|---|
| `ELBZ_BUCKET` | ここ | 保存先バケット（必須） |
| `NAMZ_HMAC_SECRET`, `NAMZ_HMAC_SECRET_<id>` | `batch_uplink.auth` | デバイス共有鍵 |
| `NAMZ_DEVICES_TABLE` | `batch_uplink.devices` | 生存台帳。**未設定なら台帳を書かない** |
"""

from __future__ import annotations

import base64
import hashlib
import os
import time

import boto3

from batch_uplink import auth, devices

import s3keys
import wire_gridfreq

# クライアント生成を import 時にやらない。**リージョン未設定の環境で import すら
# できなくなる**とテストから触れなくなるので、初回利用まで遅らせる。
# boto3 自体は import しておく（同梱漏れは黙って進ませずここで落とす）。
_S3 = None


def _s3():
    global _S3
    if _S3 is None:
        _S3 = boto3.client("s3")
    return _S3


def _resp(code: int, msg: str):
    return {"statusCode": code, "headers": {"content-type": "text/plain"}, "body": msg}


def handler(event, context):
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    body = event.get("body") or ""
    raw = base64.b64decode(body) if event.get("isBase64Encoded") else body.encode()

    device = headers.get("x-namz-device", "")
    sig = headers.get("x-namz-signature", "")
    try:
        auth.verify(device, raw, sig)
    except auth.AuthError as e:
        return _resp(401, f"auth: {e}")

    try:
        return _handle_batch(raw, device)
    except Exception as e:  # noqa: BLE001
        print(f"ingest error: {e!r}")
        return _resp(400, f"error: {e}")


def _handle_batch(raw: bytes, auth_device: str):
    try:
        b = wire_gridfreq.parse(raw)
    except wire_gridfreq.CrcMismatch as e:
        # **「読めない」と「壊れている」を分けてある意味がここで出る。**
        # 400 を返すとデバイスは同じ壊れたバッチを送り直し続けて uplink が詰まる。
        # 捨てると壊れ方の証拠が消える。**隔離して 200 を返し、次へ進ませる。**
        return _quarantine(raw, auth_device, str(e))
    # CrcMismatch 以外の WireFormatError はここで握らない。上の handler が 400 に
    # する。**設定ミス（例: 地震計のバッチが届いている）は fail-fast で報告する。**

    # 認証に使った device と本文の device_id の一致を強制（別デバイスの騙り防止）。
    if str(b.header.device_id) != auth_device:
        return _resp(403, "device mismatch")

    key = s3keys.series_key(b.header.device_id, b.header.batch_start_us)
    # 測定開始時刻ベースのキーなので二重送信は同一キー上書き（冪等）。
    _s3().put_object(Bucket=os.environ["ELBZ_BUCKET"], Key=key, Body=raw,
                     ContentType="application/octet-stream")

    _record_liveness(b.header.device_id, b.header.batch_start_us, key)
    return _resp(200, f"stored {key}")


def _quarantine(raw: bytes, auth_device: str, reason: str):
    now_us = int(time.time() * 1e6)
    digest = hashlib.sha256(raw).hexdigest()
    key = s3keys.bad_key(auth_device, now_us, digest)
    print(f"quarantine {key}: {reason}")
    _s3().put_object(Bucket=os.environ["ELBZ_BUCKET"], Key=key, Body=raw,
                     ContentType="application/octet-stream")
    # **200 を返す。** デバイスにとってこのバッチは「送り終えた」で正しい。
    # 送り直させても同じ結果にしかならず、後続の正常なバッチが待たされるだけだ。
    return _resp(200, f"quarantined {key}")


def _record_liveness(device_id: int, batch_start_us: int, key: str) -> None:
    """生存台帳を更新する。**主経路ではない。**

    失敗してもバッチ保存自体は成功扱いにする（デバイスに無駄な再送をさせない）。
    Namazu の判断をそのまま踏襲している。

    テーブル未設定なら黙って何もしない。watchdog を立てるまでは台帳の置き場が
    無く、毎バッチ例外を吐かせても雑音にしかならない。
    """
    if not os.environ.get("NAMZ_DEVICES_TABLE"):
        return
    try:
        devices.record_batch(device_id, batch_start_us,
                             int(time.time() * 1e6), last_batch_key=key)
    except Exception as e:  # noqa: BLE001
        print(f"devices.record_batch failed: {e!r}")
