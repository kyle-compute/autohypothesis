from __future__ import annotations

import json
import subprocess
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse


REPO_ROOT = Path(__file__).resolve().parent.parent
EXPERIMENTS_FILE = REPO_ROOT / "experiments.jsonl"

app = FastAPI(title="autoresearch dashboard")


BASE_CSS = """
:root {
  color-scheme: dark;
  --bg: #0b1020;
  --panel: rgba(13, 20, 38, 0.92);
  --panel-2: rgba(17, 27, 50, 0.92);
  --border: rgba(148, 163, 184, 0.18);
  --text: #e5edf7;
  --muted: #93a4bc;
  --green: #22c55e;
  --green-bg: rgba(34, 197, 94, 0.14);
  --red: #f87171;
  --red-bg: rgba(248, 113, 113, 0.14);
  --amber: #f59e0b;
  --amber-bg: rgba(245, 158, 11, 0.14);
  --blue: #60a5fa;
  --blue-bg: rgba(96, 165, 250, 0.14);
  --shadow: 0 24px 60px rgba(0, 0, 0, 0.28);
  --radius: 18px;
  --radius-sm: 12px;
  --mono: "SFMono-Regular", "SF Mono", Consolas, "Liberation Mono", Menlo, monospace;
  --sans: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

* { box-sizing: border-box; }
html, body { margin: 0; min-height: 100%; background:
  radial-gradient(circle at top left, rgba(96, 165, 250, 0.18), transparent 28%),
  radial-gradient(circle at top right, rgba(34, 197, 94, 0.12), transparent 24%),
  linear-gradient(180deg, #0b1020 0%, #0c1224 100%);
  color: var(--text);
  font-family: var(--sans);
}
a { color: inherit; }

.shell {
  max-width: 1500px;
  margin: 0 auto;
  padding: 24px;
}

.topbar {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: center;
  margin-bottom: 20px;
}

.brand {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.eyebrow {
  color: var(--muted);
  font-size: 12px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.title {
  font-size: 28px;
  font-weight: 700;
}

.subtitle {
  color: var(--muted);
  max-width: 760px;
  line-height: 1.5;
}

.nav {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.nav a {
  text-decoration: none;
  border: 1px solid var(--border);
  background: var(--panel);
  padding: 10px 14px;
  border-radius: 999px;
}

.nav a.active {
  background: var(--panel-2);
  border-color: rgba(96, 165, 250, 0.42);
  color: #dbeafe;
}

.panel {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  backdrop-filter: blur(18px);
}

.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 14px;
  margin-bottom: 18px;
}

.stat {
  padding: 16px 18px;
}

.stat-label {
  color: var(--muted);
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  margin-bottom: 10px;
}

.stat-value {
  font-size: 26px;
  font-weight: 700;
}

.layout {
  display: grid;
  grid-template-columns: minmax(0, 1.7fr) minmax(320px, 0.9fr);
  gap: 18px;
}

.graph-panel {
  padding: 16px;
  overflow: hidden;
}

.detail-panel {
  padding: 18px;
  min-height: 640px;
}

.section-title {
  font-size: 16px;
  font-weight: 700;
  margin-bottom: 12px;
}

.graph-wrap {
  width: 100%;
  min-height: 640px;
  overflow: auto;
  border-radius: var(--radius-sm);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.02), transparent),
    rgba(3, 8, 20, 0.32);
  border: 1px solid rgba(148, 163, 184, 0.08);
}

.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 14px;
}

.legend-item {
  display: inline-flex;
  gap: 8px;
  align-items: center;
  padding: 8px 12px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(148, 163, 184, 0.12);
  color: var(--muted);
  font-size: 13px;
}

.legend-dot {
  width: 10px;
  height: 10px;
  border-radius: 999px;
}

.empty {
  color: var(--muted);
  padding: 40px 8px;
}

.badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.badge.keep { background: var(--green-bg); color: var(--green); }
.badge.discard { background: var(--red-bg); color: var(--red); }
.badge.crash { background: var(--amber-bg); color: var(--amber); }
.badge.replicate { background: var(--blue-bg); color: var(--blue); }

.detail-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.detail-title h2 {
  margin: 0;
  font-size: 24px;
}

.detail-block {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid rgba(148, 163, 184, 0.12);
}

.kv {
  display: grid;
  grid-template-columns: 110px minmax(0, 1fr);
  gap: 8px 12px;
  align-items: start;
  font-size: 14px;
}

.kv .k {
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  font-size: 11px;
  margin-top: 3px;
}

.mono {
  font-family: var(--mono);
}

.pill-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.pill {
  padding: 7px 10px;
  border-radius: 999px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  background: rgba(255, 255, 255, 0.04);
  font-size: 12px;
  font-family: var(--mono);
}

.grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.metric {
  padding: 12px;
  border-radius: var(--radius-sm);
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(148, 163, 184, 0.12);
}

.metric-label {
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 6px;
}

.metric-value {
  font-size: 18px;
  font-weight: 700;
}

.muted {
  color: var(--muted);
}

.diff-toggle {
  margin-top: 12px;
  display: inline-flex;
  gap: 8px;
  align-items: center;
  border-radius: 999px;
  background: var(--panel-2);
  border: 1px solid rgba(96, 165, 250, 0.3);
  padding: 10px 14px;
  color: #dbeafe;
  cursor: pointer;
}

.diff {
  margin-top: 12px;
  border-radius: var(--radius-sm);
  padding: 12px;
  border: 1px solid rgba(148, 163, 184, 0.12);
  background: rgba(0, 0, 0, 0.28);
  overflow: auto;
  max-height: 280px;
  white-space: pre-wrap;
  font-family: var(--mono);
  font-size: 12px;
}

.decision-md {
  margin-top: 12px;
  border-radius: var(--radius-sm);
  padding: 12px;
  border: 1px solid rgba(148, 163, 184, 0.12);
  background: rgba(0, 0, 0, 0.2);
  overflow: auto;
  max-height: 340px;
  white-space: pre-wrap;
  font-family: var(--mono);
  font-size: 12px;
}

.link-card {
  display: grid;
  gap: 10px;
  padding: 22px;
}

.link-card a {
  text-decoration: none;
}

.hero-value {
  font-size: 46px;
  font-weight: 800;
}

.hero-sub {
  color: var(--muted);
}

svg text {
  font-family: var(--mono);
}

@media (max-width: 1100px) {
  .layout {
    grid-template-columns: 1fr;
  }

  .detail-panel {
    min-height: auto;
  }
}
"""


