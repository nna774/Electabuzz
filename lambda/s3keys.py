"""S3キーの組み立て。→ docs/storage.md

**`batch_uplink.s3util` を使わない理由は prefix だ。** あちらの `raw_key()` は
`raw/` 固定で、Namazu 側の lifecycle は `raw/` に 90日の expire を掛けている。
GFRQ のバッチは**累積位相**であって永久保存が前提なので、同じ prefix に置くと
「設計上永久のはずのデータが90日で消える」という、事故ってから3ヶ月後に気づく
種類の壊れ方をする。**prefix は保存方針そのものだ。共有ライブラリの既定に
寄りかからず、こちらで名指しする。**

キーの形（`{device:04d}-{batch_start_us:020d}.bin`）は共有ライブラリと同一に
揃えてある。**20桁ゼロ埋めゆえに辞書順 = 時系列順**で、S3 の list がそのまま
時系列走査になる。ここを崩すと rollup と api の両方が桁上がりで壊れる。
"""

from __future__ import annotations

import datetime as dt
from typing import Iterator

SERIES_PREFIX = "series"
# CRC が合わなかったバッチの隔離先。→ handler の _handle_batch
BAD_PREFIX = "bad"


def _dt(us: int) -> dt.datetime:
    return dt.datetime.fromtimestamp(us / 1e6, tz=dt.timezone.utc)


def series_key(device_id: int, batch_start_us: int) -> str:
    """series/YYYY/MM/DD/HH/<device>-<startus>.bin

    **測定開始時刻だけから決まる。** 受信時刻を混ぜないので、同じバッチを
    二重送信しても同じキーに上書きされるだけで済む（冪等）。
    """
    d = _dt(batch_start_us)
    return (f"{SERIES_PREFIX}/{d:%Y/%m/%d/%H}/"
            f"{device_id:04d}-{batch_start_us:020d}.bin")


def bad_key(device_id: str, received_at_us: int, digest: str) -> str:
    """bad/YYYY/MM/DD/<device>-<受信時刻>-<本文ハッシュ>.bin

    **測定開始時刻を使えない。** CRC が合わないバッチはヘッダが正しく読めた
    保証が無く、`batch_start_us` を信じるとキーが飛ぶ。受信壁時計で並べ、
    本文のハッシュを付けて同一内容の再送を1つに畳む。

    device は署名検証に通った側の値を使う。本文の device_id は信用しない。
    """
    d = _dt(received_at_us)
    safe = "".join(c for c in device_id if c.isalnum())[:16] or "unknown"
    return (f"{BAD_PREFIX}/{d:%Y/%m/%d}/"
            f"{safe}-{received_at_us:020d}-{digest[:16]}.bin")


# 多重防御: 1回の列挙で辿る時別prefixの上限。s3util.MAX_HOUR_PREFIXES と同じ発想で、
# 引数の取り違えで S3 を舐め尽くさないための蓋。
MAX_HOUR_PREFIXES = 24 * 8  # 8日


def series_hour_prefixes(start_us: int, end_us: int) -> Iterator[str]:
    """[start,end] をまたぐ series/ の時別prefixを列挙。"""
    cur = _dt(start_us).replace(minute=0, second=0, microsecond=0)
    end = _dt(end_us)
    count = 0
    while cur <= end and count < MAX_HOUR_PREFIXES:
        yield f"{SERIES_PREFIX}/{cur:%Y/%m/%d/%H}/"
        cur += dt.timedelta(hours=1)
        count += 1
