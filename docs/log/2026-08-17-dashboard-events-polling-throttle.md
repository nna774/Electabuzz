# dashboardの/eventsポーリングを5分間隔に間引く

## 何を決めたか

`dashboard/app.js`の`refresh()`は`/recent`・`/devices`・`/events`を全て同じ10秒
間隔で叩いていたが、`/events`だけ5分間隔に間引いた(`EVENTS_REFRESH_INTERVAL_MS`)。
初回ロード時は必ず取得し、以降は`Date.now() - lastEventsFetchedAt`が閾値を
超えた回だけ`/events`を叩く。取得に失敗した場合は`lastEventsFetchedAt`を
更新しないので、次の10秒後に再試行される(5分丸ごと待たされない)。

## なぜそう決めたか

detectイベント(周波数逸脱・RoCoF・電圧異常の確定判定)は`/recent`が返す瞬時
周波数のように頻繁に動く値ではない。頻発しない値を、頻繁に動く値と同じ
10秒間隔でポーリングする実利が無かった。

実機1台の個人運用でLambda呼び出しが増えること自体のコスト・負荷は誤差の
範囲だが、指摘を受けて直す価値はあると判断した。

## 何が覆ったか

覆っていない。`/events`自体は
[2026-08-17-dashboard-events-section.md](2026-08-17-dashboard-events-section.md)
で実装済みのものに対する、ポーリング頻度だけの調整。

## 次に何が可能になったか

特に無し。UIの見た目・挙動(初回表示・イベント発生時の反映)は変わらない
(反映が最大5分遅れる可能性がある程度)。
