"""watchdog Lambda: 定期起動し、生存台帳を見て異常をSlack通知する。

Namazu(nna774/NamazuHaUrokoGaNai)の
[lambda/watchdog/handler.py](https://github.com/nna774/NamazuHaUrokoGaNai/blob/master/lambda/watchdog/handler.py)
を踏襲するが、Electabuzz固有の項目(AC入力断・再起動検知)を追加している(→ docs/cloud.md)。

不在（データが来ないこと）はイベント駆動では検知できないので、外から定期的に見る。
EventBridge の定期ルールで数分おきに起動し、ingest が更新する electabuzz-devices を見る。

- `NAMZ_OFFLINE_AFTER_S` を超えて受信が途絶えたら「欠測」を通知。落ちている間は
  `NAMZ_OFFLINE_RENOTIFY_S` 間隔で再送、復帰したら1回通知して解除
  (`batch_uplink.devices.evaluate`)。
- 受信は続くが測定時刻が `NAMZ_LAG_AFTER_S` 以上遅れていたら「データ遅延」を通知。
  再送・解除は欠測と同じ形(`batch_uplink.devices.evaluate_lag`)。欠測中は黙る。
- AC入力断(`kGfrqFlagPowerFail`)を検出したバッチが来たら「AC入力断」を通知、
  復帰も同様(`lambda/common/power_fail_watch.py`)。**線が抜けたのか停電したのかは
  区別しない**（→ docs/open-questions.md）。欠測中は黙る。
- 稼働時間ヘッダからの逆算で再起動を検知したら1回だけ通知する
  (`lambda/common/reboot_watch.py`)。`tools/request_ota.py`の許可を経ない再起動は
  異常の可能性がある。
- pull型OTA(docs/ota.md §2)が許可してから長時間解消しなければ「停滞」を通知
  (`lambda/common/ota_watch.py`)。

状態遷移の判定はいずれも副作用のない純粋関数に集約し、DynamoDB抜きでテストできる形に
してある。mute されたデバイス(`lambda/common/watchdog_mute.py`、
`tools/mute_device.py`)は評価自体をスキップする——実際に送信が来ればingestが
自動でunmuteするので、ここでは何も評価しない。
"""

from __future__ import annotations

import datetime as dt
import os
import time

from batch_uplink import devices, notify

from common import ota_watch, power_fail_watch, reboot_watch, watchdog_mute

# 生存とみなす最終受信からの猶予[s]。バッチは30秒間隔なので、既定300秒＝約10バッチ落ち。
OFFLINE_AFTER_S = float(os.environ.get("NAMZ_OFFLINE_AFTER_S", "300"))
# 落ちている間の再送間隔[s]。既定1日。
OFFLINE_RENOTIFY_S = float(os.environ.get("NAMZ_OFFLINE_RENOTIFY_S", "86400"))
# 受信は続くが測定時刻がこの秒数以上遅れたら「データ遅延」とみなす。既定600秒＝10分。
LAG_AFTER_S = float(os.environ.get("NAMZ_LAG_AFTER_S", "600"))
# 遅延が続いている間の再送間隔[s]。既定1日。
LAG_RENOTIFY_S = float(os.environ.get("NAMZ_LAG_RENOTIFY_S", "86400"))
# AC入力断が続いている間の再送間隔[s]。既定1日。
POWER_FAIL_RENOTIFY_S = float(os.environ.get("NAMZ_POWER_FAIL_RENOTIFY_S", "86400"))
# pull型OTA(docs/ota.md §2)。要求してからこの秒数を超えて解消しなければ「停滞」と
# みなす。既定1800秒＝30分。
OTA_STUCK_AFTER_S = float(os.environ.get("NAMZ_OTA_STUCK_AFTER_S", "1800"))
# 停滞が続いている間の再送間隔[s]。既定1日。
OTA_STUCK_RENOTIFY_S = float(os.environ.get("NAMZ_OTA_STUCK_RENOTIFY_S", "86400"))

