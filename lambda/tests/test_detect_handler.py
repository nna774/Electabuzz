"""detect Lambda のハンドラレベルテスト。

しきい値判定そのものはgrid_detect.analyzeの純粋関数テストで確認済みなので、
ここでは「配線が正しいか」(S3イベントからkeyを拾い、新規セッションだけ通知するか)
だけを見る。S3・DynamoDBには触れない——`wire_gridfreq.parse`・
`store_gridfreq.list_series_keys_in_range`・`grid_events.record`・`notify.from_env`を
すべて差し替える。
"""

from __future__ import annotations

from conftest import load_handler

from wire_gridfreq import Batch, Header, Record

DEVICE_ID = 1


class FakeNotifier:
    def __init__(self):
        self.calls = []

    def notify(self, title, text, fields=None, **kw):
        self.calls.append({"title": title, "text": text, "fields": fields})


class FakeBody:
    def __init__(self, data: bytes = b""):
        self._data = data

    def read(self) -> bytes:
        return self._data


def _header(**kw):
    base = dict(
        version=1, record_format=0, header_len=64, batch_start_us=0,
        device_id=DEVICE_ID, record_count=3, record_rate_mhz=1000,
        session_id=1, f_nominal_mhz=50_000, fs_measured_uhz=48_000_000_000,
        tb_obs_count=0, tb_residual_ns=0, flags=0, timebase_source=2,
        soc_temp_c=25, crc32=0,
    )
    base.update(kw)
    return Header(**base)


def _batch_with_freq_deviation() -> Batch:
    """3レコード連続で+0.3Hz逸脱するバッチ(hold=3ちょうどで検知される)。"""
    cycles = 0.0
    records = []
    for f in (50.3, 50.3, 50.3):
        cycles += f
        records.append(Record(cycles_q16=int(round(cycles * 65536)), v_rms_mv=10_300, flags=0))
    # samples_from_batchesは最初のレコードの周波数を計算できない(直前の点が無い)ので、
    # 先頭にダミーの1レコードを足して3件の逸脱runを確保する。
    records = [Record(cycles_q16=0, v_rms_mv=10_300, flags=0)] + records
    return Batch(header=_header(record_count=len(records)), records=tuple(records))


def _handler(monkeypatch):
    h = load_handler("detect")
    monkeypatch.setenv("ELBZ_BUCKET", "elbz-test-bucket")
    monkeypatch.setattr(h.s3, "get_object", lambda Bucket, Key: {"Body": FakeBody(b"dummy")})
    monkeypatch.setattr(h.store_gridfreq, "list_series_keys_in_range",
                        lambda s3, bucket, start, end: [])  # 直前バッチ無し
    fake_notifier = FakeNotifier()
    monkeypatch.setattr(h.notify, "from_env", lambda: fake_notifier)
    return h, fake_notifier


def _event(key="series/2026/08/17/00/0001-00000000001000000000.bin"):
    return {"Records": [{"s3": {"object": {"key": key}}}]}


def test_new_detection_notifies_once(monkeypatch):
    h, fake = _handler(monkeypatch)
    monkeypatch.setattr(h.wire_gridfreq, "parse", lambda body: _batch_with_freq_deviation())
    recorded = []
    monkeypatch.setattr(h.grid_events, "record",
                        lambda device_id, event_type, onset, last, peak: (
                            recorded.append((device_id, event_type, onset, last, peak)),
                            (f"{device_id:04d}-{event_type}-0", True))[1])

    h.handler(_event(), None)

    assert len(fake.calls) == 1
    assert fake.calls[0]["title"] == "周波数逸脱を検知"
    assert recorded and recorded[0][1] == "freq_deviation"


