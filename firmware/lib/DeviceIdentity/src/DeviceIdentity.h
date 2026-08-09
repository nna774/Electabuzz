#pragma once
// デバイス固有の識別情報・秘密・ingest URL。
//
// コンパイル時定数(旧: main.cppがsecrets.hを直接includeしていた形)としては
// 埋め込まず、NVS(Preferences)に持つ。理由(→ docs/ota.md):
// pull型OTAは env ごとに1本のバイナリを公開URL(CloudFront)へ置く。WiFiパスワードや
// 投稿用HMAC鍵がバイナリに平文で焼き込まれていると、公開した瞬間その1台の家WiFiと
// なりすまし投稿の鍵を世界に漏らすことになる。OTAはappパーティションのみを
// 書き換えNVSには触らないため、ここに置けばOTAをまたいで保持され、かつ公開
// バイナリ自体には何も残らない（Namazuと同じ設計、→ CLAUDE.md不変条件ではないが
// open-questions.mdの既定路線）。
//
// 書き込みは初回USB書き込み時、専用の provision ビルド(firmware/src/provision_main.cpp、
// [env:provision])から1回だけ行う。secrets.h(gitignore対象)はprovision_main.cppだけが
// includeし、通常のfirmware(main.cpp)はもう secrets.h を読まない。

#include <Arduino.h>

struct DeviceIdentity {
  uint32_t deviceId = 0;
  String wifiSsid;
  String wifiPass;
  String hmacSecret;
  String ingestUrl;
};

// NVSから読む。deviceId/wifiSsid/hmacSecret/ingestUrlのいずれかが空(未設定)なら
// 未プロビジョニングとみなしfalseを返す——呼び出し側は起動を止めるべきで、
// 空文字列のままWiFi.begin()等を呼んで不定動作にしてはいけない。
bool loadDeviceIdentity(DeviceIdentity& out);

// NVSへ書く。provision専用ビルドから呼ぶ。
bool saveDeviceIdentity(const DeviceIdentity& in);
