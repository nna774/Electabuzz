"""grid_events.event_id の純粋関数テスト。

record()/recent_events()はDynamoDBに直接触るので、他のcommon/配下のモジュール
(reboot_watch等)と同じ方針でテスト対象から外す(モック層を持ち込まない)。
"""

from common import grid_events


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
