# クラウド側: ingest / detect / rollup

## ingest

既存 ingest を分岐させるのではなく、**Electabuzz 専用の ingest を別に置く**(スタック分離のため)。
構造は [ingest/handler.py](https://github.com/nna774/NamazuHaUrokoGaNai/blob/master/lambda/ingest/handler.py) をそのまま踏襲する。

- `auth.verify()` → `wire_gridfreq.parse()` → device_id 一致チェック → `s3.put_object()` →
  `devices.record_batch()` の流れは同一
- device_id 一致チェック([handler.py:56-57](https://github.com/nna774/NamazuHaUrokoGaNai/blob/master/lambda/ingest/handler.py#L56-L57))の
  「別デバイスの騙り防止」は必ず踏襲する
- `devices.record_batch()` の失敗を握りつぶして 200 を返す判断
  ([handler.py:67-68](https://github.com/nna774/NamazuHaUrokoGaNai/blob/master/lambda/ingest/handler.py#L67-L68)、
  「デバイスに無駄な再送をさせない」)も踏襲する。**これは正しい判断だ**
- `/alert` は JSON なので周波数用のフィールドに差し替えるだけ

## 新規 detect_gridfreq / rollup

既存の状態機械を流用して判定だけ差し替える。

| イベント | デバイス側即時 | cloud 確定 |
|---|---|---|
| 周波数逸脱 | \|f - f_nom\| > 100mHz が継続 | 前後波形と PPS 品質で確認 |
| 急変(RoCoF) | \|df/dt\| > 200mHz/s | 同上 |
| 電圧異常 | v_rms が公称 ±10% 外 | 同上 |
| 停電・復電 | v_rms 急落/復帰 | 復電時の位相跳躍量を記録 |
| 位相不連続 | unwrap 失敗・SNR低下 | 測定側異常として `artificial` |

`artificial` フラグが既存にあるのが効く。自宅のエアコン起動によるローカルな電圧変動と
系統側事象を人が区別して記録できる。`tools/flag_event.py` もそのまま使える。