JST = dt.timezone(dt.timedelta(hours=9))

# 見落とすと実害が大きい通知(欠測・データ遅延・AC入力断)にはメンションを付ける。
# 空文字ならメンション無し。再起動検知・OTA停滞は情報寄りなので付けない。
SLACK_MENTION = os.environ.get("NAMZ_SLACK_MENTION", "")


def _mention() -> str:
    return f"{SLACK_MENTION} " if SLACK_MENTION else ""


def _humanize(seconds: float) -> str:
    s = int(seconds)
    if s < 90:
        return f"{s}秒"
    m = s // 60
    if m < 90:
        return f"{m}分"
    h = m // 60
    if h < 48:
        return f"{h}時間"
    return f"{h // 24}日"


def _fmt_time(us: int) -> str:
    if not us:
        return "（記録なし）"
    return dt.datetime.fromtimestamp(us / 1e6, JST).strftime("%Y-%m-%d %H:%M:%S JST")


def _device_field(did: int) -> str:
    """デバイス番号を、ダッシュボードの詳細ページへのSlack mrkdwnリンクにする。
    NAMZ_DASHBOARD_URL未設定なら番号文字列のまま返す。"""
    label = f"{did:04d}"
    base = os.environ.get("NAMZ_DASHBOARD_URL", "").rstrip("/")
    if not base:
        return label
    return f"<{base}/#device/{did}|{label}>"