def test_continuing_session_does_not_renotify(monkeypatch):
    h, fake = _handler(monkeypatch)
    monkeypatch.setattr(h.wire_gridfreq, "parse", lambda body: _batch_with_freq_deviation())
    monkeypatch.setattr(h.grid_events, "record",
                        lambda device_id, event_type, onset, last, peak: (
                            f"{device_id:04d}-{event_type}-0", False))  # 既存セッションへの延長

    h.handler(_event(), None)

    assert fake.calls == []


def test_non_series_key_is_ignored(monkeypatch):
    h, fake = _handler(monkeypatch)
    called = []
    monkeypatch.setattr(h.wire_gridfreq, "parse", lambda body: called.append(1))

    h.handler(_event(key="bad/2026/08/17/0001-x.bin"), None)

    assert not called
    assert fake.calls == []


def test_notify_event_field_links_to_dashboard_graph(monkeypatch):
    """通知の「イベント」欄は、そのイベントが収まる範囲でグラフを開けるSlack mrkdwn
    リンクになる(→ dashboard/app.jsのeventViewWindow()と同じ式をhandler側で複製、
    docs/cloud.md「detect」)。"""
    h, fake = _handler(monkeypatch)
    monkeypatch.setenv("NAMZ_DASHBOARD_URL", "https://dash.example/")
    monkeypatch.setattr(h.wire_gridfreq, "parse", lambda body: _batch_with_freq_deviation())
    monkeypatch.setattr(h.grid_events, "record",
                        lambda device_id, event_type, onset, last, peak: (
                            (f"{device_id:04d}-{event_type}-0", True)))

    h.handler(_event(), None)

    assert len(fake.calls) == 1
    field = fake.calls[0]["fields"]["イベント"]
    assert field.startswith("<https://dash.example/#live?m=")
    assert field.endswith("|0001-freq_deviation-0>")


def test_event_link_without_dashboard_url_falls_back_to_plain_id(monkeypatch):
    h, fake = _handler(monkeypatch)
    monkeypatch.delenv("NAMZ_DASHBOARD_URL", raising=False)
    monkeypatch.setattr(h.wire_gridfreq, "parse", lambda body: _batch_with_freq_deviation())
    monkeypatch.setattr(h.grid_events, "record",
                        lambda device_id, event_type, onset, last, peak: (
                            (f"{device_id:04d}-{event_type}-0", True)))

    h.handler(_event(), None)

    assert fake.calls[0]["fields"]["イベント"] == "0001-freq_deviation-0"


def test_event_view_window_matches_dashboard_presets():
    """dashboard/app.jsのEVENT_VIEW_MINUTES([1, 5, 15, 30])・eventViewWindow()の式と
    一致することを、短い/長いイベントの両端で確認する。"""
    h = load_handler("detect")

    # 短いイベント(1秒未満): 余白は最低30秒なので (1 + 30*2)/60 = ~1.03分 -> 5分プリセットに丸まる
    minutes, end_sec = h._event_view_window(onset_us=0, last_us=500_000)
    assert minutes == 5
    assert end_sec == 31  # ceil(0.5 + 30)

    # 長いイベント(200秒): 余白はduration*0.5=100秒、(200+200)/60 ≒ 6.7分 -> 15分プリセット
    minutes, end_sec = h._event_view_window(onset_us=0, last_us=200_000_000)
    assert minutes == 15
    assert end_sec == 300  # ceil(200 + 100)


def test_no_nominal_freq_skips_freq_deviation_but_keeps_others(monkeypatch):
    h, fake = _handler(monkeypatch)

    def batch():
        b = _batch_with_freq_deviation()
        return Batch(header=_header(record_count=len(b.records), f_nominal_mhz=0), records=b.records)

    monkeypatch.setattr(h.wire_gridfreq, "parse", lambda body: batch())
    recorded_types = []
    monkeypatch.setattr(h.grid_events, "record",
                        lambda device_id, event_type, onset, last, peak: (
                            recorded_types.append(event_type),
                            (f"{device_id:04d}-{event_type}-0", True))[1])

    h.handler(_event(), None)

    assert "freq_deviation" not in recorded_types