INDEX_BODY = """
<div class="shell">
  <div class="topbar">
    <div class="brand">
      <div class="eyebrow">Autoresearch Dashboard</div>
      <div class="title">Run Summary</div>
      <div class="subtitle">Derived from root-level <span class="mono">experiments.jsonl</span>, which is exported by <span class="mono">uv run python orchestrator.py sync</span>.</div>
    </div>
    <div class="nav">
      <a class="active" href="/">Latest</a>
      <a href="/history">History</a>
      <a href="/api/experiments">API</a>
    </div>
  </div>

  <div class="stats" id="stats"></div>

  <div class="layout">
    <div class="panel link-card" id="latest-card">
      <div class="section-title">Latest Experiment</div>
      <div class="empty">Waiting for experiment data.</div>
    </div>
    <div class="panel link-card">
      <div class="section-title">Next Step</div>
      <div class="subtitle">Run <span class="mono">uv run python orchestrator.py sync</span> after completed experiments, then refresh <span class="mono">/history</span>.</div>
      <a class="diff-toggle" href="/history">Open lineage graph</a>
    </div>
  </div>
</div>
"""


INDEX_SCRIPT = """
const fmt = (value, digits = 4) => Number.isFinite(value) ? value.toFixed(digits) : 'n/a';

function badge(status) {
  return `<span class="badge ${status}">${status}</span>`;
}

function statCard(label, value, subtitle = '') {
  return `
    <div class="panel stat">
      <div class="stat-label">${label}</div>
      <div class="stat-value">${value}</div>
      ${subtitle ? `<div class="muted">${subtitle}</div>` : ''}
    </div>
  `;
}

function compareExperiments(a, b) {
  const aOrdinal = Number.isFinite(a.ordinal) ? a.ordinal : null;
  const bOrdinal = Number.isFinite(b.ordinal) ? b.ordinal : null;
  if (aOrdinal != null && bOrdinal != null && aOrdinal !== bOrdinal) {
    return aOrdinal - bOrdinal;
  }
  if (aOrdinal != null && bOrdinal == null) return -1;
  if (aOrdinal == null && bOrdinal != null) return 1;
  const aTime = a.timestamp || '';
  const bTime = b.timestamp || '';
  if (aTime !== bTime) {
    return aTime.localeCompare(bTime);
  }
  return String(a.id || '').localeCompare(String(b.id || ''));
}

function runLabel(item) {
  if (Number.isFinite(item.ordinal) && item.ordinal > 0) {
    return `#${item.ordinal}`;
  }
  return item.id || 'n/a';
}

async function load() {
  const res = await fetch('/api/experiments');
  const records = res.ok ? await res.json() : [];
  const stats = document.getElementById('stats');
  const latestCard = document.getElementById('latest-card');

  if (!records.length) {
    stats.innerHTML = [
      statCard('Runs', '0'),
      statCard('Kept', '0'),
      statCard('Best BPB', 'n/a'),
    ].join('');
    return;
  }

  records.sort(compareExperiments);
  const latest = records[records.length - 1];
  const kept = records.filter((item) => item.status === 'keep' || item.status === 'replicate');
  const best = kept.reduce((bestSoFar, item) => {
    if (!bestSoFar) return item;
    return item.val_bpb < bestSoFar.val_bpb ? item : bestSoFar;
  }, null);

  stats.innerHTML = [
    statCard('Runs', String(records.length)),
    statCard('Kept', String(kept.length)),
    statCard('Best BPB', best ? fmt(best.val_bpb, 6) : 'n/a', best ? best.commit : ''),
  ].join('');

  latestCard.innerHTML = `
    <div class="section-title">Latest Experiment</div>
    <div class="hero-value">${fmt(latest.val_bpb, 6)}</div>
    <div class="hero-sub">val_bpb</div>
    <div>${badge(latest.status)}</div>
    <div class="subtitle">${latest.description || 'No description'}</div>
    <div class="kv">
      <div class="k">Run</div><div class="mono">${runLabel(latest)}</div>
      <div class="k">Commit</div><div class="mono">${latest.commit || 'unknown'}</div>
      <div class="k">Parent</div><div class="mono">${latest.parent_commit || 'root'}</div>
      <div class="k">When</div><div>${latest.timestamp || 'n/a'}</div>
      <div class="k">Worker</div><div>${latest.worker_id || 'n/a'}${latest.gpu_id ? ' / gpu ' + latest.gpu_id : ''}</div>
    </div>
    <a class="diff-toggle" href="/history">Inspect decision graph</a>
  `;
}

load();
"""


