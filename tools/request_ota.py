#!/usr/bin/env python3
"""デバイスにpull型OTAの更新を許可する/取り消す手元用CLI（→ docs/ota.md）。

デバイスは毎バッチ送信のレスポンスヘッダ(X-Elbz-Ota-Version)でpending_ota_version
を知り、自分のビルドバージョン(ELBZ_FW_VERSION)と違えば安全停止シーケンスを経て
から取得・書き込みする。値は一度伝えたら消す一回性のものではない——ターゲットは
「あるべき状態」なので、デバイスが実際にそのバージョンで起動するまで照合し続ける
（取得・書き込み失敗時の自然なリトライにもなる）。達成したらingestが自動で解放する。

使い方（AWS認証情報とリージョンは通常のboto3の解決に従う）:

    python tools/publish_ota.sh                       # バイナリを公開し、バージョンを表示

    python tools/request_ota.py request 1 351cd38        # device 1 に 351cd38 への更新を許可
    python tools/request_ota.py request 1 351cd38 --yes  # 確認プロンプトを省略
    python tools/request_ota.py cancel 1                  # 許可を取り消す
    python tools/request_ota.py list                      # 現在許可が立っているデバイスを一覧
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import awsenv  # noqa: E402

import boto3  # noqa: E402
from batch_uplink import devices  # noqa: E402

# terraform outputs devices_table と一致(project="electabuzz"固定・1台構成なので
# Namazuのように --id ごとの払い出しテーブル解決は要らない)。
DEFAULT_TABLE = "electabuzz-devices"

_table_cache = None


def _table():
    global _table_cache
    if _table_cache is None:
        _table_cache = boto3.resource("dynamodb").Table(os.environ["NAMZ_DEVICES_TABLE"])
    return _table_cache


def _confirm(prompt: str) -> bool:
    try:
        return input(f"{prompt} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def cmd_request(args):
    item = devices.get_device(args.device_id)
    if item is None:
        sys.exit(f"デバイスが見つからない（一度も送信していない?）: device {args.device_id}")
    if not args.yes and not _confirm(
            f"device {args.device_id} に version={args.version} への更新を許可するか?"):
        sys.exit("中止した")
    _table().update_item(
        Key={"device_id": args.device_id},
        UpdateExpression="SET pending_ota_version = :v, pending_ota_requested_at_us = :t",
        ExpressionAttributeValues={":v": args.version, ":t": int(time.time() * 1e6)},
    )
    print(f"更新を許可した: device {args.device_id} -> version={args.version}"
          "（次回のバッチ送信レスポンスから反映される）")


def cmd_cancel(args):
    _table().update_item(
        Key={"device_id": args.device_id},
        UpdateExpression="REMOVE pending_ota_version, pending_ota_requested_at_us",
    )
    print(f"更新許可を取り消した: device {args.device_id}")


def cmd_list(_args):
    items = [it for it in devices.list_devices() if it.get("pending_ota_version")]
    if not items:
        print("更新許可の立っているデバイスはない")
        return
    print(f"更新許可: {len(items)} 件")
    for it in items:
        did = int(it.get("device_id", 0))
        requested_at = it.get("pending_ota_requested_at_us")
        age_s = int(time.time() - int(requested_at) / 1e6) if requested_at else None
        suffix = f"（{age_s}秒前に要求）" if age_s is not None else ""
        fw = it.get("fw_version", "?")
        print(f"  device {did}  現在={fw} -> pending_ota_version={it['pending_ota_version']}"
              f"{suffix}")


def main(argv=None):
    p = argparse.ArgumentParser(description="デバイスへのpull型OTA更新許可の操作")
    default_table = os.environ.get("NAMZ_DEVICES_TABLE", DEFAULT_TABLE)
    p.add_argument("--table", default=default_table,
                   help=f"デバイスのDynamoDBテーブル名（既定: {DEFAULT_TABLE}）")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("request", help="更新を許可する")
    s.add_argument("device_id", type=int, help="対象デバイスID")
    s.add_argument("version", help="許可するバージョン（ELBZ_FW_VERSIONと一致する短縮hash）")
    s.add_argument("--yes", "-y", action="store_true", help="確認プロンプトを省略する")

    s = sub.add_parser("cancel", help="更新許可を取り消す")
    s.add_argument("device_id", type=int, help="対象デバイスID")

    sub.add_parser("list", help="更新許可の立っているデバイスを一覧")

    args = p.parse_args(argv)
    os.environ["NAMZ_DEVICES_TABLE"] = args.table
    awsenv.ensure_region()

    if args.cmd == "request":
        cmd_request(args)
    elif args.cmd == "cancel":
        cmd_cancel(args)
    elif args.cmd == "list":
        cmd_list(args)


if __name__ == "__main__":
    main()
