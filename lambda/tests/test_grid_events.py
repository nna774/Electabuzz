"""grid_events のテスト。DynamoDBはrecord()が使う操作だけを持つ偽テーブルで差し替える。"""

import pytest

from common import grid_events


class FakeTable:
    """get_item/put_item/update_item/scan だけを持つ偽のDynamoDBテーブル。"""

    def __init__(self, page_size=1000):
        self.items: dict[str, dict] = {}
        self.page_size = page_size

    def get_item(self, Key):
        item = self.items.get(Key["event_id"])
        return {"Item": dict(item)} if item else {}

    def put_item(self, Item):
        self.items[Item["event_id"]] = dict(Item)

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues):
        assert UpdateExpression == "SET last_us = :l, peak_value = :p"
        item = self.items[Key["event_id"]]
        item["last_us"] = ExpressionAttributeValues[":l"]
        item["peak_value"] = ExpressionAttributeValues[":p"]

    def scan(self, ExclusiveStartKey=None, **_):
        keys = list(self.items)
        start = keys.index(ExclusiveStartKey["event_id"]) + 1 if ExclusiveStartKey else 0
        page = keys[start:start + self.page_size]
        resp = {"Items": [dict(self.items[k]) for k in page]}
        if start + self.page_size < len(keys):
            resp["LastEvaluatedKey"] = {"event_id": page[-1]}
        return resp


@pytest.fixture
def table(monkeypatch):
    t = FakeTable(page_size=10)
    monkeypatch.setattr(grid_events, "_table", lambda: t)
    return t


def test_event_id_stable_within_same_bucket():
    a = grid_events.event_id(1, "freq_deviation", 1_000_000_000)
    b = grid_events.event_id(1, "freq_deviation", 1_000_000_000 + 1_000_000)
    assert a == b


def test_event_id_differs_across_bucket_boundary():
    a = grid_events.event_id(1, "freq_deviation", 0)
    b = grid_events.event_id(1, "freq_deviation", grid_events.BUCKET_US)
    assert a != b


def test_event_id_differs_by_event_type():
    a = grid_events.event_id(1, "freq_deviation", 0)
    b = grid_events.event_id(1, "rocof", 0)
    assert a != b


def test_event_id_differs_by_device():
    a = grid_events.event_id(1, "freq_deviation", 0)
    b = grid_events.event_id(2, "freq_deviation", 0)
    assert a != b


def test_record_merges_continuing_run_into_one_session(table):
    t0 = 10_000_000_000_000
    eid, is_new = grid_events.record(1, "freq_deviation", t0, t0 + 30_000_000, 0.2)
    assert is_new
    for i in range(1, 5):
        onset = t0 + i * 30_000_000
        eid2, is_new = grid_events.record(1, "freq_deviation", onset, onset + 30_000_000, 0.3)
        assert (eid2, is_new) == (eid, False)
    assert int(table.items[eid]["last_us"]) == t0 + 5 * 30_000_000
    assert float(table.items[eid]["peak_value"]) == 0.3


def test_record_merges_even_when_table_exceeds_one_scan_page(table):
    t0 = 10_000_000_000_000
    for i in range(50):
        table.put_item(Item={
            "event_id": f"0001-voltage_anomaly-{i}", "device_id": 1,
            "event_type": "voltage_anomaly", "onset_us": i, "last_us": i, "peak_value": 0.1,
        })
    eid, is_new = grid_events.record(1, "freq_deviation", t0, t0 + 1, 0.2)
    assert is_new
    _, is_new = grid_events.record(1, "freq_deviation", t0 + 30_000_000, t0 + 30_000_001, 0.2)
    assert not is_new


def test_record_bootstraps_pointer_from_pre_existing_events(table):
    t0 = 10_000_000_000_000
    for i in range(25):
        table.put_item(Item={
            "event_id": f"0001-voltage_anomaly-{i}", "device_id": 1,
            "event_type": "voltage_anomaly", "onset_us": t0 - 1000 + i, "last_us": t0 + i,
            "peak_value": 0.1,
        })
    eid, is_new = grid_events.record(1, "voltage_anomaly", t0 + 10_000_000, t0 + 20_000_000, 0.1)
    assert (eid, is_new) == ("0001-voltage_anomaly-24", False)
    ptr = table.items[grid_events.latest_pointer_id(1, "voltage_anomaly")]
    assert ptr["latest_event_id"] == eid


def test_record_starts_new_session_after_merge_gap(table):
    t0 = 10_000_000_000_000
    eid1, _ = grid_events.record(1, "rocof", t0, t0 + 1_000_000, 0.3)
    later = t0 + 1_000_000 + grid_events.MERGE_GAP_US + 1
    eid2, is_new = grid_events.record(1, "rocof", later, later + 1_000_000, 0.3)
    assert is_new and eid2 != eid1


def test_recent_events_reads_all_pages_and_skips_pointers(table):
    for i in range(25):
        grid_events.record(1, "rocof", i * 10 * grid_events.MERGE_GAP_US,
                           i * 10 * grid_events.MERGE_GAP_US + 1, 0.3)
    got = grid_events.recent_events(limit=3)
    assert [int(e["last_us"]) for e in got] == [
        i * 10 * grid_events.MERGE_GAP_US + 1 for i in (24, 23, 22)]
    assert not any(grid_events.is_pointer(e) for e in grid_events.recent_events(limit=100))
