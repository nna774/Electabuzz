// Electabuzz ファームウェア — フェーズ1.5「時間基準と `fs` の同時実測」
//
// **測っているものが2つある。両方を同じ NTP 標本から出す。**
//
//   gXtal : ティック源 = esp_timer(µs) → **ESP32 の 40MHz 水晶**の実 ppm
//   gFs   : ティック源 = I2S の累積フレーム数 → **`fs` そのもの**の実 ppm
//
// この2つを並べることが目的だ。**構成上は同じ水晶から出ているはずなので、
// 両者は各々の residual の範囲で一致しなければならない**（SCKI は ESP32 の MCLK で、
// MCLK も esp_timer の systimer も 40MHz 水晶に lock した PLL から出ている）。
// 一致しなければ配線かクロック経路が想定と違う。→ docs/hardware.md, docs/timebase.md
//
// gXtal は 2026-08-04〜05 の soak で **+3.8873 ± 0.0055 ppm** が出ている。
// **これが gFs の答え合わせになる。**
//
// NtpTimebase はティック源を問わないので、この2本立ては同じクラスの2インスタンスで済む。
//
// ## 注意: フレーム数だけでは PCM1808 が居ることを証明できない
//
// **ESP32 が I2S のマスタなので、PCM1808 が繋がっていなくても BCK/LRCK は出る。**
// i2s_read はゼロのフレームを返し続け、フレーム数は何事もなく進み、`fs` は綺麗な値を
// 出す。**配線していなくても「測れた」ように見えるということだ。**
// なので L/R の振幅（l_pp / r_pp）を毎行に載せる。**ここが 0 なら DOUT が死んでいる。**
//
// 出力は CSV。捕捉は tools/soak_capture.py を使え。

#include <Arduino.h>
#include <HTTPUpdate.h>
#include <Preferences.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <driver/i2s.h>
#include <esp_timer.h>

#include <algorithm>
#include <atomic>

#include "DeviceIdentity.h"
#include "Goertzel.h"
#include "GridFreqWire.h"
#include "LedStatus.h"
#include "MeasuringSntp.h"
#include "NtpTimebase.h"
#include "TimeSync.h"
#include "Uploader.h"
#include "config.h"

// pull型OTA(docs/ota.md)のビルドバージョン一致判定に使う。get_fw_version.pyが
// 常に注入するが、何らかの理由で注入されなかった時のfallback。
#ifndef ELBZ_FW_VERSION
#define ELBZ_FW_VERSION "unknown"
#endif

