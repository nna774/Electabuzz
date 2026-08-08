# NOMINAL区間の即記録・事後補正(案A)を実装した

## 経緯

[log/2026-08-08-nominal-window-open-question.md](2026-08-08-nominal-window-open-question.md)で
案Aを決定し、線形性を検証した。ここではその実装をfirmware・lambda・dashboardの3層に
入れた。

## firmware (`firmware/src/main.cpp`, `firmware/lib/Goertzel/`)

- `env:record`は起動直後、`gFs.fsMicroHz()`(ロック前は公称値そのもの)でGoertzelを
  即座に起動するようになった。**NTPロックを待つゲートは撤去した。**
- `gFs.source()`がNOMINAL→NTPへ切り替わった瞬間を`gFsSourceWasNtp`で検出し、
  規正済みfsで`GoertzelEstimator`を作り直す。**fsはコンストラクタで固定される設計
  なので、作り直す以外に追従する方法が無い。**
- `GoertzelEstimator`に`initialCyclesQ16`引数を追加した。作り直す際、直前の
  推定器の`cyclesQ16()`を渡して絶対累積位相の連続性を保つ——`docs/storage.md`の
  「累積位相は絶対値で持て」という不変条件を、作り直しのたびに壊さないため。
  これにより、この切り替えでは`GfrqFlagDiscontinuity`を立てる必要が無い
  (cycles_q16が後退しないので、DMA溢れの`resetWindow()`とは違う扱いになる)。
- 旧`GoertzelEstimator`オブジェクトは意図的に`delete`しない。Core1(`i2sTask`)が
  `addSample()`実行中にこのポインタを参照している可能性があり、`delete`すると
  use-after-freeになる。この切り替えは通常運用でセッションに1回しか起きないので、
  数百バイトのリークは実害が無いと判断した。
- `hf.timebase_source`は`kGfrqTbNtp`のハードコードをやめ、バッチ確定時点の
  `gFs.source()`を正直に申告する。**1バッチはこの粒度でしか源を持てない**ので、
  ロックがバッチの途中(30秒の間)で起きた回は末尾側の源で代表させる、という
  精度の粗さを許容した(記録頻度は1回/セッションなので実害が小さいと判断)。

## lambda (`lambda/api/handler.py`)

- `_session_fs_corrections()`を新設。同一`session_id`内でNOMINALタグ付き
  バッチの`fs_measured_uhz`(=公称fs定数そのもの)と、その後最初に規正済み
  (`is_disciplined`)になったバッチの`fs_measured_uhz`(=ロック値)を突き合わせ、
  `locked_fs / nominal_fs`を補正係数として返す。ロックがまだ来ていない
  セッションは結果に含めない。
- `_series_payload()`で、NOMINAL区間かつ補正係数が求まっているレコードにだけ
  `freq_hz_corrected = freq_hz * correction`を計算する。生の`freq_hz`は
  従来どおり出す(補正の有無に関わらず)。
- レスポンスに`timebase_source`(各点の源。文字列配列)と`freq_hz_corrected`
  (補正した予測値。無ければnull)を追加した。既存フィールドは変えていない。
- `lambda/tests/test_api.py`に2件追加(計47件、全緑): ロック前は補正値が
  出ないこと、ロック後はNOMINAL区間だけに正しい係数で補正値が付き、
  NTP区間には付かないこと。

## dashboard (`dashboard/app.js`, `dashboard/index.html`)

- 生の周波数線を、区間の始点の`timebase_source`によって描き分けるようにした:
  NOMINAL区間は灰色の点線(`--nominal`)、規正済み区間は従来どおりの実線(`--accent`)。
  1点ずつ線分を引き直す方式にしたので、同じ配列内でも区間ごとに線種が変わる。
- `freq_hz_corrected`が非nullの区間へ、アンバーの破線(`--predict`)を重ねて描く。
  ロック前は全点null なので何も描かれず、**ロックした瞬間にこの線が過去へ
  遡って現れる**、という設計どおりの見た目になる。
- `--predict`にNTPバッジと同じ配色(`#d4a017`系)を使った——補正の出処が
  「やがてNTP品質になった」ことだと視覚的に紐づくように。
- ローカルの`python3 -m http.server`+ブラウザで、合成データ(前半NOMINAL・
  後半NTP、補正線あり)を`drawFreqChart()`/`renderStatus()`へ直接渡して
  スクリーンショットで確認した。3本の線が意図どおりの色・線種で重なり、
  NTP切替後は実線へ自然に繋がることを目視確認済み。実APIでの確認はまだ
  (実機のセッションがNOMINAL→NTPを跨ぐタイミングでの確認が必要)。

## テスト・ビルド確認

- `firmware/lib/GridFreq/test/run.sh` / `Timebase/test/run.sh` /
  `Goertzel/test/run.sh` 全緑(Goertzelに継続性のテストを2件追加)。
- `.venv/bin/pio run -d firmware -e s3 -e gridfreqtest -e record` 全緑。
- `.venv/bin/python -m pytest lambda/tests` 47件全緑。

## 次に何が可能になったか

**コードは揃ったが、実機・実クラウドへは投入していない。** `terraform apply`は
実行していない(api Lambdaの中身が変わるので再デプロイが要る)。実機に焼いて
NOMINAL→NTPの遷移を跨いだ実データで、①`timebase_source`がバッチごとに正しく
遷移すること②`cycles_q16`が遷移をまたいで後退しないこと③ダッシュボードの
3本線が実データで意図どおりに出ることを確認するのが次の一手。
