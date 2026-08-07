# ダッシュボードv1を作り、apply して実データで確認する

## やったこと

`docs/roadmap.md`フェーズ8「ダッシュボード」の最小版を実装し、`apply`まで
済ませて実データで動作確認した。Namazuの`dashboard/`(`app.js`934行 +
`index.html`184行)・`lambda/api/handler.py`(309行)を読んだ上で、Electabuzzの
現状に合わせて大幅に絞った:

- **`lambda/api/handler.py`(新規)**: `/recent`のみ。Namazuには`/events`・
  `/devices`・`/event`もあるが、Electabuzzにはdetect(イベント判定)も
  生存台帳もまだ無いので持たない
- **`lambda/store_gridfreq.py`(新規)**: `series/`からGFRQバッチを読み、
  隣接レコードの`cycles`差分から瞬時周波数を計算する。Namazuの
  `common/store.py`と同じ役回りだが、GFRQは1レコード/秒・1バッチ最大30件と
  小さいので、`store.py`のmin/maxエンベロープ間引きは持ち込んでいない
  (`MAX_RECENT_MINUTES`=30と合わせても最大1800点)
- **`dashboard/`(新規)**: `index.html` + `app.js`。外部ライブラリなし、
  Canvas 2Dで自前描画。Namazuのライブ表示(3軸波形・ドラッグズーム)より
  ずっと単純な単一系列の折れ線 + 公称値の破線 + ステータス行 + 品質テーブル
- **`terraform/dashboard.tf`(新規)**: S3(非公開) + CloudFront(OAC)。
  Namazuの構成をそのまま踏襲(`Cache-Control: no-cache`をResponse Headers
  Policy側で付ける理由も含めて——S3側に付けるとエッジ↔S3間の再検証が
  毎回発生する落とし穴をNamazuが実際に踏んでいるため、同じ構成で避けた)。
  **カスタムドメインは持ち込んでいない**——CloudFrontの既定ドメインで足りる
  うちは、ACM(us-east-1)や外部DNSリポジトリとの手順の絡み合いを増やす
  理由が無い

## 周波数計算で「測れなかった区間を測れたように見せない」をどう守ったか

`Record`はワイヤ上に絶対累積位相(`cycles_q16`)しか持たず、瞬時周波数は
隣接レコードの差分として`api`側で計算する。この差分計算が「本当に1レコード
分(`record_rate_mhz`どおり)の間隔だったか」を保証できない場面が3つあり、
該当する点は`freq_hz`を`null`にして系列を途切れさせる:

1. `session_id`が変わる(デバイス再起動。`cycles`が0から再開する)
2. 実際の時刻間隔が`record_rate_mhz`から大きく外れる(送信遅延・欠測)
3. バッチに`GfrqFlagDiscontinuity`が立っている——**ここが一番踏みやすい罠
   だった。** ファーム側`GoertzelEstimator::resetWindow()`は、DMA溢れ直後の
   1窓を「基準点のみ」として無出力にする(→
   [log/2026-08-07-goertzel-cpp-port.md](2026-08-07-goertzel-cpp-port.md))。
   つまりワイヤ上のレコード列は詰まって見える(欠番が無い)が、実際には
   1窓ぶんの時間が「消えて」おり、`Batch.timestamps_us()`が
   `batch_start_us + i×record_period`で機械的に付けるタイムスタンプは
   その消えた分を反映しない。**タイムスタンプの間隔チェック(上記2)だけでは
   この罠を検出できない**——だから`GfrqFlagDiscontinuity`のバッチ全体を
   別枠で弾く必要があった

`lambda/tests/test_api.py`にこの3パターンそれぞれのテストを書いた
(`test_session_change_breaks_continuity`・
`test_discontinuity_flag_suppresses_frequency_in_batch`他)。

## 確認したこと

- `lambda/tests/test_api.py`(8ケース。空区間・単一バッチ内の周波数計算・
  バッチをまたいだ連続性・セッション境界・discontinuityフラグ・`minutes`の
  クランプ)が緑。既存37件と合わせて45件全緑
- `terraform validate` / `fmt`が緑
- **`apply`を実行した**（8 to add, 2 to change——`aws_lambda_function.ingest`の
  `2 to change`は再ビルドしたzipの`source_code_hash`差分のみで、コード自体は
  無改造）。CloudFrontの配信作成に約3分かかった
- `aws s3 sync`でダッシュボードを配置、`create-invalidation`でキャッシュを
  飛ばした
- **実データで確認した。** この時点で`env:record`のデバイスは既に`fs`が
  ロックしてバッチを送り始めていた(→
  [log/2026-08-07-terraform-apply-and-secrets.md](2026-08-07-terraform-apply-and-secrets.md)の
  続き)。`/recent?minutes=5`が270点返し、`timebase_source=NTP`・
  `f_nominal_hz=50.0`・実測周波数49.98〜50.04Hz程度の**実系統データ**が
  ダッシュボードのグラフに表示されることをブラウザで確認した
  (コンソールエラー無し)

## まだやっていないこと

- **時刻偏差(TE)の表示** — 絶対のTEはPPS到着後(フェーズ2)でないと出せない
  (`Batch.te_seconds()`はバッチ内相対値しか計算しない、→
  `lambda/wire_gridfreq.py`の同メソッドのdocstring)
- **欠測区間の可視化** — 今は周波数系列が途切れるだけで、「いつからいつまで
  欠測していたか」を明示的には出していない
- **イベント一覧・デバイス一覧** — detect・生存台帳が無いので作れない
  (→ フェーズ9)
- **カスタムドメイン** — 必要になったらNamazuの`custom_domain.tf`を参照する

## 次に何が可能になったか

`https://d749zv0enwqn1.cloudfront.net/`で系統周波数がリアルタイムに見える
ようになった。**課金対象のリソースが増えたが、実費は月100円未満の見込み**
（→ このセッション内でユーザーに提示した概算。S3 GET・Lambda呼び出し・
CloudFront転送のいずれも無料枠内かそれに近い）。