namespace {

// **単調増加するティック源。** システム時刻ではない。
// esp_timer は NTP に触られないので、これが「生の水晶」に一番近い。
uint64_t ticksNow() { return static_cast<uint64_t>(esp_timer_get_time()); }

timebase::NtpTimebase gXtal(kTickNominalMicroHz);
timebase::NtpTimebase gFs(kFsNominalMicroHz);
timebase::MeasuringSntp gSntp;
size_t gServerIndex = 0;
uint32_t gNextQueryMs = 0;

// WiFi SSID/パス・デバイスID・HMAC鍵・ingest URL。NVS(Preferences)からロードする
// （旧secrets.h。コンパイル時に埋め込まない理由は docs/ota.md）。
// ensureWifi()を呼ぶ全モード(record・soak v2)が共有し、各setup()の先頭で
// loadDeviceIdentity()に成功してから使う。
DeviceIdentity gIdentity;

// --- I2S 側。専用タスク（Core1）が書き、Core0 が読む ---
portMUX_TYPE gI2sMux = portMUX_INITIALIZER_UNLOCKED;
uint64_t gFrames = 0;      // 起動からの累積フレーム数（= LRCK の回数）
uint64_t gFramesAtUs = 0;  // 上を更新した時点の esp_timer [µs]
uint32_t gOverflows = 0;   // DMA 溢れの回数。**0 でなければ fs は信用するな**
int32_t gLMin = 0, gLMax = 0, gRMin = 0, gRMax = 0;  // 報告ごとにリセットする
bool gHaveMinMax = false;
QueueHandle_t gI2sQueue = nullptr;

// --- NAMZ_GRIDFREQ_RECORD 専用。他モードでは null のままで何も起きない ---
//
// pumpI2s() に直接組み込むのは、DMA吸い出しと同じ場所で L ch サンプルを
// 一度だけ舐めるため（別バッファへコピーし直すコストを避ける）。
// std::atomic にしてあるのは、Core0（fs がロックした瞬間に生成する）から
// Core1（i2sTask で毎回読む）への書き込みをポインタ単位で安全に見せるため。
std::atomic<gridfreq::GoertzelEstimator*> gRecordGoertzel{nullptr};
struct WindowRecord {
  uint64_t cyclesQ16;
  // この窓が完成した**瞬間**の累積フレーム数（gFrames）。pumpI2s() が確定させる。
  // **Core0 が xQueueReceive で受け取った時刻を使ってはいけない**——NTP問い合わせ
  // (gSntp.query()、最大 kNtpTimeoutMs ブロックしうる)等で loop() が遅延すると、
  // その遅延がそのままバッチ起点のタイムスタンプに乗ってしまう
  // （→ docs/log/2026-08-08-batch-boundary-timestamp-jump.md の再発版）。
  uint64_t framesAtEnd;
  bool discontinuity;  // DMA 溢れの直後に確定した窓か（gI2sMux で保護）
};
QueueHandle_t gWindowQueue = nullptr;
bool gPendingDiscontinuity = false;  // gI2sMux で保護する

struct I2sSnapshot {
  uint64_t frames;
  uint64_t atUs;
  uint32_t overflows;
  uint32_t lPp;
  uint32_t rPp;
};

// %llu が newlib の設定で死んでいても数日ぶんの記録を失わないよう、自前で書く。
const char* u64str(uint64_t v, char* buf, size_t n) {
  char tmp[21];
  size_t i = 0;
  do {
    tmp[i++] = static_cast<char>('0' + (v % 10));
    v /= 10;
  } while (v != 0 && i < sizeof(tmp));
  size_t j = 0;
  while (i > 0 && j + 1 < n) buf[j++] = tmp[--i];
  buf[j] = '\0';
  return buf;
}

bool startI2s() {
  // **ステレオで初期化する。R ch に何も繋がっていなくても同じ。**
  // ここだけが後戻りできない（→ CLAUDE.md の不変条件）。R ch は GNSS の 1PPS 用だ。
  i2s_config_t cfg = {};
  cfg.mode = static_cast<i2s_mode_t>(I2S_MODE_MASTER | I2S_MODE_RX);
  cfg.sample_rate = kFsNominalHz;  // **要求であって真値ではない。測るのは gFs だ**
  cfg.bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT;
  cfg.channel_format = I2S_CHANNEL_FMT_RIGHT_LEFT;  // ステレオ
  cfg.communication_format = I2S_COMM_FORMAT_STAND_I2S;
  cfg.intr_alloc_flags = ESP_INTR_FLAG_LEVEL1;
  cfg.dma_buf_count = kI2sDmaBufCount;
  cfg.dma_buf_len = kI2sDmaBufFrames;
  cfg.use_apll = false;  // **S3 に APLL は無い**（→ docs/hardware.md）
  cfg.tx_desc_auto_clear = false;
  cfg.fixed_mclk = 0;
  cfg.mclk_multiple = I2S_MCLK_MULTIPLE_256;  // SCKI = 256 fs。PCM1808 が自動判別する
  cfg.bits_per_chan = I2S_BITS_PER_CHAN_32BIT;  // 2ch × 32bit = 64 BCK/frame

  // イベントキューを取る。**溢れを黙って見逃さないため**で、これが本題だ。
  esp_err_t err = i2s_driver_install(I2S_NUM_0, &cfg, 8, &gI2sQueue);
  if (err != ESP_OK) {
    Serial.printf("# i2s_driver_install failed: %d\n", static_cast<int>(err));
    return false;
  }

  i2s_pin_config_t pins = {};
  pins.mck_io_num = kI2sPinMclk;
  pins.bck_io_num = kI2sPinBclk;
  pins.ws_io_num = kI2sPinLrck;
  pins.data_out_num = I2S_PIN_NO_CHANGE;
  pins.data_in_num = kI2sPinData;
  err = i2s_set_pin(I2S_NUM_0, &pins);
  if (err != ESP_OK) {
    Serial.printf("# i2s_set_pin failed: %d\n", static_cast<int>(err));
    return false;
  }
  return true;
}

// I2S を吸い出してフレーム数を進める。**中身は捨てる**（振幅だけ見る）。
// 今測りたいのは「何個出てきたか」であって波形ではない。
void pumpI2s() {
  static int32_t buf[kI2sReadFrames * 2];

  // 溢れを先に拾う。**溢れた = 読めなかったフレームがある = ティック源が飛んだ。**
  i2s_event_t ev;
  while (gI2sQueue != nullptr && xQueueReceive(gI2sQueue, &ev, 0) == pdTRUE) {
    if (ev.type == I2S_EVENT_RX_Q_OVF) {
      portENTER_CRITICAL(&gI2sMux);
      ++gOverflows;
      gPendingDiscontinuity = true;
      portEXIT_CRITICAL(&gI2sMux);
      // 記録モードでは進行中の窓と「直前の位相」の参照を捨てる。
      // **cyclesQ16 は巻き戻さない**——欠測区間をまたいだ分は
      // GfrqFlagDiscontinuity で正直に申告する(→ Goertzel.h)。
      gridfreq::GoertzelEstimator* g = gRecordGoertzel.load(std::memory_order_relaxed);
      if (g != nullptr) g->resetWindow();
    }
  }

  for (;;) {
    size_t got = 0;
    if (i2s_read(I2S_NUM_0, buf, sizeof(buf), &got, 0) != ESP_OK || got == 0) return;
    const size_t frames = got / (sizeof(int32_t) * 2);

    // この read で埋まる分の gFrames はまだ加算していない。
    // **gFrames の書き手は pumpI2s()（Core1）だけ**なのでロック無しで読んでよい
    // （他コアからの書き込みは無い。ロックが要るのは読み手側の takeI2sSnapshot()
    // ／currentFramesEstimate() が torn read を避けるためだけ）。
    const uint64_t framesBeforeThisRead = gFrames;

    // 24bit が 32bit 枠に MSB 詰めで来る（I2S 標準フォーマット）。算術シフトで戻す。
    int32_t lMin = INT32_MAX, lMax = INT32_MIN, rMin = INT32_MAX, rMax = INT32_MIN;
    for (size_t i = 0; i < frames; ++i) {
      const int32_t l = buf[i * 2] >> 8;
      const int32_t r = buf[i * 2 + 1] >> 8;
      if (l < lMin) lMin = l;
      if (l > lMax) lMax = l;
      if (r < rMin) rMin = r;
      if (r > rMax) rMax = r;

      // 記録モードでのみ非null。他モードはロード1回ぶんのコストで済む。
      gridfreq::GoertzelEstimator* g = gRecordGoertzel.load(std::memory_order_relaxed);
      if (g != nullptr && g->addSample(l)) {
        WindowRecord rec{};
        rec.cyclesQ16 = g->cyclesQ16();
        // **窓が完成した「その瞬間」のフレーム数。** Core0 がこのレコードを
        // xQueueReceive するまでの遅延（NTP問い合わせ等）に一切依存しない。
        rec.framesAtEnd = framesBeforeThisRead + i + 1;
        portENTER_CRITICAL(&gI2sMux);
        rec.discontinuity = gPendingDiscontinuity;
        gPendingDiscontinuity = false;
        portEXIT_CRITICAL(&gI2sMux);
        if (gWindowQueue != nullptr && xQueueSend(gWindowQueue, &rec, 0) != pdTRUE) {
          // 送信側が詰まっていて空きが無い。**古い方を消す**——最新の窓を
          // 失うより、少し前の1件を失う方がまだ実害が小さい。
          WindowRecord discard;
          xQueueReceive(gWindowQueue, &discard, 0);
          xQueueSend(gWindowQueue, &rec, 0);
        }
      }
    }

    const uint64_t now = ticksNow();
    portENTER_CRITICAL(&gI2sMux);
    gFrames += frames;
    gFramesAtUs = now;
    if (!gHaveMinMax) {
      gLMin = lMin; gLMax = lMax; gRMin = rMin; gRMax = rMax;
      gHaveMinMax = true;
    } else {
      if (lMin < gLMin) gLMin = lMin;
      if (lMax > gLMax) gLMax = lMax;
      if (rMin < gRMin) gRMin = rMin;
      if (rMax > gRMax) gRMax = rMax;
    }
    portEXIT_CRITICAL(&gI2sMux);

    if (got < sizeof(buf)) return;  // 溜まっていたぶんは掃けた
  }
}

// **Core1 に置く。** WiFi と SNTP は Core0 で最大2秒ブロックしうるので、
// 同じループに置くと DMA が溢れる（= fs の回帰が壊れる）。
void i2sTask(void*) {
  for (;;) {
    pumpI2s();
    vTaskDelay(pdMS_TO_TICKS(kI2sPumpIntervalMs));
  }
}

// 振幅は読むたびにリセットする（前回の報告以降のピークが欲しいので）。
I2sSnapshot takeI2sSnapshot() {
  I2sSnapshot s{};
  portENTER_CRITICAL(&gI2sMux);
  s.frames = gFrames;
  s.atUs = gFramesAtUs;
  s.overflows = gOverflows;
  s.lPp = gHaveMinMax ? static_cast<uint32_t>(gLMax - gLMin) : 0;
  s.rPp = gHaveMinMax ? static_cast<uint32_t>(gRMax - gRMin) : 0;
  gHaveMinMax = false;
  portEXIT_CRITICAL(&gI2sMux);
  return s;
}

// SNTP 標本の時刻（esp_timer µs）におけるフレーム数を線形で外挿する。
//
// スナップショットは標本の**あと**に取れるので、たいてい数十 ms ぶん巻き戻す。
// **公称 fs を使っているが、これは許される用途だ**: 外挿区間が 30ms 級なので、
// 公称値が 1000ppm 狂っていても誤差は 30µs にしかならず、経路ノイズ（数 ms）の
// はるか下にある。**長期の傾きは実測のフレーム数が決めており、ここは効かない。**
uint64_t framesAt(const I2sSnapshot& s, uint64_t atUs) {
  const int64_t dUs = static_cast<int64_t>(atUs) - static_cast<int64_t>(s.atUs);
  const int64_t dFrames = (dUs * static_cast<int64_t>(kFsNominalHz)) / 1000000;
  const int64_t v = static_cast<int64_t>(s.frames) + dFrames;
  return v > 0 ? static_cast<uint64_t>(v) : 0;
}

double ppmOf(const timebase::NtpTimebase& tb, uint64_t nominalMicroHz) {
  return (static_cast<double>(tb.fsMicroHz()) / static_cast<double>(nominalMicroHz) - 1.0) * 1e6;
}

void ensureWifi() {
  if (WiFi.status() == WL_CONNECTED) return;
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);  // 省電力で受信が遅れると往復遅延の分布が汚れる
  WiFi.begin(gIdentity.wifiSsid.c_str(), gIdentity.wifiPass.c_str());
  const uint32_t deadline = millis() + kWifiConnectTimeoutMs;
  while (WiFi.status() != WL_CONNECTED && static_cast<int32_t>(millis() - deadline) < 0) {
    delay(200);
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("# wifi connected ip=%s rssi=%d\n", WiFi.localIP().toString().c_str(),
                  WiFi.RSSI());
    gSntp.begin(ticksNow);
  } else {
    Serial.println("# wifi connect failed");
    delay(kWifiRetryDelayMs);
  }
}

