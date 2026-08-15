'use strict';

// API URL の解決優先度: ?api= > localStorage > config.js(window.ELBZ_API_URL)
// Namazuのdashboard/app.jsと同じ考え方(→ dashboard/README.md)。
function apiBase() {
  const q = new URLSearchParams(location.search).get('api');
  if (q) localStorage.setItem('elbz_api', q);
  return localStorage.getItem('elbz_api') || window.ELBZ_API_URL || '';
}

async function apiGet(path) {
  const base = apiBase();
  if (!base) throw new Error('API URL 未設定');
  const res = await fetch(base.replace(/\/$/, '') + path);
  if (!res.ok) throw new Error('HTTP ' + res.status);
  return res.json();
}

const SOURCE_LABEL = { NOMINAL: '未規正', NTP: 'NTP', PPS: 'PPS', PPS_NTP: 'PPS+NTP' };
const SOURCE_CLASS = { NOMINAL: 'badge-nominal', NTP: 'badge-ntp', PPS: 'badge-pps', PPS_NTP: 'badge-pps' };

// トランス巻数比の暫定値(2026-08-15実測、複数回で確認中。→ docs/hardware.md
// 「v_rms_mvの基準点とトランス巻数比」節)。壁側電圧の概算はチェックボックスの
// opt-inでのみ出す——巻数比自体が暫定値な上、v_rms_mv → 実電圧の換算も1点校正
// でしかないため(→ docs/log/2026-08-15-afe-empirical-calibration.md)。
const TURNS_RATIO_PROVISIONAL = 10.08;

function themeColor(varName) {
  return getComputedStyle(document.documentElement).getPropertyValue(varName).trim();
}

// t_us(unixマイクロ秒)をブラウザのローカル時刻でHH:MM:SS表示する。
// 表示範囲は最大30分(→#minutes)なので日付をまたぐ表示は不要。
function formatClock(t_us) {
  return new Date(t_us / 1000).toLocaleTimeString('ja-JP', { hour12: false });
}

// --- Canvas 描画。外部ライブラリなし(vanilla Canvas 2D) ---
const PAD = 32;

function fitCanvas(cv) {
  const dpr = window.devicePixelRatio || 1;
  const rect = cv.getBoundingClientRect();
  cv.width = Math.round(rect.width * dpr);
  cv.height = Math.round(rect.height * dpr);
  const ctx = cv.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, w: rect.width, h: rect.height };
}

