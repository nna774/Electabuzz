"""GNSS(u-blox)receiverへUBX pollリクエストを送り、現在のCFG-TP5/CFG-NAV5設定を
機械可読に読み出す。

u-centerの「Configuration View」で設定操作をした後、それがEEPROMに焼けて
実際に効いているかをGUIのスクリーンショット頼みで確認するのではなく、
receiverに直接訊いて確認するためのツール。UBXのpollは「payload無しで
そのclass/idを送ると、現在の設定がpayload付きで返ってくる」という素直な
プロトコルなので、アンテナが無くても(fixしていなくても)使える
(→ docs/log/2026-08-12-neo-m8n-ucenter-first-connection.mdのMON-VER確認と同じ性質)。

確認する2項目:
    - CFG-TP5(TIMEPULSE設定): 主眼は `lockedOtherSet` フラグ
      (立っていれば fix 喪失時も TIMEPULSE を出し続ける。→ docs/gnss.md)
    - CFG-NAV5(航法設定): 主眼は `dynModel`(2=Stationaryなら定置モード)

使い方:
    python tools/gnss_cfg_query.py --port /dev/tty.usbserial-XXXX
"""

from __future__ import annotations

import argparse
import struct
import sys
import time

try:
    import serial  # pyserial
except ImportError:
    serial = None

from parse_gnss_log import iter_ubx_frames, ubx_checksum_ok

_DYN_MODEL_NAMES = {
    0: "Portable", 2: "Stationary", 3: "Pedestrian", 4: "Automotive",
    5: "Sea", 6: "Airborne<1g", 7: "Airborne<2g", 8: "Airborne<4g",
    9: "Wrist", 10: "Bike",
}


def build_ubx(cls: int, msg_id: int, payload: bytes = b"") -> bytes:
    body = bytes([cls, msg_id]) + struct.pack("<H", len(payload)) + payload
    ck_a = ck_b = 0
    for b in body:
        ck_a = (ck_a + b) & 0xFF
        ck_b = (ck_b + ck_a) & 0xFF
    return b"\xb5\x62" + body + bytes([ck_a, ck_b])


def poll(ser: "serial.Serial", cls: int, msg_id: int, timeout_s: float = 2.0) -> bytes | None:
    """pollを送り、同じclass/idのフレームが返るまで待つ。見つからなければNone。"""
    ser.reset_input_buffer()
    ser.write(build_ubx(cls, msg_id))
    deadline = time.monotonic() + timeout_s
    buf = b""
    while time.monotonic() < deadline:
        chunk = ser.read(256)
        if chunk:
            buf += chunk
        for frame in iter_ubx_frames(buf):
            if not ubx_checksum_ok(frame):
                continue
            if frame[2] == cls and frame[3] == msg_id and len(frame) > 8:
                return frame[6:-2]  # payload
    return None


def describe_tp5(payload: bytes) -> None:
    if len(payload) < 32:
        print(f"  CFG-TP5: payload too short ({len(payload)} bytes), raw={payload.hex()}")
        return
    (tp_idx, _version) = struct.unpack_from("<BB", payload, 0)
    ant_cable_delay, rf_group_delay = struct.unpack_from("<hh", payload, 4)
    freq_period, freq_period_lock, pulse_len_ratio, pulse_len_ratio_lock = struct.unpack_from(
        "<IIII", payload, 8
    )
    user_config_delay = struct.unpack_from("<i", payload, 24)[0]
    flags = struct.unpack_from("<I", payload, 28)[0]

    def bit(n: int) -> bool:
        return bool(flags & (1 << n))

    print(f"  CFG-TP5(tpIdx={tp_idx}):")
    print(f"    freqPeriod(unlocked)={freq_period}Hz freqPeriodLock(locked)={freq_period_lock}Hz")
    print(
        f"    pulseLenRatio(unlocked)={pulse_len_ratio} pulseLenRatioLock(locked)={pulse_len_ratio_lock}"
    )
    print(f"    antCableDelay={ant_cable_delay}ns rfGroupDelay={rf_group_delay}ns userConfigDelay={user_config_delay}ns")
    print(f"    flags=0x{flags:08X}")
    print(f"      active={bit(0)}")
    print(f"      lockGnssFreq={bit(1)}")
    print(
        f"      lockedOtherSet={bit(2)}  "
        f"({'fix喪失時もTIMEPULSE継続する設定' if bit(2) else '★fix喪失時にTIMEPULSEが止まる設定のままの可能性'})"
    )
    print(f"      isFreq={bit(3)} isLength={bit(4)} alignToTow={bit(5)} polarity={bit(6)}")
    print(f"      gridUtcGnss={'GPS' if bit(7) else 'UTC'}")


def describe_nav5(payload: bytes) -> None:
    if len(payload) < 36:
        print(f"  CFG-NAV5: payload too short ({len(payload)} bytes), raw={payload.hex()}")
        return
    dyn_model = payload[2]
    fix_mode = payload[3]
    name = _DYN_MODEL_NAMES.get(dyn_model, f"unknown({dyn_model})")
    print(f"  CFG-NAV5:")
    print(
        f"    dynModel={dyn_model} ({name})  "
        f"({'定置モード' if dyn_model == 2 else '★Stationaryではない'})"
    )
    print(f"    fixMode={fix_mode} (1=2D only, 2=3D only, 3=auto 2D/3D)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", required=True, help="GNSSモジュールに繋いだUSB-TTLアダプタのシリアルポート")
    ap.add_argument("--baud", type=int, default=9600, help="u-bloxの既定ボーレート")
    args = ap.parse_args()

    if serial is None:
        print("pyserial未インストール: pip install pyserial", file=sys.stderr)
        return 1

    ser = serial.Serial(args.port, args.baud, timeout=0.2)
    try:
        print("polling CFG-TP5 (class=0x06 id=0x31)...")
        tp5 = poll(ser, 0x06, 0x31)
        if tp5 is None:
            print("  応答なし(タイムアウト)。配線・ボーレート・電源を確認しろ")
        else:
            describe_tp5(tp5)

        print("\npolling CFG-NAV5 (class=0x06 id=0x24)...")
        nav5 = poll(ser, 0x06, 0x24)
        if nav5 is None:
            print("  応答なし(タイムアウト)。配線・ボーレート・電源を確認しろ")
        else:
            describe_nav5(nav5)
    finally:
        ser.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