// NVSからデバイス識別情報をロードする。空(未プロビジョニング)なら起動を止める
// ——不定なWiFi/HMAC鍵のまま動かさない（→ DeviceIdentity.h）。
// ensureWifi()を呼ぶsetup()(record・soak v2)は、その前に必ずこれを呼ぶこと。
void loadIdentityOrHalt() {
  if (loadDeviceIdentity(gIdentity)) return;
  Serial.println("# device identity not provisioned (NVS empty); halting. "
                  "flash [env:provision] first.");
  while (true) delay(1000);
}

void logLine(const char* server, bool ok, const char* err, const timebase::SntpSample& s,
             const I2sSnapshot& i2s, uint64_t frames) {
  char b1[24], b2[24], b3[24], b4[24];
  Serial.printf("%s,%s,%s,%s,%s,%d,%s,%u,%u,%.1f,%s,%.4f,%u,%u,%u,%.1f,%d,"
                "%s,%u,%.4f,%u,%u,%u,%u,%u\n",
                u64str(ticksNow(), b1, sizeof(b1)),
                ok ? u64str(s.unixUs, b2, sizeof(b2)) : "",
                ok ? u64str(s.ticks, b3, sizeof(b3)) : "",
                ok ? String(static_cast<uint32_t>(s.rttTicks)).c_str() : "",
                server, ok ? 1 : 0, err,
                gXtal.obsCount(), gXtal.rejectedCount(), gXtal.spanSeconds(),
                gXtal.source() == timebase::Source::kNtp ? "NTP" : "NOMINAL",
                ppmOf(gXtal, kTickNominalMicroHz), gXtal.residualNs(), gXtal.fitRmsNs(),
                gXtal.minRttUs(), temperatureRead(), WiFi.RSSI(),
                // --- ここから fs 側 ---
                u64str(frames, b4, sizeof(b4)),
                gFs.obsCount(), ppmOf(gFs, kFsNominalMicroHz), gFs.residualNs(), gFs.fitRmsNs(),
                i2s.overflows, i2s.lPp, i2s.rPp);
}

}  // namespace

#if defined(NAMZ_GRIDFREQ_RECORD)
// NAMZ_GRIDFREQ_RECORD を定義してビルドすると、フェーズ2(PPS同時サンプリング)を
// 待たずに実測・記録・送信を始める。**timebase_source はそのバッチ時点の
// gFs.source()を正直に申告する**——PPS を名乗ることは無い。Goertzelの計算自体は
// Lチャンネルの生サンプルだけで完結し、PPS(方式A/B)の選択には一切触れないので、
// C++移植をフェーズ2待ちにする理由が無いと判断した経緯は
// docs/log/2026-08-07-goertzel-cpp-port.md にある。
//
// **NTPロックも待たない(2026-08-08決定)**: 起動直後は公称fsでGoertzelを
// 動かし始め、timebase_source=NOMINALと正直に申告して記録・送信する。
// fsがNtpTimebaseで規正できた(NtpTimebase::kMinSpanSeconds=600秒)瞬間に
// 規正済みfsで推定器を作り直し、以後はNTPと申告する。
// **「測れなかった区間を測れたように見せない」不変条件は、値を出さないのではなく
// 正直にNOMINALと申告することで守る**——cloud側がNOMINAL区間を後から
// スカラー補正できることを線形性検証で確かめた上での判断(→
// docs/log/2026-08-08-nominal-window-open-question.md)。DMAが溢れたら
// 該当バッチにGfrqFlagDiscontinuityを立てる(→ pumpI2s() 内の resetWindow() 呼び出し)。

