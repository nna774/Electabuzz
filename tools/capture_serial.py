"""ファームウェア(NAMZ_GRIDFREQ_TEST)のシリアル出力をCSVに保存する。

ファーム側は `firmware/src/config.h` の `kGridFreqTestDecimate`(既定48)で間引いた
L/R生コードを `t_us,l,r` で1行1サンプル出力する想定。実効レートは概ね
48000/kGridFreqTestDecimate Hz(既定1000Hz)だが、**キャリブレーション前の値**
（fsの真値はNtpTimebaseでしか測れない。→ docs/timebase.md）。

使い方:
    pio run -e gridfreqtest -d firmware -t upload
    python tools/capture_serial.py --port /dev/tty.usbmodemXXXX --seconds 30 > cap.csv
"""

from __future__ import annotations

import argparse
import sys
import time

try:
    import serial  # pyserial
except ImportError:
    serial = None


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--port", required=True)
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--seconds", type=float, default=30.0)
    args = p.parse_args()

    if serial is None:
        print("pyserial未インストール: pip install pyserial", file=sys.stderr)
        return 1

    ser = serial.Serial(args.port, args.baud, timeout=1)
    # ESP32の自動リセット回路を明示的に叩く(pyserialの既定DTR/RTS状態のままだと
    # 開いた瞬間にリセットされるとは限らず、起動直後の出力を取りこぼす)。
    ser.dtr = False
    ser.rts = True
    time.sleep(0.1)
    ser.rts = False

    print("t_us,l,r")
    deadline = None
    started = False
    n = 0
    while True:
        line = ser.readline().decode("ascii", "ignore").strip()
        if not line:
            if started and deadline is not None and time.monotonic() >= deadline:
                break
            continue
        if line.startswith("#"):
            print(line, file=sys.stderr)
            continue
        parts = line.split(",")
        if len(parts) != 3:
            continue
        try:
            t_us = int(parts[0])
            l = int(parts[1])
            r = int(parts[2])
        except ValueError:
            continue
        if not started:
            started = True
            deadline = time.monotonic() + args.seconds
        print(f"{t_us},{l},{r}")
        n += 1
        if deadline is not None and time.monotonic() >= deadline:
            break
    ser.close()
    print(f"[capture] {n} samples", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
