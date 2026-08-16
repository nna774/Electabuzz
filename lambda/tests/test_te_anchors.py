"""te_anchors.anchor_id の純粋関数テスト。

open_run_if_needed/close_open_run/anchors_for_sessionはDynamoDBに直接触るので、
grid_events.pyと同じ方針でテスト対象から外す(モック層を持ち込まない、
→ test_grid_events.py)。
"""

from common import te_anchors


def test_anchor_id_stable_for_same_inputs():
    a = te_anchors.anchor_id(1, 7, 1_750_000_000_000_000)
    b = te_anchors.anchor_id(1, 7, 1_750_000_000_000_000)
    assert a == b


def test_anchor_id_differs_by_device():
    a = te_anchors.anchor_id(1, 7, 0)
    b = te_anchors.anchor_id(2, 7, 0)
    assert a != b


def test_anchor_id_differs_by_session():
    a = te_anchors.anchor_id(1, 7, 0)
    b = te_anchors.anchor_id(1, 8, 0)
    assert a != b


def test_anchor_id_differs_by_t0():
    a = te_anchors.anchor_id(1, 7, 0)
    b = te_anchors.anchor_id(1, 7, 1)
    assert a != b