namespace {

Preferences gPrefs;
uint32_t gSessionId = 0;
double gFNominalHz = 0.0;  // 0 = 未判別
Uploader* gUploader = nullptr;
Batch* gCurrentBatch = nullptr;
bool gBatchDiscontinuity = false;
// 前回ループ時点でgFs.source()がNTPだったか。NOMINAL→NTPへの遷移だけを
// エッジ検出してGoertzelを作り直すために使う。tick逆行によるgFs.reset()で
// 理論上NOMINALへ戻ることがあるが、その場合は素直にfalseへ戻り、
// 再ロック時にまた作り直しが起きるだけでよい。
bool gFsSourceWasNtp = false;

// NOMINAL区間のバッチ起点計算用アンカー。**timesync::isSynced()が初めてtrueに
// なった瞬間に遅延取得する**(0 = 未取得)。setup()の時点で無条件に読むと、
// SNTPの初回同期がまだ済んでいない場合(実測で発生した——WiFi接続直後は
// timesync::nowUs()が1970年付近を返す)、その悪い値がセッション全体に固定
// されてしまう。遅延取得なら、初回同期が済むまでの数バッチだけ悪い値が出て
// (旧来のtimesync都度読みと同程度の影響に留まる)、以後は良いアンカーで
// 一貫する。gNominalAnchorFramesは対応する時点のrec.framesAtEnd。
// **以後はこのアンカー+公称fsによる外挿だけでバッチ起点を計算し、
// timesync::nowUs() を都度読み直さない**——都度読み直すとSNTPのslew補正
// ジッタ(数ms級)がバッチ境界のたびに乗り、freq=Δcycles/Δtの計算がそれを
// 増幅して数十〜100mHz級の針として現れる(NTPロック済み区間をunixUsAt()化
// した際と同じ理屈。gFsの回帰にはNOMINAL中使える代物が無いので、代わりに
// 「公称fsそのものを固定レート源として使う」)。
// 絶対時刻としての確度は主張しない(NOMINALはそもそも未規正)。効くのは
// **同一アンカーからの一貫した外挿によりバッチ境界の相対時間が正確になること**だけ。
uint64_t gNominalAnchorUnixUs = 0;  // 0 = 未取得
uint64_t gNominalAnchorFrames = 0;  // アンカー取得時点のrec.framesAtEnd

// --- pull型OTA（→ docs/ota.md）---
//
// バッチ送信レスポンスへの便乗で気づく。ingestはELBZ_OTA_TARGET_VERSION環境変数
// (terraform)が設定されていれば、バッチPOSTのたびにこのヘッダを返す
// （一回性ではない——デバイスのビルドバージョンと一致するまで返し続けるので、
// 取得・書き込み失敗時の自然なリトライにもなる。Namazuと同じ設計）。
// Uploaderは「指定したヘッダの値を読んで返す」だけの汎用API(v1.6.0)で、
// 意味づけはここが持つ。
constexpr const char* kOtaVersionHeader = "X-Elbz-Ota-Version";
constexpr const char* kOtaWatchedHeaders[] = {kOtaVersionHeader};

// リクエスト側に乗せて送るヘッダ。今のビルド版数・空きヒープ・起動からの経過を
// 毎バッチingestへ渡す——GFRQのワイヤ形式(testdata/gfrq_v1_golden.hexで固定された
// 契約)には運用情報を足さず、HTTPヘッダという別チャネルで運ぶ
// （ingestは現状これをCloudWatchログへ出すだけで、生存台帳が無いので保存はしない）。
constexpr const char* kFwVersionHeader = "X-Elbz-Fw-Version";
constexpr const char* kHeapFreeHeader = "X-Elbz-Heap-Free";
constexpr const char* kUptimeHeader = "X-Elbz-Uptime-Us";
constexpr const char* kTelemetryHeaderNames[] = {kFwVersionHeader, kHeapFreeHeader, kUptimeHeader};
char sFwVersionBuf[32];  // setup()で一度だけ埋める(ビルド中に変わらない)
char sHeapFreeBuf[16];   // loop()が送信直前に毎周更新する
char sUptimeBuf[24];
const char* kTelemetryHeaderValues[] = {sFwVersionBuf, sHeapFreeBuf, sUptimeBuf};

// firmware/certs/amazon_root_ca1.pem を platformio.ini の board_build.embed_txtfiles
// でリンクしたバイナリの先頭/終端。
extern const uint8_t amazon_root_ca1_pem_start[] asm("_binary_certs_amazon_root_ca1_pem_start");
extern const uint8_t amazon_root_ca1_pem_end[] asm("_binary_certs_amazon_root_ca1_pem_end");

// OTA前にRAMキューをLittleFSへ退避する。フラッシュ書き込み中はキャッシュが
// 無効になり両コアの命令フェッチが止まるため(数百ms〜数秒)、その間I2Sの
// DMAは取りこぼしうる——それ自体はpumpI2s()のオーバーフロー検出で
// GfrqFlagDiscontinuityとして正直に申告されるので構わないが、RAM上の
// 送信待ちバッチはESP.restart()で消える。事前にspillへ落として
// Uploaderの不変条件「2xxが返るまで捨てない」を守る。
void flushBeforeOta() {
  size_t flushed = gUploader->flushToSpill();
  Serial.printf("# ota: flushed %u batch(es) to spill\n", static_cast<unsigned>(flushed));
}

// OTA本体を取得して書き込む。成功ならtrue(呼び出し側がESP.restart()する)。
// TLS検証はAmazon Root CA 1を明示指定する（ダッシュボード配信のCloudFrontと
// 同じ証明書チェーンであることをopenssl s_clientで確認済み。→ docs/ota.md）。
bool performPullOta(const String& targetVersion) {
  char url[256];
  snprintf(url, sizeof(url), "%s/ota/record/%s.bin", kOtaBaseUrl, targetVersion.c_str());
  Serial.printf("# ota: fetching %s\n", url);

  WiFiClientSecure client;
  client.setCACert(reinterpret_cast<const char*>(amazon_root_ca1_pem_start));
  httpUpdate.rebootOnUpdate(false);  // 再起動は呼び出し側(checkAndPerformOta)で制御する

  t_httpUpdate_return ret = httpUpdate.update(client, url);
  if (ret != HTTP_UPDATE_OK) {
    Serial.printf("# ota: failed %d (%s)\n", static_cast<int>(ret),
                  httpUpdate.getLastErrorString().c_str());
    return false;
  }
  Serial.println("# ota: write OK, restarting");
  Serial.flush();
  return true;
}

// バージョン不一致を見つけたら、退避→取得→(成功なら再起動/失敗ならバックオフ)
// まで一息に行う。loop()がバッチ送信レスポンスを見た時に毎周呼ぶ。
// バックオフが無いとloop()の周期(NTP待ちが無い時は数十ms)ごとに取得を
// 再試行し、そのたびにflushBeforeOtaが走り続ける(Namazuが実機で踏んだ
// 不具合と同じ原因。→ docs/ota.md「実機で踏んだ不具合」、config.hのコメント参照)。
void checkAndPerformOta(const String& target) {
  static int64_t sNextAttemptUs = 0;
  if (target.length() == 0 || target == ELBZ_FW_VERSION) return;
  const int64_t now = esp_timer_get_time();
  if (now < sNextAttemptUs) return;
  Serial.printf("# ota: update available %s -> %s\n", ELBZ_FW_VERSION, target.c_str());
  flushBeforeOta();
  if (performPullOta(target)) {
    delay(200);
    ESP.restart();
  } else {
    sNextAttemptUs = now + kOtaRetryBackoffUs;
  }
}

}  // namespace

