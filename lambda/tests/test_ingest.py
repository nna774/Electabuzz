"""ingest Lambda のテスト。

**AWS には一切触らない。** S3 クライアントは偽物を差し込み、DynamoDB は
`batch_uplink.devices.record_batch` を差し替える。ここで検証したいのは
「どの入力がどのキーに、どの状態コードで落ちるか」であって boto3 の挙動ではない。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import struct

import pytest

import wire_gridfreq
from conftest import GOLDEN_PATH, load_handler, load_hex

SECRET = "test-secret"
DEVICE = "2"  # golden の device_id と一致させてある
BUCKET = "elbz-test-bucket"


class FakeS3:
    def __init__(self):
        self.puts = []

    def put_object(self, **kw):
        self.puts.append(kw)
        return {}


@pytest.fixture
def golden() -> bytes:
    return load_hex(GOLDEN_PATH)


@pytest.fixture
def h(monkeypatch):
    mod = load_handler("ingest")
    monkeypatch.setenv("ELBZ_BUCKET", BUCKET)
    monkeypatch.setenv("NAMZ_HMAC_SECRET", SECRET)
    monkeypatch.delenv("NAMZ_DEVICES_TABLE", raising=False)
    monkeypatch.setattr(mod, "_S3", FakeS3())
    return mod


def sign(body: bytes, secret: str = SECRET) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def make_event(body: bytes, device: str = DEVICE, signature: str | None = None):
    """Function URL (payload v2.0) のイベント。

    **バイナリ本文は必ず base64 で来る。** `application/octet-stream` に対して
    AWS が `isBase64Encoded=true` を立てるので、そちらを既定にする。
    """
    return {
        "rawPath": "/",
        "headers": {
            "X-Namz-Device": device,
            "X-Namz-Signature": sign(body) if signature is None else signature,
        },
        "body": base64.b64encode(body).decode(),
        "isBase64Encoded": True,
    }


def corrupt_payload(raw: bytes) -> bytes:
    """CRC を合わなくする。ヘッダは触らないのでパース自体は進む。"""
    b = bytearray(raw)
    b[wire_gridfreq.HEADER_SIZE] ^= 0xFF
    return bytes(b)


def with_power_fail(raw: bytes) -> bytes:
    """flags(offset 52, u16 LE)のpower_failビットを立てる。

    crc32はrecords()部分だけが対象でヘッダは含まれない(→ docs/wire-format.md)ので、
    ヘッダのflagsを書き換えてもCRCは壊れない。"""
    b = bytearray(raw)
    b[52] |= int(wire_gridfreq.BatchFlag.POWER_FAIL)
    return bytes(b)


# --- 正常系 -------------------------------------------------------------

def test_stores_under_series_prefix(h, golden):
    r = h.handler(make_event(golden), None)
    assert r["statusCode"] == 200
    put, = h._S3.puts
    assert put["Bucket"] == BUCKET
    # 2025-06-15T15:06:40.123456Z。**series/ であること自体が要件**
    # （raw/ は 90日 expire の prefix だ）。→ lambda/s3keys.py
    assert put["Key"] == "series/2025/06/15/15/0002-00001750000000123456.bin"
    assert put["Body"] == golden
    assert put["ContentType"] == "application/octet-stream"


def test_is_idempotent(h, golden):
    h.handler(make_event(golden), None)
    h.handler(make_event(golden), None)
    keys = {p["Key"] for p in h._S3.puts}
    assert len(h._S3.puts) == 2 and len(keys) == 1


def test_accepts_plain_text_body(h):
    """base64 でない経路でも署名検証まで到達する（本文が ASCII のときだけ）。

    `isBase64Encoded=false` の本文は UTF-8 で decode されるので、GFRQ の
    バイナリはここを通れない。**通れないこと自体は害にならない** — 署名が
    合わなくなって 401 で落ちるので、壊れたバイト列が黙って保存されることはない。
    """
    raw = b"not a gfrq batch"
    ev = make_event(raw)
    ev["body"] = raw.decode()
    ev["isBase64Encoded"] = False
    r = h.handler(ev, None)
    assert r["statusCode"] == 400  # 認証は通り、形式で落ちる
    assert "too short for header" in r["body"]


# --- 認証 ---------------------------------------------------------------

def test_rejects_bad_signature(h, golden):
    r = h.handler(make_event(golden, signature="00" * 32), None)
    assert r["statusCode"] == 401
    assert h._S3.puts == []


def test_rejects_missing_signature(h, golden):
    r = h.handler(make_event(golden, signature=""), None)
    assert r["statusCode"] == 401


def test_rejects_signature_of_other_body(h, golden):
    """署名は本文に対して検証される（ヘッダだけ流用した再送は通らない）。"""
    r = h.handler(make_event(golden, signature=sign(golden[:64])), None)
    assert r["statusCode"] == 401


def test_rejects_device_impersonation(h, golden, monkeypatch):
    """**別デバイスの騙りを塞ぐ。ここが device_id 照合の存在意義だ。**

    デバイス1が自分の正規の鍵で署名し、本文だけデバイス2のものを送る。
    署名検証は通ってしまうので、本文との照合だけが最後の砦になる。
    """
    monkeypatch.setenv("NAMZ_HMAC_SECRET_1", "device-1-secret")
    ev = make_event(golden, device="1")
    ev["headers"]["X-Namz-Signature"] = sign(golden, "device-1-secret")
    r = h.handler(ev, None)
    assert r["statusCode"] == 403
    assert "device mismatch" in r["body"]
    assert h._S3.puts == []


def test_rejects_device_mismatch_with_shared_secret(h, golden):
    """共有鍵運用（NAMZ_HMAC_SECRET だけ）でも同じく本文照合で落ちる。"""
    r = h.handler(make_event(golden, device="9"), None)
    assert r["statusCode"] == 403
    assert h._S3.puts == []


def test_per_device_secret_is_preferred(h, golden, monkeypatch):
    monkeypatch.setenv("NAMZ_HMAC_SECRET_2", "device-2-secret")
    ev = make_event(golden)
    ev["headers"]["X-Namz-Signature"] = sign(golden, "device-2-secret")
    assert h.handler(ev, None)["statusCode"] == 200


# --- 読めない / 壊れている ----------------------------------------------

def test_rejects_namz_batch_loudly(h):
    """地震計のバッチが届いたら 400 で落とす。**黙って保存しない。**"""
    raw = struct.pack("<I", wire_gridfreq.NAMZ_MAGIC) + bytes(60)
    r = h.handler(make_event(raw), None)
    assert r["statusCode"] == 400
    assert "地震計" in r["body"]
    assert h._S3.puts == []


def test_rejects_garbage(h):
    r = h.handler(make_event(b"hello"), None)
    assert r["statusCode"] == 400
    assert h._S3.puts == []


def test_quarantines_crc_mismatch(h, golden):
    """CRC 不一致は 200 + 隔離。**再送させても同じ結果にしかならない。**"""
    bad = corrupt_payload(golden)
    r = h.handler(make_event(bad), None)
    assert r["statusCode"] == 200
    put, = h._S3.puts
    assert put["Key"].startswith("bad/")
    assert put["Body"] == bad
    assert "series/" not in put["Key"]


def test_quarantine_key_folds_identical_resends(h, golden, monkeypatch):
    """同じ壊れ方の再送は同じキーに畳む（受信時刻が同じなら）。"""
    monkeypatch.setattr(h.time, "time", lambda: 1750000000.5)
    bad = corrupt_payload(golden)
    h.handler(make_event(bad), None)
    h.handler(make_event(bad), None)
    assert len({p["Key"] for p in h._S3.puts}) == 1


def test_quarantine_key_uses_authenticated_device(h, golden, monkeypatch):
    """壊れたバッチの device_id は信用しない。署名に通った名乗りを使う。"""
    monkeypatch.setenv("NAMZ_HMAC_SECRET_2", SECRET)
    bad = corrupt_payload(golden)
    h.handler(make_event(bad), None)
    assert "/2-" in h._S3.puts[0]["Key"]


# --- 生存台帳（主経路ではない） -----------------------------------------

def test_skips_ledger_when_table_unset(h, golden, monkeypatch):
    called = []
    monkeypatch.setattr(h.devices, "record_batch", lambda *a, **k: called.append(a))
    assert h.handler(make_event(golden), None)["statusCode"] == 200
    assert called == []


def test_records_ledger_when_table_set(h, golden, monkeypatch):
    monkeypatch.setenv("NAMZ_DEVICES_TABLE", "electabuzz-devices")
    called = []
    monkeypatch.setattr(h.devices, "record_batch", lambda *a, **k: called.append((a, k)))
    assert h.handler(make_event(golden), None)["statusCode"] == 200
    (args, kw), = called
    assert args[0] == 2 and args[1] == 1750000000123456
    assert kw["last_batch_key"] == "series/2025/06/15/15/0002-00001750000000123456.bin"


def test_ledger_failure_does_not_fail_the_batch(h, golden, monkeypatch):
    """台帳が落ちてもバッチは保存済み。**デバイスに無駄な再送をさせない。**"""
    monkeypatch.setenv("NAMZ_DEVICES_TABLE", "electabuzz-devices")

    def boom(*a, **k):
        raise RuntimeError("dynamodb down")

    monkeypatch.setattr(h.devices, "record_batch", boom)
    r = h.handler(make_event(golden), None)
    assert r["statusCode"] == 200
    assert len(h._S3.puts) == 1


# --- pull型OTA(→ docs/ota.md)。配信対象は NAMZ_DEVICES_TABLE(DynamoDB)の
# pending_ota_version 属性に持つ。devices.get_device/record_batch と
# ota_target.clear_ota_target を差し替えてDynamoDBに触れずに検証する ------

def test_ota_header_absent_when_table_unset(h, golden):
    """既定(テーブル未設定)では何も配信しない。既存デバイスの挙動を変えない。"""
    r = h.handler(make_event(golden), None)
    assert r["statusCode"] == 200
    assert "X-Elbz-Ota-Version" not in r["headers"]


def test_ota_header_absent_when_no_pending(h, golden, monkeypatch):
    monkeypatch.setenv("NAMZ_DEVICES_TABLE", "electabuzz-devices")
    monkeypatch.setattr(h.devices, "record_batch", lambda *a, **k: None)
    monkeypatch.setattr(h.devices, "get_device", lambda did: {"device_id": did})
    r = h.handler(make_event(golden), None)
    assert r["statusCode"] == 200
    assert "X-Elbz-Ota-Version" not in r["headers"]


def test_ota_header_present_when_pending_and_not_reached(h, golden, monkeypatch):
    """設定されていれば、成功したバッチ応答のたびに便乗させる(一回性ではない)。"""
    monkeypatch.setenv("NAMZ_DEVICES_TABLE", "electabuzz-devices")
    monkeypatch.setattr(h.devices, "record_batch", lambda *a, **k: None)
    monkeypatch.setattr(
        h.devices, "get_device",
        lambda did: {"device_id": did, "pending_ota_version": "abc1234", "fw_version": "old111"})
    cleared = []
    monkeypatch.setattr(h.ota_target, "clear_ota_target", lambda *a: cleared.append(a))
    r = h.handler(make_event(golden), None)
    assert r["statusCode"] == 200
    assert r["headers"]["X-Elbz-Ota-Version"] == "abc1234"
    assert cleared == []
    # 消費しない: もう一度送っても同じ値が返り続ける。
    r2 = h.handler(make_event(golden), None)
    assert r2["headers"]["X-Elbz-Ota-Version"] == "abc1234"


def test_ota_clears_target_when_reached(h, golden, monkeypatch):
    """ビルドバージョンと一致したら、ヘッダを返さずサーバ側の状態を解放する。"""
    monkeypatch.setenv("NAMZ_DEVICES_TABLE", "electabuzz-devices")
    monkeypatch.setattr(h.devices, "record_batch", lambda *a, **k: None)
    # デバイスが乗せてきたfw_versionがpending_ota_versionと一致した状態
    # (record_batchが直前に書いた後の get_device 読み戻し、を模している)。
    monkeypatch.setattr(
        h.devices, "get_device",
        lambda did: {"device_id": did, "pending_ota_version": "abc1234", "fw_version": "abc1234"})
    cleared = []
    monkeypatch.setattr(h.ota_target, "clear_ota_target", lambda *a: cleared.append(a))
    r = h.handler(make_event(golden), None)
    assert r["statusCode"] == 200
    assert "X-Elbz-Ota-Version" not in r["headers"]
    assert cleared == [(2, "abc1234")]  # golden の device_id=2


def test_ota_header_absent_on_quarantine(h, golden, monkeypatch):
    """隔離(CRC不一致)経路はOTA対象外——2xxだが更新許可を出さない。"""
    monkeypatch.setenv("NAMZ_DEVICES_TABLE", "electabuzz-devices")
    monkeypatch.setattr(
        h.devices, "get_device",
        lambda did: {"device_id": did, "pending_ota_version": "abc1234"})
    bad = corrupt_payload(golden)
    r = h.handler(make_event(bad), None)
    assert r["statusCode"] == 200
    assert "X-Elbz-Ota-Version" not in r["headers"]


def test_record_batch_receives_fw_version_header(h, golden, monkeypatch):
    """ファームの X-Elbz-Fw-Version ヘッダが生存台帳の fw_version として渡る。"""
    monkeypatch.setenv("NAMZ_DEVICES_TABLE", "electabuzz-devices")
    calls = []
    monkeypatch.setattr(h.devices, "record_batch", lambda *a, **k: calls.append(k))
    ev = make_event(golden)
    ev["headers"]["X-Elbz-Fw-Version"] = "abc1234"
    assert h.handler(ev, None)["statusCode"] == 200
    assert calls[0]["fw_version"] == "abc1234"


# --- watchdog向けの状態記録(→ docs/cloud.md「watchdog」。いずれも主経路ではない) ----

def test_power_fail_flag_is_recorded_when_table_set(h, golden, monkeypatch):
    monkeypatch.setenv("NAMZ_DEVICES_TABLE", "electabuzz-devices")
    monkeypatch.setattr(h.devices, "record_batch", lambda *a, **k: None)
    monkeypatch.setattr(h.devices, "get_device", lambda did: None)
    calls = []
    monkeypatch.setattr(h.power_fail_watch, "record", lambda *a: calls.append(a))
    assert h.handler(make_event(with_power_fail(golden)), None)["statusCode"] == 200
    assert calls == [(2, True)]


def test_power_fail_false_is_recorded_when_flag_absent(h, golden, monkeypatch):
    """golden fixtureのflagsはpps_locked|gnss_fixのみでpower_failは立っていない。"""
    monkeypatch.setenv("NAMZ_DEVICES_TABLE", "electabuzz-devices")
    monkeypatch.setattr(h.devices, "record_batch", lambda *a, **k: None)
    monkeypatch.setattr(h.devices, "get_device", lambda did: None)
    calls = []
    monkeypatch.setattr(h.power_fail_watch, "record", lambda *a: calls.append(a))
    assert h.handler(make_event(golden), None)["statusCode"] == 200
    assert calls == [(2, False)]


def test_power_fail_skipped_when_table_unset(h, golden, monkeypatch):
    calls = []
    monkeypatch.setattr(h.power_fail_watch, "record", lambda *a: calls.append(a))
    assert h.handler(make_event(golden), None)["statusCode"] == 200
    assert calls == []


def test_reboot_recorded_when_uptime_header_present(h, golden, monkeypatch):
    monkeypatch.setenv("NAMZ_DEVICES_TABLE", "electabuzz-devices")
    monkeypatch.setattr(h.devices, "record_batch", lambda *a, **k: None)
    monkeypatch.setattr(h.devices, "get_device", lambda did: {"device_id": did})
    calls = []
    monkeypatch.setattr(h.reboot_watch, "record_boot_epoch", lambda *a: calls.append(a))
    ev = make_event(golden)
    ev["headers"]["X-Elbz-Uptime-Us"] = "100000"
    assert h.handler(ev, None)["statusCode"] == 200
    # golden の batch_start_us = 1750000000123456
    assert calls == [(2, 1750000000123456 - 100000)]


def test_reboot_not_updated_within_drift_threshold(h, golden, monkeypatch):
    """前回値からのズレがドリフト許容(±2分)以内なら再起動とみなさない。"""
    monkeypatch.setenv("NAMZ_DEVICES_TABLE", "electabuzz-devices")
    monkeypatch.setattr(h.devices, "record_batch", lambda *a, **k: None)
    prev = 1750000000123456 - 100000
    monkeypatch.setattr(h.devices, "get_device", lambda did: {"device_id": did, "boot_epoch_us": prev})
    calls = []
    monkeypatch.setattr(h.reboot_watch, "record_boot_epoch", lambda *a: calls.append(a))
    ev = make_event(golden)
    ev["headers"]["X-Elbz-Uptime-Us"] = "100000"
    assert h.handler(ev, None)["statusCode"] == 200
    assert calls == []


def test_reboot_skipped_without_uptime_header(h, golden, monkeypatch):
    monkeypatch.setenv("NAMZ_DEVICES_TABLE", "electabuzz-devices")
    monkeypatch.setattr(h.devices, "record_batch", lambda *a, **k: None)
    calls = []
    monkeypatch.setattr(h.reboot_watch, "record_boot_epoch", lambda *a: calls.append(a))
    assert h.handler(make_event(golden), None)["statusCode"] == 200
    assert calls == []


def test_mute_is_cleared_on_every_batch(h, golden, monkeypatch):
    monkeypatch.setenv("NAMZ_DEVICES_TABLE", "electabuzz-devices")
    monkeypatch.setattr(h.devices, "record_batch", lambda *a, **k: None)
    monkeypatch.setattr(h.devices, "get_device", lambda did: None)
    calls = []
    monkeypatch.setattr(h.watchdog_mute, "clear_mute", lambda did: calls.append(did))
    assert h.handler(make_event(golden), None)["statusCode"] == 200
    assert calls == [2]


def test_mute_clear_skipped_when_table_unset(h, golden, monkeypatch):
    calls = []
    monkeypatch.setattr(h.watchdog_mute, "clear_mute", lambda did: calls.append(did))
    assert h.handler(make_event(golden), None)["statusCode"] == 200
    assert calls == []


def test_telemetry_headers_are_logged_not_stored(h, golden, capsys):
    """ファームの空きヒープ・稼働時間ヘッダはCloudWatchログへ出すだけ。

    fw_versionは生存台帳(NAMZ_DEVICES_TABLE)へ保存するのでここには出さない
    (→ 上のtest_record_batch_receives_fw_version_header、docs/ota.md)。
    """
    ev = make_event(golden)
    ev["headers"]["X-Elbz-Heap-Free"] = "123456"
    ev["headers"]["X-Elbz-Uptime-Us"] = "987654321"
    r = h.handler(ev, None)
    assert r["statusCode"] == 200
    out = capsys.readouterr().out
    assert "heap_free=123456" in out
    assert "uptime_us=987654321" in out
