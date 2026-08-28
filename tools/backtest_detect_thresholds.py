#!/usr/bin/env python3
"""detect(`lambda/common/grid_detect.py`)のしきい値を、実データに対して
再生してイベント数を比較する（→ docs/cloud.md「detect」）。

`ELBZ_FREQ_DEV_THRESHOLD_HZ`(既定100mHz)が出すぎている疑いがあるときに、
`series/`の実バッチへ`grid_detect.analyze`をしきい値違いで複数回流し、
確定イベント(run)の件数がどう変わるかを見る。運用中のLambdaには一切触らず、
判定ロジックだけを純粋関数として再利用する(`grid_detect.analyze`に副作用は無い)。

使い方（AWS認証情報とリージョンは通常のboto3の解決に従う）:

    python tools/backtest_detect_thresholds.py                      # 直近7日、100/150mHzを比較
    python tools/backtest_detect_thresholds.py --hours 48
    python tools/backtest_detect_thresholds.py --thresholds-mhz 100,120,150,200
    python tools/backtest_detect_thresholds.py --device 1
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
import s3cache  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lambda"))
import store_gridfreq  # noqa: E402
import wire_gridfreq  # noqa: E402
from common import grid_detect  # noqa: E402

# handler.pyの既定と同じ(ELBZ_FREQ_DEV_HOLD_RECORDS)。しきい値だけを振るので固定する。
FREQ_DEV_HOLD_RECORDS = int(os.environ.get("ELBZ_FREQ_DEV_HOLD_RECORDS", "3"))


def main_checkout_root() -> Path:
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
    d = dt.datetime.fromisoformat(s)
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return int(d.timestamp() * 1e6)


def fmt_us(us: int) -> str:
    return dt.datetime.fromtimestamp(us / 1e6, tz=dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hours", type=float, default=24.0 * 7, help="直近何時間を見るか(既定168=7日)")
    ap.add_argument("--start", help="開始時刻(ISO8601)。指定時は--hoursを無視")
    ap.add_argument("--end", help="終了時刻(ISO8601、既定は現在時刻)")
    ap.add_argument("--device", type=int, default=None, help="device_idで絞り込む(既定は全台)")
    ap.add_argument("--bucket", help="既定はELBZ_BUCKET環境変数、それも無ければterraform output")
    ap.add_argument("--thresholds-mhz", default="100,150",
                     help="比較するfreq_dev_threshold_hzの候補(mHz、カンマ区切り、既定100,150)")
    args = ap.parse_args()

    if args.start:
        start_us = parse_time_arg(args.start)
        end_us = parse_time_arg(args.end) if args.end else int(time.time() * 1e6)
    else:
        end_us = int(time.time() * 1e6)
        start_us = end_us - int(args.hours * 3600 * 1e6)

    thresholds_hz = [float(x) / 1000.0 for x in args.thresholds_mhz.split(",")]

    awsenv.ensure_region()
    bucket = resolve_bucket(args.bucket)
    s3 = s3cache.cached_client()

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

    if not batches:
        print("対象期間にバッチが1件も見つからなかった。--hoursや--bucketを見直すこと。", file=sys.stderr)
        return 1

    by_device: dict[int, list[wire_gridfreq.Batch]] = {}
    for b in batches:
        by_device.setdefault(b.header.device_id, []).append(b)

    for device_id, devbatches in sorted(by_device.items()):
        devbatches.sort(key=lambda b: b.header.batch_start_us)
        samples = grid_detect.samples_from_batches(devbatches)

        # f_nominal_hzはバッチ毎の判別値。稼働中はほぼ一定のはずだが、
        # 万一揺れていても最頻値を代表値として使う(0はNamazu側の「未判別」なので除く)。
        nominals = [b.header.f_nominal_hz for b in devbatches if b.header.f_nominal_hz > 0]
        if not nominals:
            print(f"\n=== device {device_id}: f_nominal_hz未判別のバッチしか無い。スキップ ===")
            continue
        f_nominal = max(set(nominals), key=nominals.count)

        span_s = (devbatches[-1].header.batch_start_us - devbatches[0].header.batch_start_us) / 1e6
        print(f"\n=== device {device_id}: {len(devbatches)}バッチ、"
              f"{span_s / 3600:.1f}時間、f_nominal={f_nominal}Hz ===")

        freq_samples = [s for s in samples if s.freq_hz is not None]
        print(f"  周波数算出できたレコード数: {len(freq_samples)} / {len(samples)}")

        for thr in thresholds_hz:
            detections = grid_detect.analyze(
                samples,
                f_nominal_hz=f_nominal,
                freq_dev_threshold_hz=thr,
                freq_dev_hold_records=FREQ_DEV_HOLD_RECORDS,
                # RoCoF・電圧異常は今回の比較対象外なので、絶対に発火しない値で無効化する。
                voltage_dev_fraction=1.0,
                voltage_dev_hold_records=10**9,
                nominal_v_rms_mv=0.0,
                rocof_threshold_hz_per_s=10**9,
            )
            freq_events = [d for d in detections if d.event_type == grid_detect.FreqDeviation]
            if not freq_events:
                print(f"  閾値{thr * 1000:.0f}mHz: freq_deviationイベント 0件")
                continue
            total_duration_s = sum((d.last_us - d.onset_us) / 1e6 for d in freq_events)
            peaks_mhz = sorted((d.peak_value * 1000 for d in freq_events), reverse=True)
            top = ", ".join(f"{p:.1f}" for p in peaks_mhz[:5])
            print(f"  閾値{thr * 1000:.0f}mHz: freq_deviationイベント {len(freq_events)}件"
                  f"（延べ{total_duration_s:.0f}秒、ピーク上位[mHz]: {top}"
                  f"{' ...' if len(peaks_mhz) > 5 else ''}）")

    return 0


if __name__ == "__main__":
    sys.exit(main())
