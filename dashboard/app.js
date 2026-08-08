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

function themeColor(varName) {
  return getComputedStyle(document.documentElement).getPropertyValue(varName).trim();
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
  const plotW = w - PAD * 2;
  const plotH = h - PAD * 2;

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

  const x = (t) => PAD + ((t - t0) / (t1 - t0 || 1)) * plotW;
  const y = (f) => PAD + (1 - (f - yMin) / (yMax - yMin || 1)) * plotH;

  // 軸・公称値の破線
  ctx.strokeStyle = line;
  ctx.lineWidth = 1;
  ctx.strokeRect(PAD, PAD, plotW, plotH);
  ctx.save();
  ctx.setLineDash([4, 4]);
  ctx.beginPath();
  ctx.moveTo(PAD, y(fNom));
  ctx.lineTo(PAD + plotW, y(fNom));
  ctx.stroke();
  ctx.restore();

  ctx.fillStyle = fg;
  ctx.font = '11px system-ui, sans-serif';
  ctx.textAlign = 'right';
  ctx.fillText(yMax.toFixed(3) + 'Hz', PAD - 4, PAD + 4);
  ctx.fillText(yMin.toFixed(3) + 'Hz', PAD - 4, PAD + plotH);
  ctx.fillText(fNom.toFixed(0) + 'Hz', PAD - 4, y(fNom) + 4);
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
function renderStatus(series) {
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
  document.querySelector('#quality-table tbody').innerHTML =
    rows.map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join('');
}

// --- メインループ ---
let refreshTimer = null;

async function refresh() {
  const minutes = document.getElementById('minutes').value;
  try {
    const series = await apiGet(`/recent?minutes=${minutes}`);
    drawFreqChart(document.getElementById('freq-canvas'), series);
    renderStatus(series);
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
  window.addEventListener('resize', () => refresh());
  refresh();
  scheduleAutoRefresh();
});
