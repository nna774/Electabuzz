"""watchdog Lambda のハンドラレベルテスト。

状態遷移の判定自体はbatch_uplink.devices / common.power_fail_watch /
common.reboot_watch / common.ota_watch の純粋関数テストで確認済みなので、
ここでは「配線が正しいか」（list_devicesを回し、mute済みをスキップし、
アクションに応じて正しい通知とマークを呼ぶか）だけを見る。DynamoDBには触れない
——devices.list_devicesと各モジュールのmark_*/clear_*をすべて差し替える。
"""

from __future__ import annotations

from conftest import load_handler

NOW_US = 1_000_000_000_000
NOW_S = NOW_US / 1e6


class FakeNotifier:
    def __init__(self):
        self.calls = []

    def notify(self, title, text, fields=None, **kw):
        self.calls.append({"title": title, "text": text, "fields": fields})


def _mock_devices(monkeypatch, h, items):
    monkeypatch.setattr(h.devices, "list_devices", lambda: items)
    marks = {"offline": [], "offline_clear": [], "lag": [], "lag_clear": []}
    monkeypatch.setattr(h.devices, "mark_offline_notified",
                        lambda did, at: marks["offline"].append((did, at)))
    monkeypatch.setattr(h.devices, "clear_offline", lambda did: marks["offline_clear"].append(did))
    monkeypatch.setattr(h.devices, "mark_lag_notified", lambda did, at: marks["lag"].append((did, at)))
    monkeypatch.setattr(h.devices, "clear_lag", lambda did: marks["lag_clear"].append(did))
    return marks


def _mock_extras(monkeypatch, h):
    marks = {"pf": [], "pf_clear": [], "reboot": [], "ota": []}
    monkeypatch.setattr(h.power_fail_watch, "mark_notified",
                        lambda did, at: marks["pf"].append((did, at)))
    monkeypatch.setattr(h.power_fail_watch, "clear_notified",
                        lambda did: marks["pf_clear"].append(did))
    monkeypatch.setattr(h.reboot_watch, "mark_reboot_notified",
                        lambda did, boot: marks["reboot"].append((did, boot)))
    monkeypatch.setattr(h.ota_watch, "mark_ota_stuck_notified",
                        lambda did, at: marks["ota"].append((did, at)))
    return marks


def _handler(monkeypatch):
    h = load_handler("watchdog")
    monkeypatch.setattr(h.time, "time", lambda: NOW_S)
    fake = FakeNotifier()
    monkeypatch.setattr(h.notify, "from_env", lambda: fake)
    return h, fake


def test_offline_device_triggers_notification(monkeypatch):
    h, fake = _handler(monkeypatch)
    item = {"device_id": 1, "last_ingest_at_us": NOW_US - 400_000_000}  # 400秒無音 > 300秒
    marks = _mock_devices(monkeypatch, h, [item])
    _mock_extras(monkeypatch, h)

    result = h.handler({}, None)

    assert marks["offline"] == [(1, NOW_US)]
    titles = [c["title"] for c in fake.calls]
    assert "デバイス欠測" in titles
    assert {"device_id": 1, "action": "offline"} in result["actions"]


def test_muted_device_is_skipped_entirely(monkeypatch):
    h, fake = _handler(monkeypatch)
    item = {
        "device_id": 1,
        "last_ingest_at_us": NOW_US - 400_000_000,
        "watchdog_muted": True,
    }
    _mock_devices(monkeypatch, h, [item])
    _mock_extras(monkeypatch, h)

    result = h.handler({}, None)

    assert fake.calls == []
    assert result["actions"] == []


def test_power_fail_triggers_notification(monkeypatch):
    h, fake = _handler(monkeypatch)
    item = {
        "device_id": 2,
        "last_ingest_at_us": NOW_US - 10_000_000,  # 生存中
        "power_fail": True,
    }
    _mock_devices(monkeypatch, h, [item])
    marks = _mock_extras(monkeypatch, h)

    result = h.handler({}, None)

    assert marks["pf"] == [(2, NOW_US)]
    titles = [c["title"] for c in fake.calls]
    assert "AC入力断" in titles
    assert {"device_id": 2, "action": "power_fail"} in result["actions"]


def test_reboot_baseline_does_not_notify(monkeypatch):
    """初回観測(baseline)は基準を作るだけで通知しない。"""
    h, fake = _handler(monkeypatch)
    item = {
        "device_id": 3,
        "last_ingest_at_us": NOW_US - 10_000_000,
        "boot_epoch_us": 999,
    }
    _mock_devices(monkeypatch, h, [item])
    marks = _mock_extras(monkeypatch, h)

    result = h.handler({}, None)

    assert marks["reboot"] == [(3, 999)]
    assert fake.calls == []
    assert {"device_id": 3, "action": "baseline"} in result["actions"]


def test_reboot_change_notifies(monkeypatch):
    h, fake = _handler(monkeypatch)
    item = {
        "device_id": 3,
        "last_ingest_at_us": NOW_US - 10_000_000,
        "boot_epoch_us": 2_000_000_000,
        "boot_epoch_notified_us": 1_000_000_000,
    }
    _mock_devices(monkeypatch, h, [item])
    marks = _mock_extras(monkeypatch, h)

    result = h.handler({}, None)

    assert marks["reboot"] == [(3, 2_000_000_000)]
    titles = [c["title"] for c in fake.calls]
    assert "デバイス再起動を検知" in titles
    assert {"device_id": 3, "action": "rebooted"} in result["actions"]


def test_ota_stuck_triggers_notification(monkeypatch):
    h, fake = _handler(monkeypatch)
    item = {
        "device_id": 4,
        "last_ingest_at_us": NOW_US - 10_000_000,
        "pending_ota_version": "abc1234",
        "pending_ota_requested_at_us": NOW_US - 2_000_000_000,  # 33分強前
    }
    _mock_devices(monkeypatch, h, [item])
    marks = _mock_extras(monkeypatch, h)

    result = h.handler({}, None)

    assert marks["ota"] == [(4, NOW_US)]
    titles = [c["title"] for c in fake.calls]
    assert "pull型OTAが停滞" in titles
    assert {"device_id": 4, "action": "stuck"} in result["actions"]


def test_quiet_device_produces_no_actions(monkeypatch):
    h, fake = _handler(monkeypatch)
    item = {"device_id": 5, "last_ingest_at_us": NOW_US - 10_000_000}
    _mock_devices(monkeypatch, h, [item])
    _mock_extras(monkeypatch, h)

    result = h.handler({}, None)

    assert fake.calls == []
    assert result["actions"] == []