function drawFreqChart(cv, series) {
  const { ctx, w, h } = fitCanvas(cv);
  const fg = themeColor('--fg');
  const line = themeColor('--line');
  const accent = themeColor('--accent');
  const nominalColor = themeColor('--nominal') || '#888';
  const predictColor = themeColor('--predict') || accent;
  ctx.clearRect(0, 0, w, h);

  const n = series.t_us.length;

  if (n === 0) {
    ctx.fillStyle = fg;
    ctx.font = '13px system-ui, sans-serif';
    ctx.fillText('データなし', PAD, h / 2);
    return;
  }

  const t0 = series.start_us, t1 = series.end_us;
  const fNom = series.latest ? series.latest.f_nominal_hz : 50.0;
  // 縦軸は公称値を中心に ±200mHz を既定にし、外れたら自動で広げる(見切れ防止)。
  let dev = 0.2;
  for (const f of series.freq_hz) {
    if (f == null) continue;
    dev = Math.max(dev, Math.abs(f - fNom) * 1.15);
  }
  const yMin = fNom - dev, yMax = fNom + dev;
  const yMaxLabel = yMax.toFixed(3) + 'Hz';
  const yMinLabel = yMin.toFixed(3) + 'Hz';
  const fNomLabel = fNom.toFixed(0) + 'Hz';

  // 左余白は目盛ラベルの実測幅から決める(固定PADだと桁数次第で先頭が
  // canvas外にはみ出して欠ける)。
  ctx.font = '11px system-ui, sans-serif';
  const labelW = Math.max(
    ctx.measureText(yMaxLabel).width,
    ctx.measureText(yMinLabel).width,
    ctx.measureText(fNomLabel).width
  );
  const padLeft = Math.max(PAD, labelW + 12);
  const plotW = w - padLeft - PAD;
  const plotH = h - PAD * 2;

  const x = (t) => padLeft + ((t - t0) / (t1 - t0 || 1)) * plotW;
  const y = (f) => PAD + (1 - (f - yMin) / (yMax - yMin || 1)) * plotH;

  // 軸・公称値の破線
  ctx.strokeStyle = line;
  ctx.lineWidth = 1;
  ctx.strokeRect(padLeft, PAD, plotW, plotH);
  ctx.save();
  ctx.setLineDash([4, 4]);
  ctx.beginPath();
  ctx.moveTo(padLeft, y(fNom));
  ctx.lineTo(padLeft + plotW, y(fNom));
  ctx.stroke();
  ctx.restore();

  ctx.fillStyle = fg;
  ctx.font = '11px system-ui, sans-serif';
  ctx.textAlign = 'right';
  ctx.fillText(yMaxLabel, padLeft - 4, PAD + 4);
  ctx.fillText(yMinLabel, padLeft - 4, PAD + plotH);
  ctx.fillText(fNomLabel, padLeft - 4, y(fNom) + 4);
  ctx.textAlign = 'left';

  // 横軸(時刻)の目盛。プロット幅に収まる本数だけ等間隔に引き、
  // 両端は画面外にはみ出さないよう左/右寄せにする(縦軸ラベルと同じ配慮)。
  const tickCount = Math.max(2, Math.min(6, Math.floor(plotW / 80) + 1));
  ctx.fillStyle = fg;
  ctx.strokeStyle = line;
  for (let i = 0; i < tickCount; i++) {
    const t = t0 + ((t1 - t0) * i) / (tickCount - 1);
    const px = x(t);
    ctx.beginPath();
    ctx.moveTo(px, PAD + plotH);
    ctx.lineTo(px, PAD + plotH + 4);
    ctx.stroke();
    ctx.textAlign = i === 0 ? 'left' : i === tickCount - 1 ? 'right' : 'center';
    ctx.fillText(formatClock(t), px, PAD + plotH + 16);
  }
  ctx.textAlign = 'left';

  // 生の周波数の折れ線。null(欠測・不連続)をまたぐところは線をつながない。
  // **NOMINAL区間(fs未規正)は淡い点線で描き、規正済み区間と一見で区別できるようにする**
  // ——「測れなかった精度のものを測れたように見せない」の描画版(→ docs/timebase.md)。
  // 1点ずつ、区間の始点の timebase_source でその区間の線種を決める。
  const py = (f) => y(Math.min(Math.max(f, yMin), yMax));
  for (let i = 1; i < n; i++) {
    const f0 = series.freq_hz[i - 1], f1 = series.freq_hz[i];
    if (f0 == null || f1 == null) continue;
    const isNominal = series.timebase_source && series.timebase_source[i] === 'NOMINAL';
    ctx.save();
    ctx.strokeStyle = isNominal ? nominalColor : accent;
    ctx.lineWidth = isNominal ? 1.25 : 1.5;
    if (isNominal) ctx.setLineDash([2, 3]);
    ctx.beginPath();
    ctx.moveTo(x(series.t_us[i - 1]), py(f0));
    ctx.lineTo(x(series.t_us[i]), py(f1));
    ctx.stroke();
    ctx.restore();
  }

  // NOMINAL区間のうち、NTPロック後に事後補正できた「補正した予測値」を重ねて描く。
  // ロック前(現在進行形)はfreq_hz_correctedがNoneなので、まだ何も描かれない
  // ——ロックした瞬間、この線が過去へ遡って現れる。
  if (series.freq_hz_corrected && series.freq_hz_corrected.some((v) => v != null)) {
    ctx.save();
    ctx.strokeStyle = predictColor;
    ctx.lineWidth = 1.25;
    ctx.setLineDash([6, 3]);
    ctx.beginPath();
    let drawingPred = false;
    for (let i = 0; i < n; i++) {
      const fc = series.freq_hz_corrected[i];
      if (fc == null) { drawingPred = false; continue; }
      const px = x(series.t_us[i]);
      if (!drawingPred) { ctx.moveTo(px, py(fc)); drawingPred = true; } else { ctx.lineTo(px, py(fc)); }
    }
    ctx.stroke();
    ctx.restore();
  }
}

