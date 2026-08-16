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
         *, flags: int = 0, rate_mhz: int = 1000, source: int = 0, fs_uhz: int = 48_000_000_000):
    data = build(records=records, start_us=batch_start_us, device_id=device_id,
                 session_id=session_id, rate_mhz=rate_mhz, flags=flags, source=source,
                 fs_uhz=fs_uhz)
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
    assert body["v_rms_mv"] == [10_500, 10_500, 10_500]  # freqと違い1件目も欠けない
    assert body["latest"]["v_rms_mv"] == 10_500


def test_v_rms_mv_survives_discontinuity_flag(h):
    # v_rms_mvはレコード単体の瞬時値で、freq_hzのような隣接点間の差分計算に
    # 依存しない。DISCONTINUITYでfreqがNone落ちしても値は抑制しない。
    recs = [(cycles(50.0, 0), 8_500, 0), (cycles(50.0, 1), 8_520, 0),
            (cycles(50.0, 2), 8_490, 0)]
    seed(h, device_id=1, batch_start_us=BASE_US, session_id=1, records=recs,
         flags=1 << 2)  # GfrqFlagDiscontinuity

    resp = h.handler(make_event("/recent", {"minutes": "1", "start": str(BASE_US + 5_000_000)}), None)
    import json
    body = json.loads(resp["body"])
    assert all(f is None for f in body["freq_hz"])
    assert body["v_rms_mv"] == [8_500, 8_520, 8_490]


def test_continuous_breaks_on_session_change_but_not_discontinuity_flag(h):
    # v_rms_mv用の「線をつないでよいか」判定(continuous)は、freq_hzのNoneとは
    # 別基準。DISCONTINUITYが立ったバッチでも実測dtが想定間隔どおりなら
    # つなぐ(freqと違い値自体を抑制する理由が無いのと同じ理由)が、
    # session_idが変わる(再起動・実データ欠測)点ではつながない。
    recs1 = [(cycles(50.0, i), 8_500, 0) for i in range(2)]
    recs2 = [(cycles(50.0, i), 8_500, 0) for i in range(3)]  # DISCONTINUITY立ち、同一セッション
    recs3 = [(cycles(50.0, i), 8_500, 0) for i in range(2)]  # 新セッション(再起動)
    seed(h, device_id=1, batch_start_us=BASE_US, session_id=1, records=recs1)
    seed(h, device_id=1, batch_start_us=BASE_US + 2_000_000, session_id=1, records=recs2,
         flags=1 << 2)  # GfrqFlagDiscontinuity
    seed(h, device_id=1, batch_start_us=BASE_US + 5_000_000, session_id=2, records=recs3)

    resp = h.handler(make_event("/recent", {"minutes": "1", "start": str(BASE_US + 10_000_000)}), None)
    import json
    body = json.loads(resp["body"])
    assert body["n"] == 7
    assert body["continuous"][0] is False  # 系列先頭
    assert body["continuous"][1] is True
    assert body["continuous"][2] is True  # DISCONTINUITY境界だが実測dtは想定どおり→つなぐ
    assert body["continuous"][3] is True
    assert body["continuous"][4] is True
    assert body["continuous"][5] is False  # セッション境界→つながない
    assert body["continuous"][6] is True
    # v_rms_mv自体はDISCONTINUITYでもセッション境界でも欠けない。
    assert body["v_rms_mv"] == [8_500] * 7


def test_continuous_breaks_on_large_time_gap_within_session(h):
    # 同一セッションでも、実測dtが想定間隔の2倍を超えたら(オフライン期間等)つながない。
    recs1 = [(cycles(50.0, i), 8_500, 0) for i in range(2)]
    recs2 = [(cycles(50.0, i), 8_500, 0) for i in range(2)]
    seed(h, device_id=1, batch_start_us=BASE_US, session_id=1, records=recs1)
    # 本来2秒後のはずが、10秒空いて再開した想定。
    seed(h, device_id=1, batch_start_us=BASE_US + 10_000_000, session_id=1, records=recs2)

    resp = h.handler(make_event("/recent", {"minutes": "1", "start": str(BASE_US + 15_000_000)}), None)
    import json
    body = json.loads(resp["body"])
    assert body["n"] == 4
    assert body["continuous"][2] is False  # 大きな時間ギャップ→つながない
    assert body["v_rms_mv"] == [8_500] * 4


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