HISTORY_BODY = """
<div class="shell">
  <div class="topbar">
    <div class="brand">
      <div class="eyebrow">Autoresearch Dashboard</div>
      <div class="title">History</div>
      <div class="subtitle">Lineage view of completed runs exported from the current orchestrator. Edges are driven by <span class="mono">parent_commit</span>, not by mutable brief state.</div>
    </div>
    <div class="nav">
      <a href="/">Latest</a>
      <a class="active" href="/history">History</a>
      <a href="/api/experiments">API</a>
    </div>
  </div>

  <div class="stats" id="stats"></div>

  <div class="legend">
    <div class="legend-item"><span class="legend-dot" style="background: var(--green)"></span>keep</div>
    <div class="legend-item"><span class="legend-dot" style="background: var(--blue)"></span>replicate</div>
    <div class="legend-item"><span class="legend-dot" style="background: var(--red)"></span>discard</div>
    <div class="legend-item"><span class="legend-dot" style="background: var(--amber)"></span>crash</div>
  </div>

  <div class="layout">
    <div class="panel graph-panel">
      <div class="section-title">Lineage Graph</div>
      <div class="graph-wrap" id="graph-wrap">
        <div class="empty" id="graph-empty">Waiting for experiment data.</div>
        <svg id="graph" width="100%" height="640" aria-label="experiment history graph"></svg>
      </div>
    </div>

    <aside class="panel detail-panel">
      <div class="section-title">Experiment Detail</div>
      <div id="detail-empty" class="empty">Select a node to inspect lineage, hyperparameter deltas, the scientific decision note, rationale, and outcome.</div>
      <div id="detail" hidden></div>
    </aside>
  </div>
</div>
"""


