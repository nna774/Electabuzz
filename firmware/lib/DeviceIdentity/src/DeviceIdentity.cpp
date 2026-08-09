#include "DeviceIdentity.h"

#include <Preferences.h>

namespace {
// main.cppがsession_id(起動ごとの通し番号)で使っているのと同じnamespace。
// 1台のNVS上に混在させて問題ない(Preferencesはnamespace内でkey単位に分かれる)。
constexpr const char* kNamespace = "electabuzz";
}  // namespace

bool loadDeviceIdentity(DeviceIdentity& out) {
  Preferences prefs;
  if (!prefs.begin(kNamespace, /*readOnly=*/true)) return false;
  out.deviceId = prefs.getUInt("device_id", 0);
  out.wifiSsid = prefs.getString("wifi_ssid", "");
  out.wifiPass = prefs.getString("wifi_pass", "");
  out.hmacSecret = prefs.getString("hmac_secret", "");
  out.ingestUrl = prefs.getString("ingest_url", "");
  prefs.end();
  return out.deviceId != 0 && out.wifiSsid.length() > 0 && out.hmacSecret.length() > 0 &&
         out.ingestUrl.length() > 0;
}

bool saveDeviceIdentity(const DeviceIdentity& in) {
  Preferences prefs;
  if (!prefs.begin(kNamespace, /*readOnly=*/false)) return false;
  prefs.putUInt("device_id", in.deviceId);
  prefs.putString("wifi_ssid", in.wifiSsid);
  prefs.putString("wifi_pass", in.wifiPass);
  prefs.putString("hmac_secret", in.hmacSecret);
  prefs.putString("ingest_url", in.ingestUrl);
  prefs.end();
  return true;
}