// --- ステータス行・品質テーブル ---
// deviceは生存台帳(/devices、→ docs/ota.md)の該当デバイス分。取得失敗時や
// まだ生存台帳を立てていない環境ではnull——その場合はビルド版数等の行を
// 省くだけで、/recentが主で描くグラフ・時間基準品質の表示は妨げない。
function renderStatus(series, device) {
  const el = document.getElementById('status');
  const latest = series.latest;
  if (!latest) {
    el.innerHTML = '<span class="status-ng">データなし</span>';
    return;
  }
  const ageS = (Date.now() * 1000 - latest.t_us) / 1e6;
  const staleClass = ageS > 60 ? 'status-ng' : 'status-ok';
  const devMhz = latest.freq_hz == null ? null : Math.round((latest.freq_hz - latest.f_nominal_hz) * 1000);
  const srcClass = SOURCE_CLASS[latest.timebase_source] || 'badge-nominal';
  const srcLabel = SOURCE_LABEL[latest.timebase_source] || latest.timebase_source;
  el.innerHTML =
    `<span class="${staleClass}">最終受信 ${ageS.toFixed(0)}秒前</span> ・ ` +
    (latest.freq_hz == null ? '周波数: 不連続区間' : `${latest.freq_hz.toFixed(3)}Hz (${devMhz >= 0 ? '+' : ''}${devMhz}mHz)`) +
    ` ・ <span class="badge ${srcClass}">${srcLabel}</span>` +
    (latest.is_disciplined ? '' : ' <span class="muted">(絶対時刻は未規正)</span>');

  const rows = [
    ['デバイス', latest.device_id],
    ['セッション', latest.session_id],
    ['公称周波数', latest.f_nominal_hz.toFixed(1) + 'Hz'],
    ['実効サンプルレート', latest.fs_measured_hz.toFixed(3) + 'Hz'],
    ['時間基準の確度(1σ)', latest.tb_residual_ns + 'ns/s'],
    ['SoC温度', latest.soc_temp_c + '℃'],
  ];
  // トランス二次側の実効値。v_rms_mvはワイヤフォーマット上の実測値そのもの
  // (→ docs/wire-format.md)なので、これ自体は概算扱いしない。
  if (latest.v_rms_mv != null) {
    rows.push(['トランス二次側電圧', (latest.v_rms_mv / 1000).toFixed(2) + 'V']);
    if (document.getElementById('show-wall-voltage').checked) {
      const wallV = (latest.v_rms_mv / 1000) * TURNS_RATIO_PROVISIONAL;
      // 巻数比が暫定値・AFE換算も1点校正のみなので、有効数字を絞って
      // 「精密な値に見える」ことを避ける(整数V止まり)。
      rows.push(['壁側電圧(概算)', `${Math.round(wallV)}V <span class="muted">(巻数比暫定・未校正)</span>`]);
    }
  }
  if (device && device.fw_version) rows.push(['ビルド版数', device.fw_version]);
  if (device && device.staleness_s != null) {
    // last_ingest_at_us(受信壁時計)ベース。latest.t_us(測定時刻)ベースの
    // 「最終受信」とは別系統——バックフィル中は測定側が古いまま見えても、
    // こちらは受信が続いているかどうかを独立に示す(→ batch_uplink.devices)。
    const ingestClass = device.staleness_s > 60 ? 'status-ng' : 'status-ok';
    rows.push(['受信(壁時計)', `<span class="${ingestClass}">${device.staleness_s.toFixed(0)}秒前</span>`]);
  }
  if (device && device.batches_total != null) rows.push(['累積受信バッチ数', device.batches_total]);
  if (device && device.pending_ota_version) {
    rows.push(['OTA', `${device.pending_ota_version} へ更新待ち`]);
  }
  document.querySelector('#quality-table tbody').innerHTML =
    rows.map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join('');
}

// --- メインループ ---
let refreshTimer = null;
// 壁側電圧チェックボックスの再描画用(再フェッチせず直前の値で出し直す)。
let lastSeries = null;
let lastDevice = null;

async function refresh() {
  const minutes = document.getElementById('minutes').value;
  try {
    const series = await apiGet(`/recent?minutes=${minutes}`);
    drawFreqChart(document.getElementById('freq-canvas'), series);
    // 生存台帳(/devices)は補助情報。取得できなくても(まだ立てていない環境・
    // 一時的な失敗)メインのグラフ・ステータス表示は妨げない。
    let device = null;
    try {
      const d = await apiGet('/devices');
      device = (d.devices || []).find((x) => x.device_id === series.latest?.device_id) || d.devices?.[0] || null;
    } catch (e) { /* 補助情報なので無視 */ }
    lastSeries = series;
    lastDevice = device;
    renderStatus(series, device);
  } catch (e) {
    document.getElementById('status').innerHTML = `<span class="status-ng">取得失敗: ${e.message}</span>`;
  }
}

function scheduleAutoRefresh() {
  if (refreshTimer) clearInterval(refreshTimer);
  if (document.getElementById('autorefresh').checked) {
    refreshTimer = setInterval(refresh, 10_000);
  }
}

function initApiSettings() {
  const input = document.getElementById('api');
  const base = apiBase();
  if (!base) {
    document.getElementById('api-settings').style.display = '';
  }
  input.value = base;
  document.getElementById('save-api').addEventListener('click', () => {
    localStorage.setItem('elbz_api', input.value.trim().replace(/\/$/, ''));
    refresh();
  });
}

window.addEventListener('DOMContentLoaded', () => {
  initApiSettings();
  document.getElementById('minutes').addEventListener('change', refresh);
  document.getElementById('autorefresh').addEventListener('change', scheduleAutoRefresh);
  document.getElementById('refresh-now').addEventListener('click', refresh);
  document.getElementById('show-wall-voltage').addEventListener('change', () => {
    if (lastSeries) renderStatus(lastSeries, lastDevice);
  });
  window.addEventListener('resize', () => refresh());
  refresh();
  scheduleAutoRefresh();
});
