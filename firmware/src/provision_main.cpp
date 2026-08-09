// NVS(Preferences)へデバイス識別情報・秘密・ingest URLを書き込むだけの専用ビルド
// (→ docs/ota.md)。通常のfirmware(main.cpp)とは排他で、
// platformio.iniの[env:provision]だけがこれをビルドする
// (build_src_filterでmain.cppと排他、setup()/loop()の二重定義を避ける)。
//
// secrets.h(gitignore対象)を読むのはこのファイルだけにする。main.cppはもう
// secrets.hをincludeしない——公開OTAバイナリに秘密を焼き込まないため。
//
// 使い方:
//   pio run -e provision -t upload --upload-port <USBポート>  # これを焼いて1回起動
//   pio run -e record -t upload --upload-port <USBポート>     # 続けて通常のfirmwareを焼く

#include <Arduino.h>

#include "DeviceIdentity.h"
#include "secrets.h"

void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println("\n[provision] writing device identity to NVS...");

  DeviceIdentity id;
  id.deviceId = kDeviceId;
  id.wifiSsid = kWifiSsid;
  id.wifiPass = kWifiPass;
  id.hmacSecret = kHmacSecret;
  id.ingestUrl = kIngestUrl;

  bool wrote = saveDeviceIdentity(id);

  DeviceIdentity readback;
  bool verified = wrote && loadDeviceIdentity(readback) && readback.deviceId == id.deviceId &&
                  readback.hmacSecret == id.hmacSecret && readback.ingestUrl == id.ingestUrl;

  if (verified) {
    Serial.printf("[provision] OK: device %u written and verified.\n", (unsigned)id.deviceId);
    Serial.println("[provision] Now flash the normal firmware (pio run -e record -t upload).");
  } else {
    Serial.println("[provision] FAILED to write/verify NVS. Do not flash the normal firmware.");
  }
}

void loop() { delay(1000); }
