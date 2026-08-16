"""reboot_watch: boot_epoch_us の更新判定・再起動通知の状態遷移（DynamoDBに触れない）。"""

from common import reboot_watch


# --- should_update_boot_epoch（ingest側。ドリフト許容±2分） ---

def test_should_update_when_unset():
    assert reboot_watch.should_update_boot_epoch(None, 1_000_000) is True


def test_should_not_update_within_threshold():
    assert reboot_watch.should_update_boot_epoch(1_000_000_000, 1_000_000_000 + 30_000_000) is False


def test_should_update_beyond_threshold():
    over = reboot_watch.BOOT_EPOCH_DRIFT_THRESHOLD_US + 1
    assert reboot_watch.should_update_boot_epoch(1_000_000_000, 1_000_000_000 + over) is True


def test_should_update_handles_negative_drift():
    over = reboot_watch.BOOT_EPOCH_DRIFT_THRESHOLD_US + 1
    assert reboot_watch.should_update_boot_epoch(1_000_000_000, 1_000_000_000 - over) is True


# --- evaluate_reboot（watchdog側。前回通知済み値との比較） ---

def test_no_action_without_boot_epoch():
    assert reboot_watch.evaluate_reboot({"device_id": 1}) is None


def test_baseline_on_first_observation():
    # boot_epoch_usはあるがboot_epoch_notified_usが無い(=watchdogがまだ見ていない)
    # → 基準を作るだけで通知しない
    it = {"device_id": 1, "boot_epoch_us": 1_000_000_000}
    assert reboot_watch.evaluate_reboot(it) == "baseline"


def test_no_action_when_unchanged():
    it = {"device_id": 1, "boot_epoch_us": 1_000_000_000, "boot_epoch_notified_us": 1_000_000_000}
    assert reboot_watch.evaluate_reboot(it) is None


def test_rebooted_when_boot_epoch_changes():
    it = {"device_id": 1, "boot_epoch_us": 2_000_000_000, "boot_epoch_notified_us": 1_000_000_000}
    assert reboot_watch.evaluate_reboot(it) == "rebooted"
