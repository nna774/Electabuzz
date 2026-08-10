# `batch-uplink` の pin を v1.6.0 から v2.12.0 へ上げた

## 背景

Namazu側の`batch-uplink`利用がElectabuzzより大きく先行しており（pinは`v1.6.0`のまま
2026-08-06から止まっていたが、Namazuは同日以降18回タグを切ってv2.12.0まで進んでいた）、
「どこまで追従すべきか、そもそも追従する必要があるか」を検討した。

**結論: 機能に追従したいからではなく、Electabuzzの実機が現に晒されているリスクを
潰すために上げる価値があると判断した。** `docs/batch-uplink.md`が既に「Electabuzzは
都度pinを上げてよく、Namazuの破壊的変更を待つ理由が無い」と明言しており、この方針
どおりに動いた形になる。

## 何を検討したか

v1.7.0〜v2.12.0の16コミットを全て確認し、Electabuzzへの関連度で選別した。

**取り込む理由が明確だったもの:**

- **`v2.3.0`: TLSハンドシェイクタイムアウトをtask watchdog未満に縮める。**
  Namazuのdevice1で実際に起きた事故が動機——`WiFiClientSecure`の既定ハンドシェイク
  タイムアウト(120秒)がtask watchdogより長く、ネット瞬断でハンドシェイクが詰まると
  WDTパニックで先に再起動させられ、`flushToSpill()`を経由しないためRAM上のバッチを
  毎回失っていた。**Electabuzzは`Uploader::pump()`を専用task化せず`main.cpp`の
  `loop()`(Core0)から直接呼んでいる**ため、専用taskすら無いぶん同じ壊れ方をする条件は
  Namazuより緩いまである。実機1台しか無いことを考えると見送る理由が無い。
- **`discardSpillOn400`(v2.x、既定false・オプトイン): 破損した退避ファイルの隔離。**
  電源断でLittleFSの退避ファイルが0バイト/途中で切れた場合の対処。Electabuzzは
  測定対象の商用電源そのものに給電されている機体で、退避ファイル破損の起きやすさは
  Namazuより高いまである。`lambda/wire_gridfreq.py`の`parse()`は該当ケースで
  `CrcMismatch`ではなく`WireFormatError("too short for header")`を投げ、
  `lambda/ingest/handler.py`の`handler()`はこれを汎用exceptで拾って**既に400を
  返す実装になっている**（`CrcMismatch`だけは200で隔離、という契約とは別経路）。
  つまりingest側を一切変えずにこのオプションはそのまま噛み合うと確認した上で有効化した。
- **`v1.8.0`: CA証明書ピン留め(`caCert`引数、既定nullptr)。**
  OTA(`performPullOta()`)で既に`firmware/certs/amazon_root_ca1.pem`を
  `board_build.embed_txtfiles`で埋め込んでいるので、同じシンボルをUploaderの
  ingest送信にも渡すだけで`setInsecure()`を卒業できる。二重管理にならない。
  `open-questions.md`で2026-08-09に一度検討済みで結論も出ていたが未着手だったもの。
- **`v1.7.0`: バックフィル中の接続使い回し。** Electabuzzのspillは既定パーティションで
  約2.9日分溜め込める設計(`docs/batch-uplink.md`)なので、長期欠測からの復旧時に
  TLSハンドシェイクを繰り返さずに済む効果がそのまま活きる。

**見送ったもの:**

- **`v2.11.0`: `pump()`のRAM優先化。** Namazuの`Batch`プール枯渇→ヒープ破壊事故
  （`gBatchQueue`の producer/consumer 分離task構成に起因）の対策だが、Electabuzzは
  `GridFreqWire.cpp`で単発`new Batch(...)`するだけでプールを持たない。同じ事故は
  再現しないが、副作用の無い一般的な安全側の変更ではあるのでバージョン込みで
  そのまま取り込んだ(個別に無効化はしていない)。
- **`maxSpillReadBytes`固定バッファ・各種タイミングデバッグログ:** Namazuの
  87倍高いデータレート・producer/consumer構成に起因するヒープ断片化対策で、
  Electabuzzの低頻度単発送信では効果が薄い。既定0/未指定で無害なので今回は
  触らずデフォルトのまま据え置いた。必要になってから足せば足りる。

## v2.0.0の破壊的変更への対応

ヘッダ配列が固定長+本数引数からnullptr終端方式に変わり、`Uploader`コンストラクタから
`watchResponseHeaderCount`/`extraRequestHeaderCount`引数が消えた（`kMaxExtraRequestHeaders=4`
上限も撤廃）。`firmware/src/main.cpp`の`kOtaWatchedHeaders`・`kTelemetryHeaderNames`に
末尾`nullptr`を追加し、コンストラクタ呼び出しから該当引数を削って`caCert`・
`maxSpillReadBytes`・`discardSpillOn400`を渡す形に書き換えた。ロジック変更ではなく
機械的な移行で済んだ。

## 変更点

- `firmware/platformio.ini`・`terraform/build_lambda.sh`・
  `firmware/lib/GridFreq/test/run.sh`の3箇所のpinを`v1.6.0`→`v2.12.0`へ
  （3箇所とも独立にpinしているため、どれか1つを直し忘れると食い違う）
- `firmware/src/main.cpp`: `Uploader`コンストラクタ呼び出しをv2系APIへ移行、
  `caCert`にOTA用root CAを渡し、`discardSpillOn400=true`を指定

## 確認したこと

- `firmware/lib/GridFreq/test/run.sh`・`firmware/lib/Timebase/test/run.sh`・
  `firmware/lib/Goertzel/test/run.sh` 全緑
- `.venv/bin/python -m pytest lambda/tests` 58件全緑（batch-uplinkのpinはlambda側の
  ビルドスクリプトのみが参照し、pytest自体はvendorに依存しないため直接の影響は
  無いが、既存の回帰が壊れていないことの確認として実施）
- `.venv/bin/pio run -d firmware -e s3 -e gridfreqtest -e record` 全てSUCCESS
  （v2.12.0を実際にPlatformIO Library Managerが取得し、書き換えたAPI呼び出しが
  コンパイルを通ることを確認した）。`-e provision`は本worktreeに`secrets.h`が
  無いため失敗するが、これは既知の制約(gitignore対象・作業ツリー固有)であり
  今回の変更とは無関係

## まだやっていないこと

**実機への焼き直しはまだ。** 実機は1台のみで、`env:record`で常時稼働中のため、
焼き直しは別途ユーザーの判断で行う。次にこの作業を再開する時は、
`pio run -e record -t upload`で書き込み、シリアルログで
`# ota: fetching ...`等が出ないこと（通常運用時は関係ないログのはず）と
バッチ送信が従来どおり継続することを確認するとよい。TLS証明書検証を
`setInsecure()`から`setCACert()`へ切り替えたので、初回の疎通確認は
特に注意して見ること（証明書チェーンの不一致があればここで初めて表面化する）。