def test_batch_boundary_timestamp_jitter_does_not_distort_frequency(h):
    # バッチ起点(batch_start_us)にNTP観測反映によるジッタ(数ms)が乗っても、
    # 除算にはrecord_rate_mhz由来の理論値を使うので周波数は歪まない
    # (→ docs/log/2026-08-09-batch-boundary-jump-regression-cause.md)。
    # 実測dtを使っていた旧実装なら、この2msのジッタだけで約50.1Hzにズレていた
    # (実データでは最大244mHz級のズレが261境界中16件で観測された)。
    recs1 = [(cycles(50.0, i), 0, 0) for i in range(3)]
    recs2 = [(cycles(50.0, i), 0, 0) for i in range(3, 5)]
    seed(h, device_id=1, batch_start_us=BASE_US, session_id=7, records=recs1)
    # 本来3.000秒後のはずのバッチ起点が、NTP再同期の影響で2ms早く記録された想定。
    jittered_start_us = BASE_US + 3_000_000 - 2_000
    seed(h, device_id=1, batch_start_us=jittered_start_us, session_id=7, records=recs2)

    resp = h.handler(make_event("/recent", {"minutes": "1", "start": str(BASE_US + 10_000_000)}), None)
    import json
    body = json.loads(resp["body"])
    assert body["n"] == 5
    assert body["freq_hz"][3] == pytest.approx(50.0)  # ジッタに引きずられず正確
    assert body["freq_hz"][4] == pytest.approx(50.0)
    # t_usの方はbatch_start_usベースのままで、ジッタを隠さず反映する
    # (時間軸の表示・時刻偏差の計算にはこちらを使うため)。
    assert body["t_us"][3] == jittered_start_us


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


def test_nominal_without_lock_has_no_corrected_freq(h):
    # ロック(規正済みバッチ)がまだ来ていないNOMINAL区間には補正値を出さない。
    recs = [(cycles(50.0, i), 0, 0) for i in range(3)]
    seed(h, device_id=1, batch_start_us=BASE_US, session_id=9, records=recs, source=0)

    resp = h.handler(make_event("/recent", {"minutes": "1", "start": str(BASE_US + 5_000_000)}), None)
    import json
    body = json.loads(resp["body"])
    assert body["timebase_source"] == ["NOMINAL", "NOMINAL", "NOMINAL"]
    assert all(f is None for f in body["freq_hz_corrected"])


def test_nominal_gets_corrected_once_session_locks(h):
    # 同一セッション: 先にNOMINALバッチ、続いてNTP(ロック)バッチ。
    # ロック後、NOMINALレコードだけにfreq_hz * (locked_fs/nominal_fs) が付く。
    nominal_fs = 48_000_000_000
    locked_fs = 48_004_800_000  # +100ppm
    recs_nominal = [(cycles(50.0, i), 0, 0) for i in range(3)]
    recs_locked = [(cycles(50.0, i), 0, 0) for i in range(3, 6)]
    seed(h, device_id=1, batch_start_us=BASE_US, session_id=42, records=recs_nominal,
         source=0, fs_uhz=nominal_fs)
    seed(h, device_id=1, batch_start_us=BASE_US + 3_000_000, session_id=42, records=recs_locked,
         source=1, fs_uhz=locked_fs)

    resp = h.handler(make_event("/recent", {"minutes": "1", "start": str(BASE_US + 10_000_000)}), None)
    import json
    body = json.loads(resp["body"])
    assert body["timebase_source"] == ["NOMINAL"] * 3 + ["NTP"] * 3

    factor = locked_fs / nominal_fs
    # NOMINAL区間: 先頭は直前点が無いのでfreqそのものがNone。以降は補正が付く。
    assert body["freq_hz_corrected"][0] is None
    assert body["freq_hz_corrected"][1] == pytest.approx(50.0 * factor)
    assert body["freq_hz_corrected"][2] == pytest.approx(50.0 * factor)
    # NTP区間はすでに規正済みなので補正値を出さない(Noneのまま)。
    assert body["freq_hz_corrected"][3] is None
    assert body["freq_hz_corrected"][4] is None
    assert body["freq_hz_corrected"][5] is None
    # 生のfreq_hzは補正の有無に関わらずこれまでどおり出る。
    assert body["freq_hz"][1] == pytest.approx(50.0)
    assert body["freq_hz"][4] == pytest.approx(50.0)