def handler(event, context):
    now_us = int(time.time() * 1e6)
    offline_after = int(OFFLINE_AFTER_S * 1e6)
    offline_renotify = int(OFFLINE_RENOTIFY_S * 1e6)
    lag_after = int(LAG_AFTER_S * 1e6)
    lag_renotify = int(LAG_RENOTIFY_S * 1e6)
    power_fail_renotify = int(POWER_FAIL_RENOTIFY_S * 1e6)
    ota_stuck_after = int(OTA_STUCK_AFTER_S * 1e6)
    ota_stuck_renotify = int(OTA_STUCK_RENOTIFY_S * 1e6)
    n = notify.from_env()
    actions = []

    for item in devices.list_devices():
        if watchdog_mute.is_muted(item):
            continue
        did = int(item.get("device_id", 0))
        last = int(item.get("last_ingest_at_us", 0))
        age = _humanize(devices.staleness_us(item, now_us) / 1e6)

        action = devices.evaluate(item, now_us, offline_after, offline_renotify)
        if action is not None:
            actions.append({"device_id": did, "action": action})
            if action in ("offline", "offline_again"):
                title = "デバイス欠測" if action == "offline" else "デバイス欠測（継続）"
                n.notify(
                    title,
                    f"{_mention()}device *{did:04d}* から *{age}* データが来ていない。"
                    "落ちているかもしれない。",
                    {"デバイス": _device_field(did), "最終受信": _fmt_time(last), "経過": age},
                )
                devices.mark_offline_notified(did, now_us)
            elif action == "recovery":
                n.notify(
                    "デバイス復帰",
                    f"{_mention()}device *{did:04d}* がデータ送信を再開した。",
                    {"デバイス": _device_field(did), "最終受信": _fmt_time(last)},
                )
                devices.clear_offline(did)

        # データ遅延（受信は続くが測定時刻が遅れている）。欠測中は evaluate_lag が黙る。
        lag_action = devices.evaluate_lag(item, now_us, lag_after, lag_renotify, offline_after)
        if lag_action is not None:
            actions.append({"device_id": did, "action": lag_action})
            last_batch = int(item.get("last_batch_start_us", 0))
            lag = _humanize((devices.lag_us(item, now_us) or 0) / 1e6)
            if lag_action in ("lag", "lag_again"):
                title = "データ遅延" if lag_action == "lag" else "データ遅延（継続）"
                n.notify(
                    title,
                    f"{_mention()}device *{did:04d}* のデータが *{lag}* 遅れている。"
                    "受信は続いているが測定時刻が追いついていない（時計ずれか追いつき中）。",
                    {"デバイス": _device_field(did), "最新データ時刻": _fmt_time(last_batch),
                     "遅延": lag},
                )
                devices.mark_lag_notified(did, now_us)
            elif lag_action == "lag_recovery":
                n.notify(
                    "データ遅延解消",
                    f"{_mention()}device *{did:04d}* のデータ遅延が解消した。",
                    {"デバイス": _device_field(did), "最新データ時刻": _fmt_time(last_batch)},
                )
                devices.clear_lag(did)

        # AC入力断(kGfrqFlagPowerFail)。線が抜けたのか停電したのかは区別しない
        # (→ docs/open-questions.md)。欠測中は power_fail_watch.evaluate が黙る。
        pf_action = power_fail_watch.evaluate(item, now_us, offline_after, power_fail_renotify)
        if pf_action is not None:
            actions.append({"device_id": did, "action": pf_action})
            if pf_action in ("power_fail", "power_fail_again"):
                title = "AC入力断" if pf_action == "power_fail" else "AC入力断（継続）"
                n.notify(
                    title,
                    f"{_mention()}device *{did:04d}* がAC入力を検出できていない。"
                    "線が抜けたか停電か、現地で切り分けること。",
                    {"デバイス": _device_field(did)},
                )
                power_fail_watch.mark_notified(did, now_us)
            elif pf_action == "power_fail_recovery":
                n.notify(
                    "AC入力復帰",
                    f"{_mention()}device *{did:04d}* のAC入力が復帰した。",
                    {"デバイス": _device_field(did)},
                )
                power_fail_watch.clear_notified(did)

        # 稼働時間ヘッダからの逆算による再起動検知(→ lambda/common/reboot_watch.py)。
        # 初回観測("baseline")は基準を作るだけで通知しない。
        reboot_action = reboot_watch.evaluate_reboot(item)
        if reboot_action is not None:
            actions.append({"device_id": did, "action": reboot_action})
            boot_epoch_us = int(item.get("boot_epoch_us", 0))
            reboot_watch.mark_reboot_notified(did, boot_epoch_us)
            if reboot_action == "rebooted":
                n.notify(
                    "デバイス再起動を検知",
                    f"device *{did:04d}* が再起動した。tools/request_ota.pyでの許可を"
                    "経ていなければ、WDTパニック等の異常の可能性がある。"
                    "シリアルログで確認すること。",
                    {"デバイス": _device_field(did), "起動時刻": _fmt_time(boot_epoch_us)},
                )

        # pull型OTA(docs/ota.md §2)の停滞。要求してから長時間解消しなければ通知する
        # （証明書検証失敗・ネットワーク不調・配布物の取り違え等、原因は問わない）。
        ota_action = ota_watch.evaluate_ota_stuck(item, now_us, ota_stuck_after,
                                                  ota_stuck_renotify)
        if ota_action is not None:
            actions.append({"device_id": did, "action": ota_action})
            target = item.get("pending_ota_version", "?")
            requested_at = int(item.get("pending_ota_requested_at_us", 0))
            elapsed = _humanize((now_us - requested_at) / 1e6) if requested_at else "?"
            title = "pull型OTAが停滞" if ota_action == "stuck" else "pull型OTAが停滞（継続）"
            n.notify(
                title,
                f"device *{did:04d}* に *{target}* への更新を許可してから *{elapsed}* "
                "経つが解消していない。証明書検証失敗・ネットワーク不調・配布物の取り違え等、"
                "実機のシリアルログで原因を確認すること。",
                {"デバイス": _device_field(did), "許可したバージョン": target, "経過": elapsed},
            )
            ota_watch.mark_ota_stuck_notified(did, now_us)

    return {"ok": True, "actions": actions}
