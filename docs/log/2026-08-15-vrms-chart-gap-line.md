# 電圧グラフの欠測区間が直線でつながって見える問題を直した

## 何が起きていたか

ユーザーから「ダッシュボードの電圧グラフを見ると、no dataな区間が直線でつながっているように見える。周波数グラフのように線を切ってほしい」という指摘。

`drawVrmsChart`(`dashboard/app.js`)は元々`v_rms_mv === 0`(未対応ファーム時代のレコード)の点で線を切る実装を持っていたが、それだけでは足りなかった。

## 原因

`v_rms_mv`はレコード単体の瞬時値で、`freq_hz`のような隣接点間の差分計算に依存しない。この性質を理由に、`lambda/api/handler.py`は`session_id`変化やDISCONTINUITY(GfrqFlagDiscontinuity)による抑制を意図的に適用していない(`test_v_rms_mv_survives_discontinuity_flag`で担保済み——値自体は抑制しないのが正しい設計)。

一方`freq_hz`は、まさにその抑制(`session_id`変化・実測dtの逸脱・DISCONTINUITYのいずれかで前の点を引き継がずNoneにする)によって、副産物として「欠測区間で線を切る」という効果を得ていた。周波数グラフの線切れは意図的な欠測マーカーではなく、差分計算ができないことの結果でしかなかった。

つまり`v_rms_mv`には最初から「本当の欠測区間(再起動・オフライン期間)で線をつながない」ための情報が無かった。ダッシュボードのソースを見ても、電圧の折れ線は各点の実測`t_us`をそのままx座標にプロットしてつなぐだけなので、値が存在する2点の間がどれだけ時間的に離れていようと直線で結んでしまう。

## 対応

`freq_hz`のnullをそのまま流用する案は採らなかった——DISCONTINUITYが立ったバッチ全体で線が切れてしまい、「`v_rms_mv`は抑制しない」という既存の設計意図(テストで担保済み)と矛盾する。

代わりに`_series_payload()`に**`continuous`という独立のbool配列**を追加した(`t_us`と並行)。判定基準は`freq_hz`とは別で、実測の時間だけを見る:

- 直前のレコードと`session_id`が同じ
- かつ実測dtが`record_rate_mhz`由来の想定間隔の2倍以内

`suspect`(DISCONTINUITY)は見ない——その窓のタイムスタンプ自体は実測どおりで、資格があるのは時間そのものだから。DISCONTINUITYバッチ内でも実測dtが正常なら`continuous=true`のままになり、`v_rms_mv`の値を抑制しない設計と整合する。一方、セッション再起動や実際のオフライン期間(実測dtが想定の2倍超)ではきちんと`false`になる。

`dashboard/app.js`の`drawVrmsChart`は、`v_rms_mv==null`に加えて`continuous[i]===false`でも線を切るように直した。値自体は変えず(点は引き続き描く)、前の点との接続だけを切る。

## 確認したこと

- `lambda/tests/test_api.py`に2件追加:
  - `test_continuous_breaks_on_session_change_but_not_discontinuity_flag`: DISCONTINUITYでは`continuous=true`のまま(v_rms_mvも欠けない)、セッション境界では`false`になることを確認
  - `test_continuous_breaks_on_large_time_gap_within_session`: 同一セッション内でも実測dtが想定の2倍を超えると`false`になることを確認
- `.venv/bin/python -m pytest lambda/tests` 全61件パス(既存の回帰なし)
- `node -c dashboard/app.js`で構文確認
- ブラウザでの実描画確認は未実施(モックAPIでの動作確認は次の一手)

## 次に何が可能になったか

- 電圧グラフが「測れなかった区間を測れたように見せない」というリポジトリ全体の不変条件を満たすようになった
- `continuous`は`v_rms_mv`専用に設計したが、将来的差分計算に依存しない別の量(SoC温度等)を時系列グラフに追加する際にも同じ考え方を再利用できる
