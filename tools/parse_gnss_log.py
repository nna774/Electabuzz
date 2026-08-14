"""u-center等が無い環境で録った生シリアルログ(NMEA＋UBXバイナリ混在)を要約する。

`screen`や`cat`で吐かせたファイルは、u-centerの録画機能で保存する`.ubx`と
中身は同じ(受信機がUARTに流したバイト列をそのまま落としただけ)なので、
このスクリプトはどちらの取り方のログにも使える。段階1の判定(捕捉衛星数・
fix安定性の実測、→ docs/gnss.md)で、屋外/屋内(窓ガラス貼り付け)の比較に使う。

対象にするメッセージ:
    - NMEA $..GGA  : fix品質・捕捉衛星数(numSV)・HDOP・高度(UTC時刻のみ、日付は無い)
    - NMEA $..RMC  : UTC日付(ddmmyy)。GGAの時刻に日付を紐づけるために使う
    - NMEA $..GSV  : 衛星ごとのCN0(SNR)。talkerで衛星系を区別する
      (GP=GPS, GL=GLONASS, GA=Galileo, GB=BeiDou, GQ=QZSS)
    - UBX NAV-PVT (class 0x01 id 0x07) : fixType・numSV(出力されていれば)
それ以外のUBXメッセージは種別ごとの件数だけ数える。

**GGA単体にはUTC日付が無い**ので、日をまたぐ(深夜0時UTC越え)長時間ログでは
時刻だけでは前後関係が決まらない。直近に見たRMCのUTC日付をGGAへ紐づけて
`datetime`化することで、日またぎでも経過時間を正しく計算する。

`screen`や`cat`での録画は、録り始め・録り終わりが必ずしもメッセージの区切りと
一致しない(先頭が受信済みバイト列の途中から始まる・Ctrl-Cで末尾が切れる)。
NMEAはチェックサム(`*hh`)、UBXはFletcher-8チェックサムをそれぞれ検証し、
壊れた行/フレームは黙って読み飛ばす(件数はサマリの最後に出す)。

使い方:
    python tools/parse_gnss_log.py path/to/capture.log
"""

from __future__ import annotations

import argparse
import datetime
import struct
import sys
from collections import Counter, defaultdict


def parse_nmea_time(hhmmss: str) -> tuple[int, int, int, int] | None:
    # "hhmmss.ss" (小数部は無いこともある)
    if len(hhmmss) < 6:
        return None
    try:
        h, m, s = int(hhmmss[0:2]), int(hhmmss[2:4]), int(hhmmss[4:6])
        frac = hhmmss[6:]
        micro = int(round(float("0" + frac) * 1_000_000)) if frac else 0
        return h, m, s, micro
    except ValueError:
        return None


def parse_rmc_date(fields: list[str]) -> datetime.date | None:
    # $..RMC,hhmmss.ss,status,lat,NS,lon,EW,sog,cog,ddmmyy,magvar,magvarEW,mode*cs
    if len(fields) < 10 or len(fields[9]) != 6:
        return None
    try:
        dd, mm, yy = int(fields[9][0:2]), int(fields[9][2:4]), int(fields[9][4:6])
        return datetime.date(2000 + yy, mm, dd)
    except ValueError:
        return None


def nmea_checksum_ok(line: str) -> bool:
    """`$...*hh` のXORチェックサムを検証する。壊れた/途中から始まる行を弾く。"""
    if not line.startswith("$"):
        return False
    body, sep, chk = line[1:].partition("*")
    if not sep or len(chk) < 2:
        return False
    try:
        expected = int(chk[:2], 16)
    except ValueError:
        return False
    actual = 0
    for ch in body:
        actual ^= ord(ch)
    return actual == expected


def parse_gga(fields: list[str]) -> dict | None:
    # $..GGA,hhmmss.ss,lat,N/S,lon,E/W,quality,numSV,HDOP,alt,M,...
    if len(fields) < 10:
        return None
    try:
        return {
            "time": fields[1],
            "quality": fields[6],
            "num_sv": int(fields[7]) if fields[7] else None,
            "hdop": float(fields[8]) if fields[8] else None,
            "alt_m": float(fields[9]) if fields[9] else None,
        }
    except ValueError:
        return None


def parse_gsv(fields: list[str]) -> list[tuple[str, int]]:
    # $..GSV,total_msgs,msg_num,num_sats_in_view,[prn,el,az,snr]*(1..4)
    if not fields or len(fields[0]) < 3:
        return []
    talker = fields[0][1:3]
    out = []
    body = fields[4:]
    for i in range(0, len(body) - 3, 4):
        snr = body[i + 3].split("*")[0]
        if snr:
            try:
                out.append((talker, int(snr)))
            except ValueError:
                pass
    return out


def ubx_checksum_ok(frame: bytes) -> bool:
    ck_a = ck_b = 0
    for b in frame[2:-2]:
        ck_a = (ck_a + b) & 0xFF
        ck_b = (ck_b + ck_a) & 0xFF
    return ck_a == frame[-2] and ck_b == frame[-1]


def iter_ubx_frames(data: bytes):
    """B5 62 syncを総当たりで拾う。録画の先頭/末尾切れで生じた偽陽性の同期は
    長さフィールドがデタラメになりやすく、ここでは境界チェックだけ行い、
    チェックサム検証は呼び出し側(summarize)に委ねる。"""
    i = 0
    n = len(data)
    while i < n - 8:
        if data[i] == 0xB5 and data[i + 1] == 0x62:
            length = struct.unpack_from("<H", data, i + 4)[0]
            total = 6 + length + 2
            if i + total > n:
                break
            yield data[i : i + total]
            i += total
        else:
            i += 1


