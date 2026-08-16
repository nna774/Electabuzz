# dashboardにdetectイベント一覧を追加(タブ化は見送り)

## 経緯

detect(v1)を`apply`し実クラウドで動作確認した([log/2026-08-17-detect-gridfreq-apply-verify.md](2026-08-17-detect-gridfreq-apply-verify.md))
後、`/events`を叩けるだけで画面に出す場所が無いと指摘を受けた。

## タブ化するか、既存ページに1セクション足すか

NamazuHaUrokoGaNai(地震計)のダッシュボードはライブ/イベント/デバイスの3タブ構成
だが、Electabuzzは今のところ

- 1ページに周波数・電圧の2グラフ+品質テーブルしか無く、Namazuの各タブほど
  1画面あたりの情報量が無い
- イベント自体、実機で0件(安定運転中の系統なら発生自体が稀)

という理由で、**今回はタブ化せず、既存ページの下にイベント一覧セクションを
1つ足す形にした。** イベントの種類・件数が増えてページが縦に伸びすぎたら、
Namazuと同じタブ構成へ切り替えることを検討する——この判断はコード側にも
コメントとして残してある(`dashboard/index.html`のイベントテーブル直前、
`dashboard/app.js`の`renderEvents`前)。

## 実装

- `dashboard/index.html`: `#quality-table`の下に`#events-table`(検知時刻・種類・
  ピーク値・継続の4列)を追加。`td:first-child`の共通スタイル(品質テーブルの
  キー列を弱める用)が新テーブルの1列目(データ列)まで巻き込まないよう、
  `#quality-table td:first-child`にスコープを絞った
- `dashboard/app.js`: `renderEvents()`を追加。`event_type`のラベル
  (`EVENT_TYPE_LABEL`)とピーク値の単位変換(`formatPeakValue`。
  `lambda/detect/handler.py`の`EVENT_TITLES`/`PEAK_LABELS`と対応する単位で表示)、
  日付+時刻表示用の`formatDateTime`(既存の`formatClock`は表示範囲30分前提で
  時刻のみだが、イベントは何日前のものも残りうるため日付が要る)
- `refresh()`に`/events?limit=20`の取得を追加。`/devices`と同じく**補助情報**
  として扱い、取得失敗時は直前の表示を残す(空扱いで上書きしない)

## 確認

ローカルで`python3 -m http.server`を立て、`?api=`で本番APIを指定してChromeで
実データ表示を確認(「直近のイベントはありません」を実データで確認、コンソール
エラー無し)。実機にはまだ逸脱イベントが無いため、`renderEvents()`へ疑似データを
直接渡してラベル・単位・日付跨ぎ表示(前日のイベント)の見た目も確認した。
