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
| `NAMZ_DEVICES_TABLE` | `batch_uplink.devices`・`ota_target` | 生存台帳兼pull型OTA配信対象。**未設定なら台帳を書かず、OTAヘッダも返さない** |

## pull型OTA（→ docs/ota.md）

配信対象バージョンは`NAMZ_DEVICES_TABLE`(DynamoDB)の`pending_ota_version`属性に
持つ。`tools/request_ota.py`が直接書き込む——`ELBZ_BUCKET`同様のterraform変数
ではなく、配信のたびにterraform applyを要求しない設計にした(→ docs/ota.md)。
値が立っていればバッチPOST成功のたびに`X-Elbz-Ota-Version`レスポンスヘッダとして
便乗させる。一回性ではない——ファームのビルドバージョンと一致するまで返し続ける
（デバイス側の自然なリトライ機構になる）。一致を検出したら(`ota_target.reached_target`)
このingestが自分で`pending_ota_version`を解放する。

ファーム側は毎バッチ`X-Elbz-Fw-Version`/`X-Elbz-Heap-Free`/`X-Elbz-Uptime-Us`
ヘッダで現在の版数・空きヒープ・稼働時間を送ってくる。`fw_version`は生存台帳へ
保存する(ダッシュボードの`/devices`表示・OTA達成判定に使う)。heap/uptimeは
台帳スキーマに含めておらずCloudWatchログに出すだけ（運用者がOTAロールアウトを
見守る時の可観測性)。
"""

from __future__ import annotations

import base64
import hashlib
import os
import time

import boto3

from batch_uplink import auth, devices

import ota_target
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


def _resp(code: int, msg: str, extra_headers: dict | None = None):
    headers = {"content-type": "text/plain"}
    if extra_headers:
        headers.update(extra_headers)
    return {"statusCode": code, "headers": headers, "body": msg}


def _log_telemetry(headers: dict, device: str) -> None:
    """ファームが毎バッチ乗せてくる空きヒープ・稼働時間をログへ出す。

    fw_versionは生存台帳(NAMZ_DEVICES_TABLE)へ保存する(_record_liveness)ので
    ここでは出さない。heap/uptimeは台帳スキーマに含めていないので、OTA
    ロールアウトを手元で見守る時の可観測性としてログに出すだけ(→ docs/ota.md)。
    """
    heap = headers.get("x-elbz-heap-free", "")
    uptime = headers.get("x-elbz-uptime-us", "")
    if heap or uptime:
        print(f"telemetry device={device} heap_free={heap} uptime_us={uptime}")


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

    _log_telemetry(headers, device)

    try:
        return _handle_batch(raw, device, headers)
    except Exception as e:  # noqa: BLE001
        print(f"ingest error: {e!r}")
        return _resp(400, f"error: {e}")


def _handle_batch(raw: bytes, auth_device: str, headers: dict):
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

    fw_version = headers.get("x-elbz-fw-version", "")
    _record_liveness(b.header.device_id, b.header.batch_start_us, key, fw_version)
    extra_headers = _ota_response_headers(b.header.device_id)
    return _resp(200, f"stored {key}", extra_headers)


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


def _record_liveness(device_id: int, batch_start_us: int, key: str, fw_version: str) -> None:
    """生存台帳を更新する。**主経路ではない。**

    失敗してもバッチ保存自体は成功扱いにする（デバイスに無駄な再送をさせない）。
    Namazu の判断をそのまま踏襲している。

    テーブル未設定なら黙って何もしない(単体テスト等、DynamoDBに触れない環境向け)。
    """
    if not os.environ.get("NAMZ_DEVICES_TABLE"):
        return
    try:
        devices.record_batch(device_id, batch_start_us,
                             int(time.time() * 1e6), last_batch_key=key,
                             fw_version=fw_version)
    except Exception as e:  # noqa: BLE001
        print(f"devices.record_batch failed: {e!r}")


def _ota_response_headers(device_id: int) -> dict:
    """pull型OTA(→ docs/ota.md)の配信対象バージョンヘッダ。**主経路ではない。**

    `pending_ota_version`が立っていなければ空。ビルドバージョンと一致済み
    (`ota_target.reached_target`)なら、ヘッダは返さずサーバ側の状態を解放する
    ——一致後もヘッダを返し続けると、デバイスは`target == ELBZ_FW_VERSION`の
    早期returnで何もしないので実害は無いが、`pending_ota_version`が残り続けると
    将来watchdogを立てた時に「達成済みなのに停滞」と誤検知する種になる。

    テーブル未設定・読み書き失敗はいずれもバッチ保存自体を失敗にしない
    （_record_livenessと同じ方針）。
    """
    if not os.environ.get("NAMZ_DEVICES_TABLE"):
        return {}
    try:
        item = devices.get_device(device_id)
        if not item:
            return {}
        pending = item.get("pending_ota_version")
        if not pending:
            return {}
        if ota_target.reached_target(item):
            ota_target.clear_ota_target(device_id, str(pending))
            return {}
        return {"X-Elbz-Ota-Version": str(pending)}
    except Exception as e:  # noqa: BLE001
        print(f"ota target check failed: {e!r}")
        return {}