void setup() {
  Serial.begin(kSerialBaud);
  delay(500);
  Serial.println();
  Serial.println("# electabuzz gridfreq record (PPS/NTPロックとも待たず開始。"
                  "timebase_sourceはgFs.source()を正直に申告)");
  Serial.printf("# fw_version=%s\n", ELBZ_FW_VERSION);

  loadIdentityOrHalt();

  gPrefs.begin("electabuzz", false);
  gSessionId = gPrefs.getUInt("session_id", 0) + 1;
  gPrefs.putUInt("session_id", gSessionId);
  gPrefs.end();
  Serial.printf("# session_id=%u\n", gSessionId);

  // 物理LEDの色に「赤=警告」の慣習を合わせる: kLedWifiPinは赤LED前提で
  // 「切断中に点灯」(問題がある時だけ光る)。他2本は緑/黄LED前提で
  // 「その状態の時に点灯」(健全・進行中を素直に示す)。
  pinMode(kLedWifiPin, OUTPUT);
  pinMode(kLedTimebaseLockPin, OUTPUT);
  pinMode(kLedSpillBacklogPin, OUTPUT);
  pinMode(kLedFastSlowPin, OUTPUT);
  digitalWrite(kLedWifiPin, HIGH);  // WiFi接続が確立するまでは「切断中」を表す点灯
  digitalWrite(kLedTimebaseLockPin, LOW);
  digitalWrite(kLedSpillBacklogPin, LOW);
  digitalWrite(kLedFastSlowPin, LOW);

  ensureWifi();
  timesync::begin(kNtpServers[0], kNtpServers[1],
                   static_cast<uint64_t>(kTimeSyncStepThresholdSeconds) * 1000000ULL);

  if (!startI2s()) {
    Serial.println("# i2s init failed");
    while (true) delay(1000);
  }
  Serial.printf("# i2s pins: mclk=%d bclk=%d lrck=%d din=%d\n", kI2sPinMclk, kI2sPinBclk,
                kI2sPinLrck, kI2sPinData);

  // --- 起動時の50/60Hz判別 ---
  // 生サンプルをバッファに溜めてから判別、ではなく**2本のGoertzelを並走させて
  // 窓の終わりに振幅を比べるだけ**にしてある。1秒窓ぶん(≈48000サンプル×4バイト
  // ≈188KB)のバッファをPSRAM無しのSRAMに確保するのは避けたい
  // （→ docs/hardware.md の「PSRAMは意図的に有効化しない」）。
  // i2sTask を起動する前のこの1回だけは、ここで直接 i2s_read する
  // （他に読み手がいないので競合しない）。
  {
    gridfreq::GoertzelEstimator det50(50.0, kFsNominalHz, 1.0);
    gridfreq::GoertzelEstimator det60(60.0, kFsNominalHz, 1.0);
    const size_t winN = det50.windowSamples();
    size_t gotTotal = 0;
    static int32_t buf[kI2sReadFrames * 2];
    while (gotTotal < winN) {
      size_t got = 0;
      if (i2s_read(I2S_NUM_0, buf, sizeof(buf), &got, portMAX_DELAY) != ESP_OK) continue;
      const size_t frames = got / (sizeof(int32_t) * 2);
      for (size_t i = 0; i < frames && gotTotal < winN; ++i, ++gotTotal) {
        const int32_t l = buf[i * 2] >> 8;
        det50.addSample(l);
        det60.addSample(l);
      }
    }
    gFNominalHz = (det50.magnitude() >= det60.magnitude()) ? 50.0 : 60.0;
    Serial.printf("# f_nominal detected: %.0fHz (mag50=%.0f mag60=%.0f)\n", gFNominalHz,
                  det50.magnitude(), det60.magnitude());
  }

  // **NTPロックを待たず、公称fsで即座に記録を始める。**
  // `gFs.fsMicroHz()`はロック前は公称値をそのまま返すので(NtpTimebaseの不変条件)、
  // ここではまだ「測った値」を名乗っていない——batch側もtimebase_source=NOMINALと
  // 正直に申告する(loop()参照)。ロックした瞬間にgFsSourceWasNtpの遷移を検出して
  // 推定器を規正済みfsで作り直す。→ docs/log/2026-08-08-nominal-window-open-question.md
  gWindowQueue = xQueueCreate(8, sizeof(WindowRecord));
  gRecordGoertzel.store(
      new gridfreq::GoertzelEstimator(gFNominalHz, static_cast<double>(gFs.fsMicroHz()) / 1e6,
                                       1.0),
      std::memory_order_relaxed);

  xTaskCreatePinnedToCore(i2sTask, "i2s_pump", 4096, nullptr, 5, nullptr, 1);

  // fw versionは実行中変わらないので一度だけ埋める(Uploaderはポインタを保持する
  // だけで値をコピーしない。ヒープ/uptimeはloop()側で毎周更新する)。
  snprintf(sFwVersionBuf, sizeof(sFwVersionBuf), "%s", ELBZ_FW_VERSION);

  gUploader = new Uploader(gIdentity.ingestUrl.c_str(), /*alertUrl=*/"",
                            gIdentity.hmacSecret.c_str(), gIdentity.deviceId, kMaxRamBatches,
                            kSpillDir, /*dropOldestWhenFull=*/true, kOtaWatchedHeaders,
                            1, kTelemetryHeaderNames, kTelemetryHeaderValues, 3);
  gUploader->begin();

  Serial.println("# recording started immediately (timebase_source=NOMINAL); "
                  "will re-arm goertzel once fs locks via NTP (~600s)");
  gNextQueryMs = millis();
}