def test_minutes_is_clamped(h):
    # 巨大値・負値・非数値のいずれも [0.1, 30] にクランプされ、例外にならない。
    for raw in ("99999", "-5", "not-a-number"):
        resp = h.handler(make_event("/recent", {"minutes": raw, "start": str(BASE_US)}), None)
        assert resp["statusCode"] == 200


# --- /devices(生存台帳。→ docs/ota.md) -------------------------------------

def test_devices_empty_when_table_unset(h):
    """テーブル未設定(NAMZ_DEVICES_TABLE無し)なら空配列(まだ立てていない環境向け)。"""
    resp = h.handler(make_event("/devices"), None)
    assert resp["statusCode"] == 200
    import json
    assert json.loads(resp["body"]) == {"devices": []}


def test_devices_lists_from_table(h, monkeypatch):
    monkeypatch.setenv("NAMZ_DEVICES_TABLE", "electabuzz-devices")
    monkeypatch.setattr(h.devices, "list_devices", lambda: [
        {"device_id": 1, "fw_version": "351cd38", "last_ingest_at_us": 1_750_000_000_000_000,
         "last_batch_start_us": 1_749_999_970_000_000, "batches_total": 42,
         "pending_ota_version": "abc1234"},
    ])
    resp = h.handler(make_event("/devices"), None)
    assert resp["statusCode"] == 200
    import json
    body = json.loads(resp["body"])
    d, = body["devices"]
    assert d["device_id"] == 1
    assert d["fw_version"] == "351cd38"
    assert d["last_ingest_at_us"] == 1_750_000_000_000_000
    assert d["batches_total"] == 42
    assert d["pending_ota_version"] == "abc1234"
    assert d["staleness_s"] is not None


def test_devices_omits_optional_fields_when_absent(h, monkeypatch):
    """新規デバイス(初回バッチ直後)はfw_version/pending_ota_versionが無い状態もある。"""
    monkeypatch.setenv("NAMZ_DEVICES_TABLE", "electabuzz-devices")
    monkeypatch.setattr(h.devices, "list_devices", lambda: [
        {"device_id": 1, "last_ingest_at_us": 1_750_000_000_000_000},
    ])
    resp = h.handler(make_event("/devices"), None)
    import json
    d, = json.loads(resp["body"])["devices"]
    assert d["fw_version"] is None
    assert d["pending_ota_version"] is None
    assert d["last_batch_start_us"] is None


# --- /events(detectが確定したイベント。→ lambda/detect/handler.py) ---------

def test_events_empty_when_table_unset(h):
    """テーブル未設定(NAMZ_EVENTS_TABLE無し)なら空配列(まだ立てていない環境向け)。"""
    resp = h.handler(make_event("/events"), None)
    assert resp["statusCode"] == 200
    import json
    assert json.loads(resp["body"]) == {"events": []}


def test_events_lists_from_table(h, monkeypatch):
    from decimal import Decimal
    monkeypatch.setenv("NAMZ_EVENTS_TABLE", "electabuzz-events")
    monkeypatch.setattr(h.grid_events, "recent_events", lambda limit: [
        {"event_id": "0001-freq_deviation-100", "device_id": 1, "event_type": "freq_deviation",
         "onset_us": 1_750_000_000_000_000, "last_us": 1_750_000_003_000_000,
         "peak_value": Decimal("0.3")},
    ])
    resp = h.handler(make_event("/events"), None)
    assert resp["statusCode"] == 200
    import json
    e, = json.loads(resp["body"])["events"]
    assert e["device_id"] == 1
    assert e["event_type"] == "freq_deviation"
    assert e["peak_value"] == 0.3


def test_events_limit_is_clamped(h, monkeypatch):
    monkeypatch.setenv("NAMZ_EVENTS_TABLE", "electabuzz-events")
    seen = {}

    def _fake_recent(limit):
        seen["limit"] = limit
        return []

    monkeypatch.setattr(h.grid_events, "recent_events", _fake_recent)
    for raw, expect in (("99999", h.MAX_EVENTS_LIMIT), ("-5", 1), ("not-a-number", 50)):
        h.handler(make_event("/events", {"limit": raw}), None)
        assert seen["limit"] == expect
