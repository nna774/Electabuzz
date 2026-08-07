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

  // 周波数の折れ線。null(欠測・不連続)をまたぐところは線をつながない。
  ctx.strokeStyle = accent;
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  let drawing = false;
  for (let i = 0; i < n; i++) {
    const f = series.freq_hz[i];
    if (f == null) { drawing = false; continue; }
    const px = x(series.t_us[i]), py = y(Math.min(Math.max(f, yMin), yMax));
    if (!drawing) { ctx.moveTo(px, py); drawing = true; } else { ctx.lineTo(px, py); }
  }
  ctx.stroke();
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
  window.addEventListener('resize', () => refresh());
  refresh();
  scheduleAutoRefresh();
});