void loop() {
  ensureWifi();
  if (WiFi.status() != WL_CONNECTED) {
    digitalWrite(kLedWifiPin, HIGH);  // 赤LED: 切断中を点灯で示す
    delay(kWifiRetryDelayMs);
    return;
  }
  digitalWrite(kLedWifiPin, LOW);  // 接続中は消灯(問題なし)

  if (static_cast<int32_t>(millis() - gNextQueryMs) >= 0) {
    const char* server = kNtpServers[gServerIndex];
    gServerIndex = (gServerIndex + 1) % kNtpServerCount;

    timebase::SntpSample s{};
    const bool got = gSntp.query(server, kNtpTimeoutMs, s);
    const I2sSnapshot i2s = takeI2sSnapshot();
    const uint64_t frames = got ? framesAt(i2s, s.ticks) : i2s.frames;

    static uint32_t seenOverflows = 0;
    if (i2s.overflows != seenOverflows) {
      Serial.printf("# i2s overflow (total=%u); fs regression reset\n", i2s.overflows);
      gFs.reset();
      seenOverflows = i2s.overflows;
    }

    if (got && i2s.atUs != 0) {
      const uint64_t rttFrames = (s.rttTicks * kFsNominalHz) / 1000000ULL;
      gFs.addObservation(frames, s.unixUs, rttFrames);
    }
    Serial.printf("# fs n=%u source=%s ppm=%.4f resid_ns=%u l_pp=%u r_pp=%u\n", gFs.obsCount(),
                  gFs.source() == timebase::Source::kNtp ? "NTP" : "NOMINAL",
                  ppmOf(gFs, kFsNominalMicroHz), gFs.residualNs(), i2s.lPp, i2s.rPp);

    // NOMINAL→NTPへ切り替わった瞬間、規正済みfsでGoertzelを作り直す。
    // **fsはコンストラクタで固定される設計なので、作り直す以外に追従する方法がない**
    // (→ Goertzel.h)。cyclesQ16は継続させる(絶対累積位相を後退させない不変条件)。
    // 旧オブジェクトは意図的にdeleteしない: Core1(i2sTask)がaddSample()実行中に
    // このポインタを参照している可能性があり、delete するとuse-after-freeになる。
    // この切り替えは通常運用でセッションに1回しか起きないので、
    // 数百バイトのリークは実害が無い。
    const bool nowNtp = gFs.source() == timebase::Source::kNtp;
    digitalWrite(kLedTimebaseLockPin, nowNtp ? HIGH : LOW);
    if (nowNtp && !gFsSourceWasNtp) {
      gridfreq::GoertzelEstimator* prev = gRecordGoertzel.load(std::memory_order_relaxed);
      const uint64_t seedCycles = prev != nullptr ? prev->cyclesQ16() : 0;
      gRecordGoertzel.store(
          new gridfreq::GoertzelEstimator(gFNominalHz, static_cast<double>(gFs.fsMicroHz()) / 1e6,
                                           1.0, seedCycles),
          std::memory_order_relaxed);
      Serial.printf("# fs locked: goertzel re-armed fs=%.6f seed_cycles_q16=%llu obs=%u "
                    "resid_ns=%u\n",
                    static_cast<double>(gFs.fsMicroHz()) / 1e6,
                    static_cast<unsigned long long>(seedCycles), gFs.obsCount(),
                    gFs.residualNs());
    }
    gFsSourceWasNtp = nowNtp;

    gNextQueryMs = millis() + (kNtpIntervalSeconds + random(kNtpJitterSeconds)) * 1000;
  }

  WindowRecord rec;
  while (gWindowQueue != nullptr && xQueueReceive(gWindowQueue, &rec, 0) == pdTRUE) {
    // WS2812の色更新は測定データの経路と無関係な副作用。rec.cyclesQ16は
    // このWindowRecordが確定した時点の累積位相そのもの(→ wire-format.md)なので、
    // 追加の状態を持たずそのまま渡せる。**測定・送信のロジックには一切影響しない。**
    {
      const ledstatus::Rgb c =
          ledstatus::cyclesToColor(rec.cyclesQ16, kWs2812Brightness, kCyclesToHueGain);
      neopixelWrite(kWs2812Pin, c.r, c.g, c.b);

      // 回転方向(色の変化だけ)では「今速いか遅いか」が瞬時に読めないという
      // フィードバックを受け、符号だけを別LEDで即座に示す。
      gridfreq::GoertzelEstimator* g = gRecordGoertzel.load(std::memory_order_relaxed);
      if (g != nullptr) {
        digitalWrite(kLedFastSlowPin, g->freqHz() > gFNominalHz ? HIGH : LOW);
      }
    }

    if (gCurrentBatch == nullptr) {
      gCurrentBatch = gridfreq::newBatch();
      // バッチ内のレコード間隔は gFs(NtpTimebase の回帰)の fsMicroHz() から決まる。
      // 起点もここから取れば同じ時刻源で揃う。**timesync(粗いSMOOTH SNTP壁時計)を
      // 都度読み直すと、そちらの補正ジッタがバッチ境界にだけ乗ってしまう**
      // （→ docs/log/2026-08-08-batch-boundary-timestamp-jump.md）。
      //
      // **「今」ではなく rec.framesAtEnd を使う。** xQueueReceive した時刻(=このループを
      // 回している瞬間)を使うと、gSntp.query()（最大 kNtpTimeoutMs ブロックしうる）で
      // loop() が詰まった分がそのままバッチ起点のズレになって再発する
      // （実機検証で発覚。NTP問い合わせのたびに境界dtが乱れていた）。
      // rec.framesAtEnd は Core1 が窓の完成した瞬間に確定させた値なので、
      // Core0 側の処理遅延に一切左右されない。
      //
      // gFs が未規正(NOMINAL)の間は、timesync::nowUs() を都度読み直す代わりに
      // gNominalAnchorUnixUs(SNTP初回同期の直後に一度だけ固定)から公称fsで外挿する。
      // **NOMINAL中はSNTPのslew補正ジッタ(数ms級)がバッチ境界のたびに乗り、
      // freq=Δcycles/Δtの計算がそれを増幅して〜100mHz級の針になっていた**
      // (実機検証で発覚。NTP問い合わせループとは無関係にNOMINAL区間だけで再現した)。
      // 絶対時刻としての確度はNOMINALなので元々主張しない——効くのは
      // 「同一アンカーからの一貫した外挿でバッチ境界の相対時間が正確になる」ことだけ。
      //
      // **アンカーは遅延取得する。** setup()で無条件に読むと、SNTPの初回同期が
      // まだの場合(実機でWiFi不調により発生した)、timesync::nowUs()が1970年
      // 付近を返し、その悪い値がセッション全体に固定されてしまう。
      // timesync::isSynced()がtrueになった最初のバッチでだけ取り直すことで、
      // 悪い影響を「同期が済むまでの数バッチ」に限定する(旧来のtimesync都度読みと
      // 同程度の影響で、以後は良いアンカーに揃う)。
      if (gNominalAnchorUnixUs == 0 && timesync::isSynced()) {
        gNominalAnchorUnixUs = timesync::nowUs();
        gNominalAnchorFrames = rec.framesAtEnd;
      }
      const uint64_t batchStartUs =
          gFs.source() == timebase::Source::kNtp
              ? gFs.unixUsAt(rec.framesAtEnd)
          : gNominalAnchorUnixUs != 0
              ? gNominalAnchorUnixUs +
                    static_cast<uint64_t>(static_cast<double>(rec.framesAtEnd -
                                                                gNominalAnchorFrames) /
                                               static_cast<double>(kFsNominalHz) * 1e6 +
                                           0.5)
              : timesync::nowUs();
      gCurrentBatch->begin(batchStartUs);
    }
    gridfreq::addRecord(*gCurrentBatch, rec.cyclesQ16, /*vRmsMv=*/0, /*flags=*/0);
    if (rec.discontinuity) gBatchDiscontinuity = true;

    if (gCurrentBatch->isFull()) {
      gridfreq::HeaderFields hf;
      hf.device_id = gIdentity.deviceId;
      hf.session_id = gSessionId;
      hf.f_nominal_mhz = static_cast<uint32_t>(gFNominalHz * 1000.0 + 0.5);
      hf.fs_measured_uhz = gFs.fsMicroHz();
      hf.tb_obs_count = gFs.obsCount();
      hf.tb_residual_ns = gFs.residualNs();
      hf.flags = gBatchDiscontinuity ? kGfrqFlagDiscontinuity : 0;
      // **正直にそのバッチ時点のgFs.source()を申告する。** ロック前はNOMINAL、
      // ロック後はNTP(PPSが無いのでPPSを名乗ることはない)。1バッチはこの粒度
      // でしか源を持たないので、ロックがバッチの途中で起きた回は末尾側の源で
      // 代表させる(→ docs/log/2026-08-08-nominal-window-open-question.md)。
      hf.timebase_source =
          gFs.source() == timebase::Source::kNtp ? kGfrqTbNtp : kGfrqTbNominal;
      hf.soc_temp_c = static_cast<int8_t>(temperatureRead());
      gridfreq::fillHeader(*gCurrentBatch, hf);

      Serial.printf("# batch enqueue: records=%u flags=0x%04x ram=%u spill=%u\n",
                    gCurrentBatch->recordCount(), hf.flags, gUploader->ramQueued(),
                    gUploader->spillCount());
      gUploader->enqueue(gCurrentBatch);
      gCurrentBatch = nullptr;
      gBatchDiscontinuity = false;
    }
  }

  // 送信直前にヒープ・稼働時間ヘッダを更新する（Uploaderは値をコピーせず
  // ポインタを保持するため、pump()がPOSTする直前の値を確実に使わせるには
  // この位置で書く必要がある）。
  snprintf(sHeapFreeBuf, sizeof(sHeapFreeBuf), "%u", static_cast<unsigned>(ESP.getFreeHeap()));
  snprintf(sUptimeBuf, sizeof(sUptimeBuf), "%lld", static_cast<long long>(esp_timer_get_time()));
  gUploader->pump();
  // spillに1件でも積まれている = RAMキューだけでは追いつかずLittleFSへ退避した
  // ことがある、つまり送信が実測データの生成に追いついていない兆候。
  digitalWrite(kLedSpillBacklogPin, gUploader->spillCount() > 0 ? HIGH : LOW);

  // pull型OTA更新の確認（→ docs/ota.md）。同じバッチ送信レスポンスヘッダで
  // 気づく。不一致なら取得〜書き込みまで一息に行い、完了までここでブロックする。
  checkAndPerformOta(gUploader->lastResponseHeaderValue(kOtaVersionHeader));
}

