"""S3 の `series/` から GFRQ バッチを読み、時間窓を組み立てる。api Lambda 用。

Namazu の `lambda/common/store.py` と同じ役回りだが、GFRQ は1レコード/秒で
1バッチ最大30件と小さいので、`store.py` にある min/max エンベロープ間引きは
持ち込んでいない（`api/handler.py` の `MAX_RECENT_MINUTES` 上限と合わせても
最大1800点で、間引く理由が無い）。
"""

from __future__ import annotations

import s3keys
import wire_gridfreq


def list_series_keys_in_range(s3, bucket: str, start_us: int, end_us: int) -> list[str]:
    """[start,end] と重なる `series/` のキーを時系列順で返す。"""
    keys: list[str] = []
    for prefix in s3keys.series_hour_prefixes(start_us, end_us):
        token = None
        while True:
            kw = {"Bucket": bucket, "Prefix": prefix}
            if token:
                kw["ContinuationToken"] = token
            resp = s3.list_objects_v2(**kw)
            keys += [it["Key"] for it in resp.get("Contents", [])]
            if resp.get("IsTruncated"):
                token = resp["NextContinuationToken"]
            else:
                break
    # キー末尾の batch_start_us(20桁ゼロ埋め) で時系列ソート
    keys.sort()
    return keys


def load_batches_in_range(s3, bucket: str, start_us: int, end_us: int) -> list[wire_gridfreq.Batch]:
    """[start,end] と重なるバッチを `batch_start_us` 順にパースして返す。

    範囲の**前**に40秒(1バッチぶん+余裕)だけ広げて拾う。1バッチは最大30秒ぶんの
    幅を持つので、`start` の直前に始まったバッチが範囲に食い込むことがあり、
    かつ隣接レコードの周波数計算(`api/handler.py`)には「窓の直前の1点」が要る。

    **壊れているバッチは黙って飛ばす。** ingest 側で CRC 不一致は既に `bad/` へ
    隔離済みなので、ここに来る時点で壊れているのは想定外だが、ダッシュボードの
    1系列のためにAPI全体を500にする理由が無い。
    """
    keys = list_series_keys_in_range(s3, bucket, start_us - 40_000_000, end_us)
    batches = []
    for key in keys:
        try:
            body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
            batches.append(wire_gridfreq.parse(body))
        except Exception:  # noqa: BLE001
            continue
    batches.sort(key=lambda b: b.header.batch_start_us)
    return batches