HISTORY_SCRIPT = """
const STATUS_COLORS = {
  keep: '#22c55e',
  replicate: '#60a5fa',
  discard: '#f87171',
  crash: '#f59e0b',
};

const PARAM_KEYS = [
  'depth',
  'model_dim',
  'n_heads',
  'head_dim',
  'window_pattern',
  'total_batch_size',
  'device_batch_size',
  'matrix_lr',
  'embedding_lr',
  'weight_decay',
  'warmdown_ratio',
];

let experiments = [];
let selectedId = null;
let graphWidth = 1200;
const graphHeight = 640;
const padding = { top: 56, right: 84, bottom: 72, left: 84 };

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function fmt(value, digits = 4) {
  return Number.isFinite(value) ? Number(value).toFixed(digits) : 'n/a';
}

function compareExperiments(a, b) {
  const aOrdinal = Number.isFinite(a.ordinal) ? a.ordinal : null;
  const bOrdinal = Number.isFinite(b.ordinal) ? b.ordinal : null;
  if (aOrdinal != null && bOrdinal != null && aOrdinal !== bOrdinal) {
    return aOrdinal - bOrdinal;
  }
  if (aOrdinal != null && bOrdinal == null) return -1;
  if (aOrdinal == null && bOrdinal != null) return 1;
  const aTime = a.timestamp || '';
  const bTime = b.timestamp || '';
  if (aTime !== bTime) {
    return aTime.localeCompare(bTime);
  }
  return String(a.id || '').localeCompare(String(b.id || ''));
}

function runLabel(exp) {
  if (Number.isFinite(exp.ordinal) && exp.ordinal > 0) {
    return `#${exp.ordinal}`;
  }
  return exp.id || 'n/a';
}

function metricCard(label, value) {
  return `<div class="metric"><div class="metric-label">${label}</div><div class="metric-value">${value}</div></div>`;
}

function statusBadge(status) {
  return `<span class="badge ${status}">${escapeHtml(status)}</span>`;
}

function renderStats() {
  const stats = document.getElementById('stats');
  if (!experiments.length) {
    stats.innerHTML = [
      '<div class="panel stat"><div class="stat-label">Runs</div><div class="stat-value">0</div></div>',
      '<div class="panel stat"><div class="stat-label">Kept</div><div class="stat-value">0</div></div>',
      '<div class="panel stat"><div class="stat-label">Best BPB</div><div class="stat-value">n/a</div></div>',
    ].join('');
    return;
  }
  const terminal = experiments.length;
  const kept = experiments.filter((item) => item.status === 'keep' || item.status === 'replicate');
  const best = kept.reduce((bestSoFar, item) => {
    if (!bestSoFar) return item;
    return item.val_bpb < bestSoFar.val_bpb ? item : bestSoFar;
  }, null);
  const crashes = experiments.filter((item) => item.status === 'crash').length;
  const latest = experiments[experiments.length - 1];
  stats.innerHTML = [
    `<div class="panel stat"><div class="stat-label">Runs</div><div class="stat-value">${terminal}</div></div>`,
    `<div class="panel stat"><div class="stat-label">Kept</div><div class="stat-value">${kept.length}</div></div>`,
    `<div class="panel stat"><div class="stat-label">Best BPB</div><div class="stat-value">${best ? fmt(best.val_bpb, 6) : 'n/a'}</div><div class="muted mono">${best ? escapeHtml(best.commit) : ''}</div></div>`,
    `<div class="panel stat"><div class="stat-label">Crashes</div><div class="stat-value">${crashes}</div></div>`,
    `<div class="panel stat"><div class="stat-label">Latest</div><div class="stat-value">${escapeHtml(runLabel(latest))}</div><div class="muted mono">${escapeHtml(latest.commit)}</div></div>`,
  ].join('');
}

function lineageSet(exp) {
  const byCommit = new Map(experiments.map((item) => [item.commit, item]));
  const related = new Set();
  let cursor = exp;
  while (cursor) {
    related.add(cursor.id);
    cursor = cursor.parent_commit ? byCommit.get(cursor.parent_commit) : null;
  }

  const queue = [exp];
  while (queue.length) {
    const current = queue.shift();
    for (const child of experiments.filter((item) => item.parent_commit === current.commit)) {
      if (!related.has(child.id)) {
        related.add(child.id);
        queue.push(child);
      }
    }
  }
  return related;
}

function buildLayout() {
  const wrap = document.getElementById('graph-wrap');
  const count = Math.max(experiments.length, 1);
  graphWidth = Math.max(wrap.clientWidth - 2, count * 150);

  const yValues = experiments.map((item) => item.val_bpb);
  const minY = yValues.length ? Math.min(...yValues) : 0;
  const maxY = yValues.length ? Math.max(...yValues) : 1;
  const range = Math.max(maxY - minY, 0.01);

  return experiments.map((item, index) => {
    const x = count === 1
      ? graphWidth / 2
      : padding.left + (index / (count - 1)) * (graphWidth - padding.left - padding.right);
    const y = padding.top + ((item.val_bpb - minY) / range) * (graphHeight - padding.top - padding.bottom);
    const radius = item.status === 'keep' ? 16 : item.status === 'replicate' ? 14 : item.status === 'crash' ? 11 : 10;
    return { ...item, x, y, radius };
  });
}

function paramChanges(exp) {
  const parent = experiments.find((item) => item.commit === exp.parent_commit);
  if (!parent) return [];
  return PARAM_KEYS.flatMap((key) => {
    const before = parent[key];
    const after = exp[key];
    if (before == null || after == null) return [];
    if (String(before) === String(after)) return [];
    return [{ key, before, after }];
  });
}

async function showDetail(exp) {
  selectedId = exp.id;
  const detail = document.getElementById('detail');
  const empty = document.getElementById('detail-empty');
  empty.hidden = true;
  detail.hidden = false;

  const changes = paramChanges(exp);
  const checkpoints = Array.isArray(exp.bpb_at_checkpoints) ? exp.bpb_at_checkpoints : [];
  const kvRows = [
    ['Commit', `<span class="mono">${escapeHtml(exp.commit || 'unknown')}</span>`],
    ['Parent', `<span class="mono">${escapeHtml(exp.parent_commit || 'root')}</span>`],
    ['Timestamp', escapeHtml(exp.timestamp || 'n/a')],
    ['Execution', escapeHtml(exp.execution_status || 'n/a')],
    ['Decision', escapeHtml(exp.decision_status || exp.status || 'n/a')],
    ['Worker', escapeHtml(exp.worker_id || 'n/a')],
    ['GPU', escapeHtml(exp.gpu_name || (exp.gpu_id ? 'GPU ' + exp.gpu_id : 'n/a'))],
    ['Hypothesis', escapeHtml(exp.hypothesis_id || 'n/a')],
  ].map(([key, value]) => `<div class="k">${key}</div><div>${value}</div>`).join('');

  detail.innerHTML = `
    <div class="detail-title">
      <h2>${escapeHtml(runLabel(exp))}</h2>
      ${statusBadge(exp.status)}
    </div>
    <div class="hero-value">${fmt(exp.val_bpb, 6)}</div>
    <div class="hero-sub">val_bpb</div>

    <div class="detail-block">
      <div class="kv">${kvRows}</div>
      <div class="muted mono" style="margin-top:10px;">run_id ${escapeHtml(exp.id || 'n/a')}</div>
    </div>

    <div class="detail-block">
      <div class="section-title">Decision</div>
      <div>${escapeHtml(exp.description || 'No description')}</div>
      ${exp.rationale ? `<div class="muted" style="margin-top:10px;"><strong>Rationale:</strong> ${escapeHtml(exp.rationale)}</div>` : ''}
      ${exp.outcome ? `<div class="muted" style="margin-top:10px;"><strong>Outcome:</strong> ${escapeHtml(exp.outcome)}</div>` : ''}
      ${exp.notes ? `<div class="muted" style="margin-top:10px;"><strong>Notes:</strong> ${escapeHtml(exp.notes)}</div>` : ''}
    </div>

    <div class="detail-block">
      <div class="section-title">Scientific Decision Markdown</div>
      <div class="muted" id="decision-path">Loading decision.md path...</div>
      <button class="diff-toggle" id="decision-toggle" type="button">Load decision.md</button>
      <pre class="decision-md" id="decision-md" hidden></pre>
    </div>

    <div class="detail-block">
      <div class="section-title">Hyperparameter Delta</div>
      ${changes.length ? `<div class="pill-row">${changes.map((item) => `<div class="pill">${escapeHtml(item.key)} ${escapeHtml(item.before)} → ${escapeHtml(item.after)}</div>`).join('')}</div>` : '<div class="muted">No parent diff available.</div>'}
    </div>

    <div class="detail-block">
      <div class="section-title">Metrics</div>
      <div class="grid">
        ${metricCard('Delta vs prior best', fmt(exp.delta, 6))}
        ${metricCard('Train BPB', fmt(exp.train_bpb, 6))}
        ${metricCard('Steps', escapeHtml(exp.num_steps ?? '0'))}
        ${metricCard('tok/sec', escapeHtml((exp.tokens_per_second ?? 0).toLocaleString()))}
        ${metricCard('Train seconds', fmt(exp.training_seconds, 1))}
        ${metricCard('Total seconds', fmt(exp.total_seconds, 1))}
        ${metricCard('VRAM GB', fmt(exp.peak_vram_gb, 2))}
        ${metricCard('Params M', fmt(exp.num_params_M, 2))}
      </div>
    </div>

    <div class="detail-block">
      <div class="section-title">Architecture</div>
      <div class="pill-row">
        <div class="pill">depth ${escapeHtml(exp.depth)}</div>
        <div class="pill">model_dim ${escapeHtml(exp.model_dim)}</div>
        <div class="pill">n_heads ${escapeHtml(exp.n_heads)}</div>
        <div class="pill">head_dim ${escapeHtml(exp.head_dim)}</div>
        <div class="pill">window ${escapeHtml(exp.window_pattern || 'n/a')}</div>
        <div class="pill">batch ${escapeHtml(exp.total_batch_size)}</div>
        <div class="pill">device_batch ${escapeHtml(exp.device_batch_size)}</div>
      </div>
    </div>

    <div class="detail-block">
      <div class="section-title">Convergence</div>
      ${checkpoints.length ? `<div class="pill-row">${checkpoints.map((value, index) => `<div class="pill">${(index + 1) * 25}% ${fmt(value, 4)}</div>`).join('')}</div>` : '<div class="muted">No checkpoint samples recorded.</div>'}
      ${exp.still_improving ? '<div class="muted" style="margin-top:10px;">Loss was still improving at budget end.</div>' : ''}
    </div>

    <button class="diff-toggle" id="diff-toggle" type="button">Load train.py diff</button>
    <pre class="diff" id="diff" hidden></pre>
  `;

  document.getElementById('diff-toggle').addEventListener('click', async () => {
    const diff = document.getElementById('diff');
    if (!diff.hidden) {
      diff.hidden = true;
      return;
    }
    diff.textContent = 'Loading diff...';
    diff.hidden = false;
    try {
      const res = await fetch(`/api/experiments/${encodeURIComponent(String(exp.id))}/diff`);
      const payload = res.ok ? await res.json() : { diff: '' };
      diff.textContent = payload.diff || 'No diff available for this experiment.';
    } catch (error) {
      diff.textContent = 'Failed to load diff.';
    }
  });

  document.getElementById('decision-toggle').addEventListener('click', async () => {
    const md = document.getElementById('decision-md');
    if (!md.hidden) {
      md.hidden = true;
      return;
    }
    md.textContent = 'Loading decision markdown...';
    md.hidden = false;
    try {
      const res = await fetch(`/api/experiments/${encodeURIComponent(String(exp.id))}/decision-md`);
      const payload = res.ok ? await res.json() : { content: '', path: '' };
      const pathEl = document.getElementById('decision-path');
      pathEl.textContent = payload.path || 'No scientific decision markdown recorded yet.';
      md.textContent = payload.content || 'No scientific decision markdown available for this run.';
    } catch (error) {
      md.textContent = 'Failed to load decision markdown.';
    }
  });

  (async () => {
    try {
      const res = await fetch(`/api/experiments/${encodeURIComponent(String(exp.id))}/decision-md`);
      const payload = res.ok ? await res.json() : {};
      const pathEl = document.getElementById('decision-path');
      pathEl.textContent = payload.path || 'No scientific decision markdown recorded yet.';
    } catch (error) {
      const pathEl = document.getElementById('decision-path');
      pathEl.textContent = 'Failed to load decision markdown path.';
    }
  })();

  renderGraph();
}

function renderGraph() {
  const svg = document.getElementById('graph');
  const empty = document.getElementById('graph-empty');
  if (!experiments.length) {
    empty.hidden = false;
    svg.innerHTML = '';
    return;
  }
  empty.hidden = true;

  const layout = buildLayout();
  const byCommit = new Map(layout.map((item) => [item.commit, item]));
  const selected = selectedId != null ? layout.find((item) => item.id === selectedId) : null;
  const related = selected ? lineageSet(selected) : new Set();

  svg.setAttribute('viewBox', `0 0 ${graphWidth} ${graphHeight}`);
  svg.setAttribute('width', String(graphWidth));
  svg.setAttribute('height', String(graphHeight));

  const yValues = layout.map((item) => item.val_bpb);
  const minY = Math.min(...yValues);
  const maxY = Math.max(...yValues);
  const ticks = 4;

  const gridLines = Array.from({ length: ticks + 1 }).map((_, index) => {
    const y = padding.top + (index / ticks) * (graphHeight - padding.top - padding.bottom);
    const value = minY + (index / ticks) * (maxY - minY || 1);
    return `
      <line x1="${padding.left}" y1="${y}" x2="${graphWidth - padding.right}" y2="${y}" stroke="rgba(148,163,184,0.12)" stroke-dasharray="4 8" />
      <text x="${padding.left - 16}" y="${y + 4}" text-anchor="end" fill="rgba(147,164,188,0.85)" font-size="11">${fmt(value, 4)}</text>
    `;
  }).join('');

  const edges = layout.map((item) => {
    const parent = byCommit.get(item.parent_commit);
    if (!parent) return '';
    const active = !selected || (related.has(item.id) && related.has(parent.id));
    const opacity = active ? 0.85 : 0.18;
    const stroke = item.status === 'keep' || item.status === 'replicate' ? 'rgba(96, 165, 250, 0.72)' : 'rgba(148, 163, 184, 0.38)';
    const dx = item.x - parent.x;
    return `<path d="M ${parent.x} ${parent.y} C ${parent.x + dx * 0.45} ${parent.y}, ${item.x - dx * 0.45} ${item.y}, ${item.x} ${item.y}" fill="none" stroke="${stroke}" stroke-width="${active ? 2.4 : 1.4}" opacity="${opacity}" />`;
  }).join('');

  const nodes = layout.map((item) => {
    const active = !selected || related.has(item.id);
    const stroke = STATUS_COLORS[item.status] || '#cbd5e1';
    const fill = item.status === 'discard' ? 'rgba(248, 113, 113, 0.16)' : item.status === 'crash' ? 'rgba(245, 158, 11, 0.18)' : item.status === 'replicate' ? 'rgba(96, 165, 250, 0.18)' : 'rgba(34, 197, 94, 0.18)';
    const opacity = active ? 1 : 0.24;
    const labelY = item.y - item.radius - 10;
    return `
      <g class="node" data-id="${item.id}" style="cursor:pointer;">
        <circle cx="${item.x}" cy="${item.y}" r="${item.radius}" fill="${fill}" stroke="${stroke}" stroke-width="${selected && selected.id === item.id ? 4 : 2.2}" opacity="${opacity}" />
        <text x="${item.x}" y="${item.y + 4}" text-anchor="middle" fill="rgba(229,237,247,0.9)" font-size="11" opacity="${opacity}">${escapeHtml(runLabel(item))}</text>
        <text x="${item.x}" y="${labelY}" text-anchor="middle" fill="rgba(229,237,247,0.85)" font-size="11" opacity="${opacity}">${fmt(item.val_bpb, 4)}</text>
      </g>
    `;
  }).join('');

  svg.innerHTML = `
    <rect x="0" y="0" width="${graphWidth}" height="${graphHeight}" fill="transparent" />
    ${gridLines}
    ${edges}
    <text x="${graphWidth / 2}" y="${graphHeight - 16}" text-anchor="middle" fill="rgba(147,164,188,0.85)" font-size="12">experiment order</text>
    <text x="22" y="${graphHeight / 2}" transform="rotate(-90 22 ${graphHeight / 2})" text-anchor="middle" fill="rgba(147,164,188,0.85)" font-size="12">val_bpb</text>
    ${nodes}
  `;

  Array.from(svg.querySelectorAll('.node')).forEach((node) => {
    node.addEventListener('click', () => {
      const id = node.getAttribute('data-id');
      const exp = experiments.find((item) => item.id === id);
      if (exp) showDetail(exp);
    });
  });
}

async function loadExperiments() {
  const res = await fetch('/api/experiments');
  experiments = res.ok ? await res.json() : [];
  experiments.sort(compareExperiments);
  renderStats();
  renderGraph();
  if (selectedId != null) {
    const selected = experiments.find((item) => item.id === selectedId);
    if (selected) {
      showDetail(selected);
    }
  }
}

window.addEventListener('resize', renderGraph);
loadExperiments();
setInterval(loadExperiments, 5000);
"""