#elif defined(NAMZ_LED_TEST)
// NAMZ_LED_TEST を定義してビルドすると WiFi/I2S/NTPを一切使わず、合成した
// 「50Hzを中心に振れる周波数偏差」を時間積分してcyclesQ16相当の累積位相を作り、
// WS2812の色マッピング(シンクロスコープ的な回転)と外付けLEDの配線を目視確認できる。
// 実データが要らないので実機の電波・電源状況に左右されず、brightness等を
// config.hの値を変えながら素早く試せる。
//
// **本番(NAMZ_GRIDFREQ_RECORD)のcyclesQ16は毎窓+fNominalHz(整数)が乗るので
// 常に単調増加するが、ここでは基準周波数からの偏差だけを積分している
// (基準そのものの寄与は色に影響しない=小数部を変えないので省いてよい)。**
// sin波を積分しているだけなので値は0以上に留まり、符号の心配は無い
// (∫A sin(ωt)dt = (A/ω)(1-cos(ωt)) ≥ 0)。それでも念のためclampしておく。

namespace {
constexpr double kLedTestAmplitudeHz = 0.15;  // 偏差の振幅。大きめに振ってよく見えるようにする
constexpr double kLedTestPeriodMs = 20000.0;  // 1周期20秒。ゆっくり目で追いやすい速さ
double gSimCycles = 0.0;
uint32_t gLastSimMs = 0;
}  // namespace

void setup() {
  Serial.begin(kSerialBaud);
  delay(500);
  Serial.println();
  Serial.println("# electabuzz led test (synthetic freq-deviation integrated to cycles, "
                  "no WiFi/I2S/NTP)");
  Serial.printf("# amplitude=%.3fHz period=%.0fms brightness=%u\n", kLedTestAmplitudeHz,
                kLedTestPeriodMs, kWs2812Brightness);
  // 外付け3本(wifi/timebase/spill)は配線確認用に点滅周期を変えて、どのGPIOが
  // どの物理LEDか目視で対応付けられるようにする(実運用ではそれぞれ独立した
  // 意味の二値状態)。fast/slowだけは実際の合成偏差の符号に連動させ、
  // WS2812の回転方向と一致することを確認できるようにする。
  Serial.printf("# led_wifi(GPIO%d)=1Hz led_timebase(GPIO%d)=0.5Hz led_spill(GPIO%d)=0.25Hz "
                "led_fastslow(GPIO%d)=synthetic sign\n",
                kLedWifiPin, kLedTimebaseLockPin, kLedSpillBacklogPin, kLedFastSlowPin);
  pinMode(kLedWifiPin, OUTPUT);
  pinMode(kLedTimebaseLockPin, OUTPUT);
  pinMode(kLedSpillBacklogPin, OUTPUT);
  pinMode(kLedFastSlowPin, OUTPUT);
}

void loop() {
  const uint32_t nowMs = millis();
  const double phase = 2.0 * PI * static_cast<double>(nowMs) / kLedTestPeriodMs;
  const double devHz = kLedTestAmplitudeHz * sin(phase);

  const double dtSec = (gLastSimMs == 0) ? 0.0 : (nowMs - gLastSimMs) / 1000.0;
  gLastSimMs = nowMs;
  gSimCycles = std::max(0.0, gSimCycles + devHz * dtSec);
  const uint64_t cyclesQ16 = static_cast<uint64_t>(gSimCycles * 65536.0 + 0.5);

  const ledstatus::Rgb c = ledstatus::cyclesToColor(cyclesQ16, kWs2812Brightness, kCyclesToHueGain);
  neopixelWrite(kWs2812Pin, c.r, c.g, c.b);

  digitalWrite(kLedWifiPin, (nowMs / 500) % 2);
  digitalWrite(kLedTimebaseLockPin, (nowMs / 1000) % 2);
  digitalWrite(kLedSpillBacklogPin, (nowMs / 2000) % 2);
  digitalWrite(kLedFastSlowPin, devHz > 0.0 ? HIGH : LOW);

  static uint32_t lastPrintMs = 0;
  if (nowMs - lastPrintMs >= 200) {
    lastPrintMs = nowMs;
    Serial.printf("t=%lu dev=%.4f sim_cycles=%.4f rgb=%u,%u,%u\n", nowMs, devHz, gSimCycles, c.r,
                  c.g, c.b);
  }
  delay(20);
}

#elif defined(NAMZ_GRIDFREQ_TEST)
// NAMZ_GRIDFREQ_TEST を定義してビルドすると WiFi/NTP/fs回帰を一切行わず、
// I2S の生サンプルを boxcar 平均で間引いてシリアルに吐くだけ
// （tools/capture_serial.py 用・フェーズ1の疎通確認）。Namazu の NAMZ_SENSOR_TEST と
// 同じ位置付け（→ docs/roadmap.md）。R ch も同時に出す（未接続でもノイズフロアが見える）。

