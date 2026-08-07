"""api Lambda(`/recent`)のテスト。AWSには一切触らない。"""

from __future__ import annotations

import io

import pytest
from conftest import load_handler
from test_wire_gridfreq import build

import s3keys

BUCKET = "elbz-test-bucket"


class FakeS3:
    """`put_object`で種を撒き、`list_objects_v2`/`get_object`で読ませる最小限の偽物。"""

    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def put_object(self, Bucket, Key, Body, **kw):  # noqa: N803
        self.objects[Key] = Body

    def get_object(self, Bucket, Key):  # noqa: N803
        return {"Body": io.BytesIO(self.objects[Key])}

    def list_objects_v2(self, Bucket, Prefix="", ContinuationToken=None):  # noqa: N803
        keys = sorted(k for k in self.objects if k.startswith(Prefix))
        return {"Contents": [{"Key": k} for k in keys], "IsTruncated": False}


@pytest.fixture
def h(monkeypatch):
    mod = load_handler("api")
    monkeypatch.setenv("ELBZ_BUCKET", BUCKET)
    monkeypatch.setattr(mod, "_S3", FakeS3())
    return mod


def seed(h, device_id: int, batch_start_us: int, session_id: int, records,
         *, flags: int = 0, rate_mhz: int = 1000):
    data = build(records=records, start_us=batch_start_us, device_id=device_id,
                 session_id=session_id, rate_mhz=rate_mhz, flags=flags)
    key = s3keys.series_key(device_id, batch_start_us)
    h._s3().put_object(Bucket=BUCKET, Key=key, Body=data)


def make_event(path: str, params: dict | None = None, method: str = "GET"):
    return {
        "rawPath": path,
        "requestContext": {"http": {"method": method}},
        "queryStringParameters": params,
    }


BASE_US = 1_750_000_000_000_000
Q16 = 1 << 16


def cycles(hz: float, n_seconds: float) -> int:
    return round(hz * n_seconds * Q16)


def test_options_is_204(h):
    resp = h.handler(make_event("/", method="OPTIONS"), None)
    assert resp["statusCode"] == 204


def test_unknown_path_is_404(h):
    resp = h.handler(make_event("/nope"), None)
    assert resp["statusCode"] == 404


def test_empty_range_returns_empty_series(h):
    resp = h.handler(make_event("/recent", {"minutes": "5", "start": str(BASE_US)}), None)
    assert resp["statusCode"] == 200
    import json
    body = json.loads(resp["body"])
    assert body["n"] == 0
    assert body["latest"] is None


def test_steady_50hz_within_one_batch(h):
    # 1Hzレコード、ぴったり公称50Hzで3件(=2区間ぶん)。1件目は「直前」が無いのでfreqはNone。
    recs = [(cycles(50.0, i), 10_500, 0) for i in range(3)]
    seed(h, device_id=1, batch_start_us=BASE_US, session_id=1, records=recs)

    resp = h.handler(make_event("/recent", {"minutes": "1", "start": str(BASE_US + 5_000_000)}), None)
    import json
    body = json.loads(resp["body"])
    assert body["n"] == 3
    assert body["freq_hz"][0] is None  # 系列先頭は直前が無い
    assert body["freq_hz"][1] == pytest.approx(50.0)
    assert body["freq_hz"][2] == pytest.approx(50.0)
    assert body["latest"]["freq_hz"] == pytest.approx(50.0)
    assert body["latest"]["timebase_source"] == "NOMINAL"


def test_frequency_continues_across_batch_boundary(h):
    # バッチ1: 3件(t=0,1,2s)。バッチ2: 同一セッションで2件(t=3,4s)。境界も50Hzのまま。
    recs1 = [(cycles(50.0, i), 0, 0) for i in range(3)]
    recs2 = [(cycles(50.0, i), 0, 0) for i in range(3, 5)]
    seed(h, device_id=1, batch_start_us=BASE_US, session_id=7, records=recs1)
    seed(h, device_id=1, batch_start_us=BASE_US + 3_000_000, session_id=7, records=recs2)

    resp = h.handler(make_event("/recent", {"minutes": "1", "start": str(BASE_US + 10_000_000)}), None)
    import json
    body = json.loads(resp["body"])
    assert body["n"] == 5
    assert body["freq_hz"][3] == pytest.approx(50.0)  # バッチをまたいだ最初の点
    assert body["freq_hz"][4] == pytest.approx(50.0)


def test_session_change_breaks_continuity(h):
    # 再起動(session_idが変わる)をまたぐと、その点のfreqはNoneになる。
    recs1 = [(cycles(50.0, i), 0, 0) for i in range(2)]
    recs2 = [(cycles(50.0, i), 0, 0) for i in range(2)]  # 新セッションはcyclesが0から再開
    seed(h, device_id=1, batch_start_us=BASE_US, session_id=1, records=recs1)
    seed(h, device_id=1, batch_start_us=BASE_US + 2_000_000, session_id=2, records=recs2)

    resp = h.handler(make_event("/recent", {"minutes": "1", "start": str(BASE_US + 10_000_000)}), None)
    import json
    body = json.loads(resp["body"])
    assert body["n"] == 4
    assert body["freq_hz"][2] is None  # セッション境界(直前の点が旧セッション)
    assert body["freq_hz"][3] == pytest.approx(50.0)  # 新セッション内は通常どおり計算できる
    assert body["latest"]["session_id"] == 2


def test_discontinuity_flag_suppresses_frequency_in_batch(h):
    recs = [(cycles(50.0, i), 0, 0) for i in range(3)]
    seed(h, device_id=1, batch_start_us=BASE_US, session_id=1, records=recs,
         flags=1 << 2)  # GfrqFlagDiscontinuity

    resp = h.handler(make_event("/recent", {"minutes": "1", "start": str(BASE_US + 5_000_000)}), None)
    import json
    body = json.loads(resp["body"])
    assert body["n"] == 3
    assert all(f is None for f in body["freq_hz"])


def test_minutes_is_clamped(h):
    # 巨大値・負値・非数値のいずれも [0.1, 30] にクランプされ、例外にならない。
    for raw in ("99999", "-5", "not-a-number"):
        resp = h.handler(make_event("/recent", {"minutes": raw, "start": str(BASE_US)}), None)
        assert resp["statusCode"] == 200
