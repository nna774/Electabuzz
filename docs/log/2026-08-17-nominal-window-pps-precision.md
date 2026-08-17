# NOMINAL区間の説明が「NTP規正まで約10分」のまま古くなっていたのを直す

## 経緯

dashboardのキャプション「起動直後〜NTP規正(約10分)までは点線」について、
「PPSの方がNTPより先にロックするはずなのに表現が古くないか」と指摘を受けた。

## 確認

`firmware/lib/Timebase/src/NtpTimebase.h`の`kMinSpanSeconds`は600秒(10分)、
`firmware/lib/Timebase/src/PpsTimebase.h`の`kMinSpanSeconds`は**30秒**。
`main.cpp`の`hf.timebase_source`選択ロジック(`ppsUsable ? (ntpUsable ? PPS_NTP : PPS)
: (ntpUsable ? NTP : NOMINAL)`)はPPSが使える時点でNTPの完了を待たずに
`PPS`/`PPS_NTP`へ切り替える。

このNOMINAL区間の扱いを決めた[log/2026-08-08-nominal-window-open-question.md](2026-08-08-nominal-window-open-question.md)
はPPSがまだ配線されていない時点(2026-08-08)の決定で、想定していたロック手段は
NTPだけだった。フェーズ2実配線(2026-08-15〜)後は、実運用でのNOMINAL区間は
NTPの約10分ではなく**PPSの約30秒で終わるのが通常**になっている——指摘の通り、
表現が古くなっていた。

## 直したもの

- `dashboard/index.html`: 「起動直後〜NTP規正(約10分)までは」→
  「起動直後〜規正(PPSが繋がっていれば約30秒、それが無ければNTPで約10分)までは」
- `docs/timebase.md`: 「NOMINAL区間(起動直後〜NTPロックまで)の扱い」節に、
  2026-08-08時点の決定はPPS配線前提であったこと・実運用では30秒が通常であること
  を追記(決定自体の妥当性は変わっていないので、経緯として残しつつ現状を追記する
  形にした——本体を書き換えて経緯を消すことはしていない)

設計判断の変更はなし。表示文言・説明文の精度を実装(定数)に合わせただけ。