void setup() {
  Serial.begin(kSerialBaud);
  delay(500);
  Serial.println();
  Serial.println("# electabuzz gridfreq test (raw I2S dump, decimated)");
  if (!startI2s()) {
    Serial.println("# i2s init failed");
    while (true) delay(1000);
  }
  Serial.printf("# i2s pins: mclk=%d bclk=%d lrck=%d din=%d\n", kI2sPinMclk, kI2sPinBclk,
                kI2sPinLrck, kI2sPinData);
  Serial.printf("# decimate=%u (nominal effective fs=%.1fHz, NOT calibrated)\n",
                kGridFreqTestDecimate,
                static_cast<double>(kFsNominalHz) / kGridFreqTestDecimate);
  // t は ticksNow()（壁時計）ではなく、累積フレーム数から公称fsで作る仮想時刻。
  // **理由**: i2s_read は512フレーム(≈10.7ms)ぶんをDMAがまとめて渡してくる。
  // その場でticksNow()を呼ぶと、1回のreadの中で処理した数点がほぼ同時刻を指し、
  // 次のreadまでの本来の間隔がその1点に丸め込まれる(バースト処理の時刻をサンプルの
  // 実時刻と取り違える)。フレームカウンタ起点なら等間隔が保証される
  Serial.println("# frame_us,l,r");
}

void loop() {
  static int32_t buf[kI2sReadFrames * 2];
  static int64_t lAcc = 0, rAcc = 0;
  static uint32_t acc = 0;
  static uint64_t frameIdx = 0;

  size_t got = 0;
  if (i2s_read(I2S_NUM_0, buf, sizeof(buf), &got, portMAX_DELAY) != ESP_OK || got == 0) return;
  const size_t frames = got / (sizeof(int32_t) * 2);

  for (size_t i = 0; i < frames; ++i) {
    lAcc += buf[i * 2] >> 8;
    rAcc += buf[i * 2 + 1] >> 8;
    ++frameIdx;
    if (++acc >= kGridFreqTestDecimate) {
      char tbuf[24];
      const uint64_t frameUs = frameIdx * 1000000ULL / kFsNominalHz;
      Serial.printf("%s,%ld,%ld\n", u64str(frameUs, tbuf, sizeof(tbuf)),
                    static_cast<long>(lAcc / acc), static_cast<long>(rAcc / acc));
      lAcc = 0;
      rAcc = 0;
      acc = 0;
    }
  }
}

#else

void setup() {
  Serial.begin(kSerialBaud);
  delay(500);
  Serial.println();
  Serial.println("# electabuzz timebase+fs soak v2");
  Serial.printf("# chip=%s rev=%d cpu=%uMHz xtal=%uMHz flash=%uMB\n", ESP.getChipModel(),
                ESP.getChipRevision(), getCpuFrequencyMhz(), getXtalFrequencyMhz(),
                ESP.getFlashChipSize() / (1024 * 1024));
  Serial.printf("# tick sources: esp_timer (nominal 1e12 uHz) / i2s frames (nominal %u Hz)\n",
                kFsNominalHz);
  Serial.printf("# i2s pins: mclk=%d bclk=%d lrck=%d din=%d\n", kI2sPinMclk, kI2sPinBclk,
                kI2sPinLrck, kI2sPinData);

  if (startI2s()) {
    // 実際に設定されたクロック。要求と違っていたらここで分かる。
    Serial.printf("# i2s clk requested=%u actual=%.3f\n", kFsNominalHz, i2s_get_clk(I2S_NUM_0));
    xTaskCreatePinnedToCore(i2sTask, "i2s_pump", 4096, nullptr, 5, nullptr, 1);
  } else {
    // **fs 側は測れないが、水晶側の soak は続ける。**
    // 測れないものを黙って諦めるな。列は出るが obs が増えないので読めば分かる。
    Serial.println("# i2s disabled; fs columns stay at nominal");
  }

  Serial.println("# boot_us,unix_us,ticks,rtt_ticks,server,ok,err,"
                 "n,rejected,span_s,source,ppm,resid_ns,fit_rms_ns,min_rtt_us,temp_c,rssi,"
                 "frames,fs_n,fs_ppm,fs_resid_ns,fs_rms_ns,ovf,l_pp,r_pp");
  loadIdentityOrHalt();
  ensureWifi();
}

void loop() {
  ensureWifi();
  if (WiFi.status() != WL_CONNECTED) {
    delay(kWifiRetryDelayMs);
    return;
  }

  if (static_cast<int32_t>(millis() - gNextQueryMs) < 0) {
    delay(50);
    return;
  }

  const char* server = kNtpServers[gServerIndex];
  gServerIndex = (gServerIndex + 1) % kNtpServerCount;

  timebase::SntpSample s{};
  const bool got = gSntp.query(server, kNtpTimeoutMs, s);
  const I2sSnapshot i2s = takeI2sSnapshot();
  const uint64_t frames = got ? framesAt(i2s, s.ticks) : i2s.frames;

  static uint32_t seenOverflows = 0;
  if (i2s.overflows != seenOverflows) {
    // **DMA が溢れた = 数え損ねたフレームがある = ティック源が実時間に対して飛んだ。**
    // ここで線を繋いだら「測れなかった区間を測れたように見せる」ことになる。
    // 水晶側（gXtal）は無関係なので巻き込まない。
    Serial.printf("# i2s overflow (total=%u); fs regression reset\n", i2s.overflows);
    gFs.reset();
    seenOverflows = i2s.overflows;
  }

  if (got) {
    // 採否は NtpTimebase が決める（RTT・単調性・外れ値）。ここでは判定しない。
    gXtal.addObservation(s.ticks, s.unixUs, s.rttTicks);
    // fs 側は同じ標本を、ティックだけ I2S のフレーム数に差し替えて食わせる。
    // rttTicks もフレーム単位に直す（NtpTimebase は rttTicks / 公称レート で µs に戻す）。
    //
    // **I2S が一度も動いていないうちは食わせない。** atUs が 0 のまま外挿すると
    // 起動からの経過ぶんを丸ごと足した嘘のフレーム数になる。
    // 測れていないものを食わせるくらいなら、標本を1つ捨てる方がいい。
    if (i2s.atUs != 0) {
      const uint64_t rttFrames = (s.rttTicks * kFsNominalHz) / 1000000ULL;
      gFs.addObservation(frames, s.unixUs, rttFrames);
    }
    logLine(server, true, "", s, i2s, frames);
  } else {
    logLine(server, false, gSntp.lastError(), s, i2s, frames);
  }

  // 一定間隔で叩き続けると経路の周期的な混雑と同期しうるので散らす。
  gNextQueryMs = millis() + (kNtpIntervalSeconds + random(kNtpJitterSeconds)) * 1000;
}

#endif  // NAMZ_GRIDFREQ_RECORD / NAMZ_GRIDFREQ_TEST
