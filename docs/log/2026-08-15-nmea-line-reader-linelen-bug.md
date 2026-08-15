# `NmeaLineReader::lineLen()`が常に0を返すバグを修正、`kGfrqFlagGnssFix`が立つようになった

## 経緯

[log/2026-08-15-phase2-pps-first-lock.md](2026-08-15-phase2-pps-first-lock.md)で、PPSロック(`kGfrqFlagPpsLocked`)は残差30ns/sで成功したが、`kGfrqFlagGnssFix`(GNSS UART経由のfixフラグ)が一度も立たなかった。PPSの残差の良さからGNSS自体は確実にfixしているはずで、原因はGNSS UART側にあると推測していた。

## 調査: GNSS UARTの生バイトをUSBへ一時的にエコー

`main.cpp`のGNSS UART読み取りループに`Serial.write(c)`を一時的に挟んで実機で確認したところ、`$GNGGA,142013.00,...,1,12,0.91,...`(fix quality=1、12機捕捉)という**完全に正常なNMEAが届いていた。** UART配線・ボーレート・GNSS側の設定はすべて正常。にもかかわらず`gGnssFix`は`true`にならなかった。

## 原因: `NmeaLineReader::feed()`が`lineLen()`を壊してから`true`を返していた

`firmware/lib/GnssNmea/src/NmeaLineReader.cpp`の`feed()`は、`\n`を検出した時点で:

```cpp
buf_[len_] = '\0';
const bool wasOverflowed = overflowed_;
len_ = 0;              // ← ここで既に0にしてしまっていた
overflowed_ = false;
return !wasOverflowed;
```

ヘッダのコメントは「line()/lineLen()は次のfeed()を呼ぶまで有効」と約束していたが、**`lineLen()`(`len_`をそのまま返す実装)は`feed()`が`true`を返した時点で既に0にリセットされていた。** `line()`(null終端文字列を返す`buf_`)は無事だったので、文字列自体は正しく見えるが長さだけ壊れているという分かりにくい壊れ方だった。

`main.cpp`は`parseGga(gNmeaReader.line(), gNmeaReader.lineLen(), fix)`という形で呼んでおり、`len=0`が渡ると`parseGga`の先頭にある`if (len < 9 ...) return false;`に即座に引っかかる。**GGAセンテンスがどれだけ正常でも、常に解析失敗していた。**

## なぜ既存テストが検出できなかったか

`test/test_nmea_line_reader.cpp`は`r.line()`(`std::strcmp`や`std::string`代入、内部で`strlen`を使う)しか検証しておらず、**`lineLen()`の戻り値を一度もテストしていなかった。** `main.cpp`が実際に使うAPIの組み合わせ(`line()`+`lineLen()`)を検証していなかったため、`buf_`の内容が正しく見える限りテストは全緑のままバグが埋まっていた。

## 修正

`lineReady_`フラグを追加し、`\n`検出時は`len_`を巻き戻さず`lineReady_=true`にするだけにした。実際の巻き戻しは**次の`feed()`呼び出しの先頭**で行う——これでヘッダのコメントが約束していた「次のfeed()を呼ぶまで有効」という契約を実装が正しく守るようになった。

回帰テストとして`lineLen() == strlen(line())`の一致を確認するチェックを追加した(→ `test/test_nmea_line_reader.cpp`)。`firmware/lib/GnssNmea/test/run.sh`全緑。

## 実機で確認

修正後、`env:record`を再投入:

```
# pps locked: goertzel re-armed fs=48001.727761 seed_cycles_q16=95098150 obs=30 resid_ns=21
# batch enqueue: records=30 flags=0x0003 ram=0 spill=0
```

**`flags=0x0003`——`kGfrqFlagPpsLocked`と`kGfrqFlagGnssFix`の両方が立った。** [log/2026-08-15-phase2-pps-first-lock.md](2026-08-15-phase2-pps-first-lock.md)で残っていた唯一の宿題が片付いた。

`pio run -e s3 -e gridfreqtest -e record`は全てSUCCESS(`provision`は本worktreeに`secrets.h`が無いための既知の失敗で無関係)。ホスト側テスト(GridFreq/Timebase/Goertzel/PpsEdge/GnssNmea)も全て退行なし。

## 次にやること

- フェーズ2の残タスク(soak確認、`series/`へのクラウド着弾確認)を進める