def _page(title: str, body: str, script: str) -> str:
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{title}</title>
    <style>{BASE_CSS}</style>
  </head>
  <body>
    {body}
    <script>{script}</script>
  </body>
</html>
"""


def _load_aggregate_hyperparams() -> dict[str, dict]:
    """Load hyperparameters from aggregate/experiments.json, keyed by experiment_id."""
    agg_path = REPO_ROOT / "research" / "aggregate" / "experiments.json"
    if not agg_path.exists():
        return {}
    try:
        data = json.loads(agg_path.read_text())
        result = {}
        for exp in data.get("experiments", []):
            hp = exp.get("config", {}).get("hyperparameters")
            if hp:
                result[exp["experiment_id"]] = hp
        return result
    except (json.JSONDecodeError, KeyError):
        return {}


def _enrich_record(record: dict, agg_hp: dict[str, dict]) -> None:
    """Enrich a record with data from metadata.json and aggregate hyperparams."""
    exp_id = record.get("id", "")
    run_dir = REPO_ROOT / "research" / "runs" / exp_id

    # Enrich metrics from metadata.json
    meta_path = run_dir / "metadata.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
            results = meta.get("results", {})
            # Fill zero metrics from metadata results
            metric_keys = [
                "num_steps", "training_seconds", "total_seconds",
                "mfu_percent", "total_tokens_M", "num_params_M",
            ]
            for key in metric_keys:
                if not record.get(key) and results.get(key):
                    record[key] = results[key]
            # peak_vram: metadata uses MB, record uses GB
            if not record.get("peak_vram_gb") and results.get("peak_vram_mb"):
                record["peak_vram_gb"] = results["peak_vram_mb"] / 1024
            # depth
            if not record.get("depth") and results.get("depth"):
                record["depth"] = results["depth"]
            # Attach hyperparameters
            if meta.get("hyperparameters"):
                record["hyperparameters"] = meta["hyperparameters"]
        except (json.JSONDecodeError, KeyError):
            pass

    # Fallback hyperparameters from aggregate
    if not record.get("hyperparameters") and exp_id in agg_hp:
        record["hyperparameters"] = agg_hp[exp_id]

    # Ensure hyperparameters key exists
    if "hyperparameters" not in record:
        record["hyperparameters"] = {}


def _load_records() -> list[dict]:
    if not EXPERIMENTS_FILE.exists():
        return []
    records = []
    for line in EXPERIMENTS_FILE.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    # Enrich records with metadata
    agg_hp = _load_aggregate_hyperparams()
    for record in records:
        _enrich_record(record, agg_hp)

    records.sort(
        key=lambda item: (
            item.get("ordinal", 0),
            item.get("timestamp", ""),
            str(item.get("id", "")),
        )
    )
    return records


def _load_record(exp_id: str) -> dict | None:
    for record in _load_records():
        if str(record.get("id")) == exp_id:
            return record
    return None


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}


def _relative_or_absolute(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _find_run_dir_for_commit(commit: str) -> tuple[Path, dict, dict] | None:
    if not commit:
        return None
    runs_dir = REPO_ROOT / "research" / "runs"
    if not runs_dir.exists():
        return None
    for run_dir in sorted(runs_dir.iterdir()):
        if not run_dir.is_dir():
            continue
        result = _read_json(run_dir / "result.json")
        metadata = _read_json(run_dir / "metadata.json")
        result_commit = result.get("commit") or metadata.get("runtime", {}).get("commit")
        if result_commit == commit:
            return run_dir, result, metadata
    return None


def _decision_markdown_for_record(record: dict) -> dict:
    inline_content = record.get("decision_markdown") or ""
    inline_path = record.get("decision_markdown_path") or ""
    if inline_content or inline_path:
        resolved_path = ""
        if inline_path:
            candidate = Path(inline_path)
            if not candidate.is_absolute():
                candidate = REPO_ROOT / candidate
            resolved_path = _relative_or_absolute(candidate)
            if not inline_content and candidate.exists():
                inline_content = candidate.read_text()
        return {
            "exists": bool(inline_content),
            "path": resolved_path,
            "content": inline_content,
            "commit": record.get("commit", ""),
        }

    commit = record.get("commit", "")
    match = _find_run_dir_for_commit(commit)
    if match is None:
        return {
            "exists": False,
            "path": "",
            "content": "",
            "commit": commit,
        }

    run_dir, result, metadata = match
    candidate_paths: list[Path] = []

    for payload in (result, metadata):
        for key in ("decision_md_path", "decision_markdown_path"):
            raw_path = payload.get(key)
            if not raw_path:
                continue
            candidate = Path(raw_path)
            if not candidate.is_absolute():
                candidate = REPO_ROOT / candidate
            candidate_paths.append(candidate)

    candidate_paths.extend(
        [
            run_dir / "decision.md",
            run_dir / "scientific-decision.md",
            run_dir / "decision-note.md",
            REPO_ROOT / "research" / "plans" / f"{run_dir.name}.md",
        ]
    )

    seen: set[str] = set()
    for path in candidate_paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        if path.exists():
            return {
                "exists": True,
                "path": _relative_or_absolute(path),
                "content": path.read_text(),
                "commit": commit,
                "run_id": run_dir.name,
            }

    fallback = candidate_paths[0] if candidate_paths else run_dir / "decision.md"
    return {
        "exists": False,
        "path": _relative_or_absolute(fallback),
        "content": "",
        "commit": commit,
        "run_id": run_dir.name,
    }


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return _page("Autoresearch Dashboard", INDEX_BODY, INDEX_SCRIPT)


@app.get("/history", response_class=HTMLResponse)
def history() -> str:
    return _page("Autoresearch History", HISTORY_BODY, HISTORY_SCRIPT)


@app.get("/api/experiments")
def list_experiments() -> list[dict]:
    return _load_records()


@app.get("/api/experiments/{exp_id}")
def get_experiment(exp_id: str):
    for record in _load_records():
        if str(record.get("id")) == exp_id:
            return record
    return JSONResponse(status_code=404, content={"error": "not found"})


@app.get("/api/experiments/{exp_id}/diff")
def get_diff(exp_id: str):
    for record in _load_records():
        if str(record.get("id")) != exp_id:
            continue
        commit = record.get("commit", "")
        parent = record.get("parent_commit", "")
        if not commit or not parent:
            return {"diff": ""}
        try:
            result = subprocess.run(
                ["git", "diff", parent, commit, "--", "train.py"],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=REPO_ROOT,
            )
        except Exception:
            return {"diff": ""}
        return {"diff": result.stdout or ""}
    return JSONResponse(status_code=404, content={"error": "not found"})


@app.get("/api/experiments/{exp_id}/decision-md")
def get_decision_markdown(exp_id: str):
    record = _load_record(exp_id)
    if record is None:
        return JSONResponse(status_code=404, content={"error": "not found"})
    return _decision_markdown_for_record(record)


@app.get("/api/karpathy-comparison")
def get_karpathy_comparison():
    csv_path = REPO_ROOT / "research" / "karpathy_comparison.csv"
    if not csv_path.exists():
        return []
    rows = []
    for line in csv_path.read_text().splitlines()[1:]:  # skip header
        parts = line.strip().split(",")
        if len(parts) < 4:
            continue
        rows.append({
            "experiment": parts[0],
            "karpathy_bpb": float(parts[1]),
            "our_bpb": float(parts[2]),
            "delta": parts[3],
        })
    return rows


@app.get("/api/karpathy-original")
def get_karpathy_original():
    tsv_path = REPO_ROOT / "research" / "karpathy_original_results.tsv"
    if not tsv_path.exists():
        return []
    rows = []
    best = float("inf")
    for line in tsv_path.read_text().splitlines()[1:]:  # skip header
        parts = line.strip().split("\t")
        if len(parts) < 5:
            continue
        try:
            bpb = float(parts[1])
        except ValueError:
            continue
        if bpb <= 0:
            continue
        status = parts[3]
        if status == "keep" and bpb < best:
            best = bpb
        rows.append({
            "commit": parts[0],
            "val_bpb": bpb,
            "memory_gb": float(parts[2]) if parts[2] else 0,
            "status": status,
            "description": parts[4] if len(parts) > 4 else "",
            "best_so_far": min(best, bpb) if best < float("inf") else bpb,
        })
    return rows
