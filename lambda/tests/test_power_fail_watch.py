"""power_fail_watch.evaluate のAC入力断状態遷移。

devices.evaluate_lag と同じ形の純粋関数テスト（DynamoDBに触れない）。
しきい値 offline=5分, 再送=1日 を基準にする。
"""

from common import power_fail_watch

OFFLINE = 300_000_000        # 5分[us]
RENOTIFY = 86_400_000_000    # 1日[us]
NOW = 1_000_000_000_000      # 適当な現在時刻[us]


def _item(power_fail: bool, last_ingest_ago_us=60_000_000, notified_ago_us=None):
    it = {"device_id": 1, "last_ingest_at_us": NOW - last_ingest_ago_us, "power_fail": power_fail}
    if notified_ago_us is not None:
        it["power_fail_notified_at_us"] = NOW - notified_ago_us
    return it


def test_no_action_when_not_failing():
    assert power_fail_watch.evaluate(_item(False), NOW, OFFLINE, RENOTIFY) is None


def test_first_power_fail():
    assert power_fail_watch.evaluate(_item(True), NOW, OFFLINE, RENOTIFY) == "power_fail"


def test_power_fail_but_recently_notified_stays_quiet():
    it = _item(True, notified_ago_us=3_600_000_000)  # 1時間前に通知
    assert power_fail_watch.evaluate(it, NOW, OFFLINE, RENOTIFY) is None


def test_power_fail_renotify_after_a_day():
    it = _item(True, notified_ago_us=86_400_000_000 + 1)
    assert power_fail_watch.evaluate(it, NOW, OFFLINE, RENOTIFY) == "power_fail_again"


def test_recovery_after_notified():
    it = _item(False, notified_ago_us=2 * 86_400_000_000)
    assert power_fail_watch.evaluate(it, NOW, OFFLINE, RENOTIFY) == "power_fail_recovery"


def test_recovery_without_prior_notification_stays_quiet():
    # 一度も通知していないなら復帰扱いにする理由が無い
    assert power_fail_watch.evaluate(_item(False), NOW, OFFLINE, RENOTIFY) is None


def test_silent_while_offline():
    # 欠測中(受信途絶)は黙る。offline側の通知が担当（devices.evaluate_lagと同じガード）。
    it = _item(True, last_ingest_ago_us=400_000_000)
    assert power_fail_watch.evaluate(it, NOW, OFFLINE, RENOTIFY) is None


def test_recovery_also_silent_while_offline():
    it = _item(False, last_ingest_ago_us=400_000_000, notified_ago_us=2 * 86_400_000_000)
    assert power_fail_watch.evaluate(it, NOW, OFFLINE, RENOTIFY) is None
