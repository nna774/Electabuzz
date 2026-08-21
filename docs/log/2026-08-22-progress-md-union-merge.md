# docs/progress.md のコンフリクトをmerge=unionで回避する

## 何が問題だったか

`docs/progress.md`は「表の先頭に1行追記」という運用にしていたが、並行したブランチが
同時に作業すると、両方とも表の同じ位置（ヘッダ直後）に新しい行を挿入しようとして
コンフリクトする。実際に2026-08-08、PR #14(バッチ境界の針ノイズ修正)とのマージで
`docs/progress.md`の行追加同士が衝突している
（→ [log/2026-08-08-nominal-window-merge-redeploy.md](2026-08-08-nominal-window-merge-redeploy.md)、
そのときは3-wayマージで手動解消した）。

[NamazuHaUrokoGaNai](https://github.com/nna774/NamazuHaUrokoGaNai)側でも同じ運用・
同じ問題が起きており、`.gitattributes`の`merge=union`で解消していた
（[PR #123](https://github.com/nna774/NamazuHaUrokoGaNai/pull/123)）。Electabuzz側も
`docs/progress.md`の運用が最初から同一だったので、同じ対策がそのまま効く。

## 決めたこと

`.gitattributes`に`docs/progress.md merge=union`を追加した。union mergeは追記された
行を両側から機械的に合成してコンフリクトマーカーを出さないビルトインのマージドライバ。

トレードオフとして、日付順（新しいものが上）の厳密な並びは保証されなくなる——union
マージは行の内容を合成するだけで、日付列でソートし直したりはしない。運用上「概ね新しい
ものが上」に緩め、気になったら手動でソートし直す方針にした。索引としての用途（ログへの
リンク集）には十分と判断。

## 次に何が可能になったか

並行したブランチが同時に`docs/progress.md`へ追記してもコンフリクトなくmergeできる。
