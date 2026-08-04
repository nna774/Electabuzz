#!/usr/bin/env python3
"""フェーズ1.5 soak のシリアル出力を取りこぼさず追記する。

`pio device monitor` を使わない理由は2つある。

1. **pyserial は既定で DTR/RTS を立てて開く。** ESP32 の自動リセット回路は
   この2本で EN と IO0 を叩くので、素直に開くと基板をリセット状態に握ったまま
   一文字も出てこない（実際に踏んだ）。ここでは開く前に両方を落とす。
2. 走り続ける soak を tty 無しの環境から回したい。

**接続すると基板はリセットされる。** macOS はポートを開く時点で DTR/RTS を
立ててしまい、pyserial 側で先に落としても間に合わない（実測: 開くたびに
`rst:0x1 (POWERON)` が出る）。したがって `NtpTimebase` の回帰は接続のたびに
ゼロから積み直しになる。**繋いだら放っておけ。用も無く繋ぎ直すな。**

ただしこれは致命傷ではない。ppm の推定は数時間で十分な精度に達するので、
**区間が切れても各区間ごとに ppm が出る**。切れ目は CSV 中の
`# capture: attached` と起動バナーで判別できるので、解析側はそこで区切ればよい。

    tools/soak_capture.py /dev/cu.usbmodemXXXX soak/soak-20260804.csv
"""

import datetime
import sys
import time

import serial


def open_port(port: str) -> serial.Serial:
    ser = serial.Serial()
    ser.port = port
    ser.baudrate = 115200
    ser.timeout = 1.0
    # **開く前に落とす。** open() 後では既に一度立ってしまっている。
    ser.dtr = False
    ser.rts = False
    ser.open()
    return ser


def main() -> int:
    if len(sys.argv) != 3:
        sys.stderr.write(__doc__ or "")
        return 2
    port, path = sys.argv[1], sys.argv[2]

    while True:
        try:
            ser = open_port(port)
        except (serial.SerialException, OSError) as e:
            # 抜けている・別プロセスが握っている。諦めずに待つ。
            with open(path, "ab", buffering=0) as f:
                f.write(f"# capture: cannot open {port}: {e}\n".encode())
            time.sleep(5)
            continue

        stamp = datetime.datetime.now().astimezone().isoformat()
        with open(path, "ab", buffering=0) as f:
            f.write(f"# capture: attached {stamp}\n".encode())
            try:
                while True:
                    line = ser.readline()
                    if line:
                        f.write(line)
            except (serial.SerialException, OSError) as e:
                f.write(f"# capture: detached {e}\n".encode())
        try:
            ser.close()
        except Exception:
            pass
        time.sleep(5)


if __name__ == "__main__":
    sys.exit(main())