def parse_nav_pvt(payload: bytes) -> dict | None:
    if len(payload) < 24:
        return None
    fields = struct.unpack_from("<IHBBBBBBIiBBBB", payload, 0)
    fix_type, num_sv = fields[10], fields[13]
    return {"fix_type": fix_type, "num_sv": num_sv}


def summarize(data: bytes) -> None:
    print(f"file size: {len(data)} bytes")

    gga_rows: list[dict] = []
    gsv_snr: dict[str, list[int]] = defaultdict(list)
    bad_nmea = 0
    current_date: datetime.date | None = None
    for raw_line in data.split(b"\r\n"):
        try:
            line = raw_line.decode("ascii")
        except UnicodeDecodeError:
            continue
        if not line.startswith("$"):
            # 録画開始が受信済みバイト列の途中だった場合、先頭に'$'より前の
            # 断片が残ることがある(例: 前フレームの末尾がそのまま繋がる)。
            # NMEA/UBXどちらの体裁でもないので単純に読み飛ばす。
            continue
        if not nmea_checksum_ok(line):
            bad_nmea += 1
            continue
        fields = line.split(",")
        sentence = fields[0][1:]
        if sentence.endswith("RMC"):
            d = parse_rmc_date(fields)
            if d is not None:
                current_date = d
        elif sentence.endswith("GGA"):
            row = parse_gga(fields)
            if row:
                t = parse_nmea_time(row["time"])
                if t is not None and current_date is not None:
                    h, m, s, micro = t
                    row["dt"] = datetime.datetime(
                        current_date.year, current_date.month, current_date.day,
                        h, m, s, micro, tzinfo=datetime.timezone.utc,
                    )
                else:
                    row["dt"] = None
                gga_rows.append(row)
        elif sentence.endswith("GSV"):
            for talker, snr in parse_gsv(fields):
                gsv_snr[talker].append(snr)

    print(f"\nGGA sentences: {len(gga_rows)}")
    if gga_rows:

        def fmt_row(r: dict) -> str:
            t = r["dt"].isoformat() if r["dt"] is not None else f"time={r['time']} (date不明)"
            return f"{t} quality={r['quality']} numSV={r['num_sv']} hdop={r['hdop']} alt_m={r['alt_m']}"

        print(f"  first: {fmt_row(gga_rows[0])}")
        print(f"  last:  {fmt_row(gga_rows[-1])}")
        first_dt, last_dt = gga_rows[0]["dt"], gga_rows[-1]["dt"]
        if first_dt is not None and last_dt is not None:
            print(f"  span: {last_dt - first_dt}")
        else:
            print("  span: unknown (先頭でRMCがまだ来ておらず日付が付けられなかった)")
        quality = Counter(r["quality"] for r in gga_rows)
        print(f"  quality distribution (0=no fix, 1=GPS fix, 2=DGPS): {dict(quality)}")
        num_svs = [r["num_sv"] for r in gga_rows if r["num_sv"] is not None]
        if num_svs:
            print(
                f"  numSV min/max/avg: {min(num_svs)}/{max(num_svs)}/"
                f"{sum(num_svs) / len(num_svs):.2f}"
            )
        hdops = [r["hdop"] for r in gga_rows if r["hdop"] is not None]
        if hdops:
            print(
                f"  HDOP min/max/avg: {min(hdops):.2f}/{max(hdops):.2f}/"
                f"{sum(hdops) / len(hdops):.2f}"
            )

    print("\nGSV per-satellite SNR (talker: GP=GPS, GL=GLONASS, GA=Galileo, GB=BeiDou, GQ=QZSS):")
    for talker, snrs in sorted(gsv_snr.items()):
        print(
            f"  {talker}: n={len(snrs)} snr min/max/avg = "
            f"{min(snrs)}/{max(snrs)}/{sum(snrs) / len(snrs):.1f} dB-Hz"
        )

    msg_counts: Counter[tuple[int, int]] = Counter()
    navpvt: list[dict] = []
    bad_ubx = 0
    for frame in iter_ubx_frames(data):
        if not ubx_checksum_ok(frame):
            bad_ubx += 1
            continue
        cls, idd = frame[2], frame[3]
        msg_counts[(cls, idd)] += 1
        if cls == 0x01 and idd == 0x07:
            row = parse_nav_pvt(frame[6:-2])
            if row:
                navpvt.append(row)

    print(f"\nUBX frames: {sum(msg_counts.values())} ({len(msg_counts)} message types)")
    for (cls, idd), count in sorted(msg_counts.items(), key=lambda kv: -kv[1])[:10]:
        print(f"  class=0x{cls:02X} id=0x{idd:02X} count={count}")
    if navpvt:
        fix_types = Counter(r["fix_type"] for r in navpvt)
        print(f"NAV-PVT samples: {len(navpvt)}, fixType distribution: {dict(fix_types)}")

    print(f"\nskipped (checksum failed / truncated): NMEA={bad_nmea}, UBX={bad_ubx}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", help="生シリアルログ(.ubx / screenのログ等)へのパス")
    args = ap.parse_args()

    with open(args.path, "rb") as f:
        data = f.read()
    summarize(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
