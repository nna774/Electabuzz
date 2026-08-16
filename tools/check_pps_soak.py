#!/usr/bin/env python3
"""フェーズ2(PPS)のsoak確認。`series/`の実バッチを直接読み、PPSロックが
指定期間ずっと途切れず続いているかを見る（→ docs/log/2026-08-17-dashboard-pps-caption-fix.md）。

`/recent` API(`lambda/api/handler.py`)は`MAX_RECENT_MINUTES=30`が上限で数時間分は
一度に見えないので、こちらは`series/`を直接読む。`tools/README.md`の「何度も条件を
変えて解析するときのS3キャッシュ」に従い、`get_object`だけ`.s3cache/`でキャッシュし
（`series/`は永久保存前提なのでキャッシュが腐る心配はない）、`list_objects_v2`は
新着バッチを見逃さないよう毎回本物のS3に通す。

使い方（AWS認証情報とリージョンは通常のboto3の解決に従う）:

    python tools/check_pps_soak.py                       # 直近24時間
    python tools/check_pps_soak.py --hours 6
    python tools/check_pps_soak.py --start 2026-08-17T00:00:00 --end 2026-08-17T12:00:00
    python tools/check_pps_soak.py --device 1

終了コード: ロック落ち・ソース後退・欠測ギャップが1件でもあれば1、無ければ0
（cronや`/loop`から様子見に使う想定）。
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import awsenv  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lambda"))
import store_gridfreq  # noqa: E402
import wire_gridfreq  # noqa: E402

# 連続とみなす上限。バッチは30秒間隔が基本(docs/wire-format.md)なので、
# 2バッチぶん強の猶予を持たせる
GAP_THRESHOLD_S = 75.0
LOCKED_SOURCES = (wire_gridfreq.TimebaseSource.PPS, wire_gridfreq.TimebaseSource.PPS_NTP)


class _BytesBody:
    def __init__(self, data: bytes):
        self._data = data

    def read(self) -> bytes:
        return self._data


class CachingS3:
    """get_objectだけ`.s3cache/`でキャッシュする薄いラッパー。listは毎回本物へ通す。"""

    def __init__(self, s3, cache_dir: Path):
        self._s3 = s3
        self._cache_dir = cache_dir

    def list_objects_v2(self, **kw):
        return self._s3.list_objects_v2(**kw)

    def get_object(self, Bucket: str, Key: str):
        path = self._cache_dir / Key
        if path.exists():
            return {"Body": _BytesBody(path.read_bytes())}
        resp = self._s3.get_object(Bucket=Bucket, Key=Key)
        body = resp["Body"].read()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        return {"Body": _BytesBody(body)}


def main_checkout_root() -> Path:
    """worktreeで動いていても、`.s3cache/`はメインチェックアウト側を指す(tools/README.md)。"""
    out = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return Path(out).resolve().parent


def resolve_bucket(explicit: str | None) -> str:
    if explicit:
        return explicit
    if os.environ.get("ELBZ_BUCKET"):
        return os.environ["ELBZ_BUCKET"]
    out = subprocess.run(
        ["terraform", "-chdir=terraform", "output", "-raw", "data_bucket"],
        capture_output=True, text=True, cwd=main_checkout_root(),
    )
    if out.returncode == 0 and out.stdout.strip():
        return out.stdout.strip()
    raise SystemExit(
        "バケット名を解決できない。ELBZ_BUCKET環境変数を設定するか、"
        "terraform applyされたディレクトリで実行すること。"
    )


def parse_time_arg(s: str) -> int:
    """ISO8601（タイムゾーン省略時はUTC扱い）を unix us に変換。"""
    d = dt.datetime.fromisoformat(s)
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return int(d.timestamp() * 1e6)


def fmt_us(us: int) -> str:
    return dt.datetime.fromtimestamp(us / 1e6, tz=dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def batch_duration_s(h: wire_gridfreq.Header) -> float:
    if h.record_rate_mhz <= 0:
        return 0.0
    return h.record_count * 1000.0 / h.record_rate_mhz


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hours", type=float, default=24.0, help="直近何時間を見るか(既定24)")
    ap.add_argument("--start", help="開始時刻(ISO8601)。指定時は--hoursを無視")
    ap.add_argument("--end", help="終了時刻(ISO8601、既定は現在時刻)")
    ap.add_argument("--device", type=int, default=None, help="device_idで絞り込む(既定は全台)")
    ap.add_argument("--bucket", help="既定はELBZ_BUCKET環境変数、それも無ければterraform output")
    args = ap.parse_args()

    if args.start:
        start_us = parse_time_arg(args.start)
        end_us = parse_time_arg(args.end) if args.end else int(time.time() * 1e6)
    else:
        end_us = int(time.time() * 1e6)
        start_us = end_us - int(args.hours * 3600 * 1e6)

    awsenv.ensure_region()
    bucket = resolve_bucket(args.bucket)

    import boto3

    cache_dir = main_checkout_root() / ".s3cache"
    s3 = CachingS3(boto3.client("s3"), cache_dir)

    print(f"対象: {fmt_us(start_us)} 〜 {fmt_us(end_us)}  bucket={bucket}", file=sys.stderr)
    keys = store_gridfreq.list_series_keys_in_range(s3, bucket, start_us, end_us)
    if args.device is not None:
        want = f"{args.device:04d}-"
        keys = [k for k in keys if Path(k).name.startswith(want)]
    print(f"対象バッチ数(list): {len(keys)}", file=sys.stderr)

    batches: list[wire_gridfreq.Batch] = []
    for key in keys:
        try:
            body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
            batches.append(wire_gridfreq.parse(body))
        except wire_gridfreq.WireFormatError as e:
            print(f"  skip {key}: パース失敗({e})", file=sys.stderr)

    by_device: dict[int, list[wire_gridfreq.Batch]] = {}
    for b in batches:
        by_device.setdefault(b.header.device_id, []).append(b)

    had_problem = False

    for device_id, devbatches in sorted(by_device.items()):
        devbatches.sort(key=lambda b: b.header.batch_start_us)
        print(f"\n=== device {device_id}: {len(devbatches)}バッチ ===")

        events: list[str] = []
        residuals_ns: list[int] = []
        locked_s = 0.0
        total_s = 0.0
        prev = None

        for b in devbatches:
            h = b.header
            dur = batch_duration_s(h)
            total_s += dur
            source = h.source_name
            locked = wire_gridfreq.BatchFlag.PPS_LOCKED in h.batch_flags
            if source in (s.name for s in LOCKED_SOURCES):
                locked_s += dur
                residuals_ns.append(h.tb_residual_ns)

            if prev is not None:
                gap_s = (h.batch_start_us - prev.header.batch_start_us) / 1e6 - batch_duration_s(prev.header)
                if gap_s > GAP_THRESHOLD_S:
                    events.append(f"  [{fmt_us(prev.header.batch_start_us)}] 欠測ギャップ {gap_s:.0f}秒")
                if h.session_id != prev.header.session_id:
                    events.append(
                        f"  [{fmt_us(h.batch_start_us)}] 再起動検知: session_id "
                        f"{prev.header.session_id} -> {h.session_id}"
                    )
                if source != prev.header.source_name:
                    events.append(
                        f"  [{fmt_us(h.batch_start_us)}] timebase_source変化: "
                        f"{prev.header.source_name} -> {source}"
                    )
                if source in (s.name for s in LOCKED_SOURCES) and not locked:
                    events.append(
                        f"  [{fmt_us(h.batch_start_us)}] 不整合: source={source}だが"
                        f"PPS_LOCKEDフラグが立っていない(flags=0x{h.flags:04x})"
                    )
            prev = b

        if devbatches:
            span_s = (devbatches[-1].header.batch_start_us - devbatches[0].header.batch_start_us) / 1e6
            print(f"  期間: {fmt_us(devbatches[0].header.batch_start_us)} 〜 "
                  f"{fmt_us(devbatches[-1].header.batch_start_us)}({span_s / 3600:.1f}時間)")
            print(f"  PPS/PPS_NTPロック率: {100 * locked_s / total_s:.1f}%"
                  f"（{locked_s:.0f}s / {total_s:.0f}s）" if total_s else "  データなし")
            if residuals_ns:
                print(f"  tb_residual_ns: min={min(residuals_ns)} max={max(residuals_ns)} "
                      f"mean={sum(residuals_ns) / len(residuals_ns):.1f}")

        if events:
            had_problem = True
            print(f"  イベント({len(events)}件):")
            for e in events:
                print(e)
        else:
            print("  イベントなし(ソース後退・欠測ギャップ・再起動いずれも検出せず)")

    if not batches:
        print("対象期間にバッチが1件も見つからなかった。--hoursや--bucketを見直すこと。", file=sys.stderr)
        return 1

    return 1 if had_problem else 0


if __name__ == "__main__":
    raise SystemExit(main())
