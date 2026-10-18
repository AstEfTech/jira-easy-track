#!/usr/bin/env python3
# Jira Easy Track: single file, no dependencies. Run: python jira-track.py  (Python 3.8+)
# A local server serves the UI and proxies requests to Jira (Jira Cloud blocks direct browser calls via CORS).
import json
import os
import re
import secrets
import sys
import threading
import urllib.error
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

TOKEN = secrets.token_hex(16)
HOST_RE = re.compile(r'^(127\.0\.0\.1|localhost):\d+$')
CONFIG_PATH = os.environ.get('JIRA_TRACK_CONFIG') or os.path.join(os.path.dirname(os.path.abspath(__file__)), 'jira-track.config.json')
CONFIG_KEYS = ('conn', 'jql', 'fields', 'pinned', 'workday', 'track')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


opener = urllib.request.build_opener(NoRedirect)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, code, body, ctype='text/plain; charset=utf-8'):
        data = body.encode('utf-8') if isinstance(body, str) else body
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not HOST_RE.match(self.headers.get('Host', '')):
            return self.reply(403, 'forbidden')
        route = self.path.split('?')[0]
        if route == '/':
            return self.reply(200, HTML.replace('__TOKEN__', TOKEN), 'text/html; charset=utf-8')
        if route == '/api/config' and self.headers.get('X-Track-Token') == TOKEN:
            try:
                with open(CONFIG_PATH, encoding='utf-8') as f:
                    out = {'exists': True, 'config': json.load(f), 'path': CONFIG_PATH}
            except FileNotFoundError:
                out = {'exists': False, 'path': CONFIG_PATH}
            except ValueError:
                out = {'exists': False, 'path': CONFIG_PATH, 'error': 'Config file is not valid JSON'}
            return self.reply(200, json.dumps(out), 'application/json; charset=utf-8')
        self.reply(404, 'not found')

    def save_config(self):
        size = int(self.headers.get('Content-Length') or 0)
        if size > 1_000_000:
            return self.reply(413, 'too large')
        try:
            cfg = json.loads(self.rfile.read(size))
            cfg = {k: cfg[k] for k in CONFIG_KEYS if k in cfg}
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
            try:
                os.chmod(CONFIG_PATH, 0o600)
            except OSError:
                pass
        except Exception as e:
            return self.reply(500, 'Could not save config: %s' % e)
        self.reply(200, json.dumps({'ok': True, 'path': CONFIG_PATH}), 'application/json; charset=utf-8')

    def do_POST(self):
        if not HOST_RE.match(self.headers.get('Host', '')) or self.headers.get('X-Track-Token') != TOKEN:
            return self.reply(403, 'forbidden')
        if self.path == '/api/config':
            return self.save_config()
        if self.path != '/api/jira':
            return self.reply(404, 'not found')
        size = int(self.headers.get('Content-Length') or 0)
        if size > 1_000_000:
            return self.reply(413, 'too large')
        try:
            p = json.loads(self.rfile.read(size))
            u = urlparse(p['base'])
            if u.scheme != 'https' or not u.hostname or '@' in u.netloc:
                raise ValueError
        except Exception:
            return self.reply(400, 'Jira URL must start with https://')
        method, path = p.get('method'), p.get('path')
        if method not in ('GET', 'POST', 'PUT', 'DELETE') or not isinstance(path, str) \
                or not path.startswith('/rest/api/3/') or '..' in path or re.search(r'[\s\x00-\x1f]', path):
            return self.reply(400, 'bad request')

        body = p.get('body')
        req = urllib.request.Request(
            'https://' + u.netloc + path,
            data=json.dumps(body).encode('utf-8') if body is not None else None,
            method=method,
            headers={'Authorization': str(p.get('auth') or ''), 'Accept': 'application/json', 'Content-Type': 'application/json'},
        )
        try:
            with opener.open(req, timeout=60) as r:
                status, text = r.status, r.read().decode('utf-8', 'replace')
        except urllib.error.HTTPError as e:
            status, text = e.code, e.read().decode('utf-8', 'replace')
        except Exception as e:
            status, text = 0, json.dumps({'errorMessages': ['Could not connect to Jira: %s' % e]})
        try:
            data = json.loads(text) if text else None
        except ValueError:
            data = text
        self.reply(200, json.dumps({'status': status, 'data': data}), 'application/json; charset=utf-8')


def main():
    port = int(os.environ.get('PORT') or 4777)
    try:
        srv = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    except OSError:
        srv = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    url = 'http://127.0.0.1:%d' % srv.server_address[1]
    print('Jira Easy Track: %s  (Ctrl+C to exit)' % url)
    if '--no-open' not in sys.argv:
        threading.Timer(0.5, webbrowser.open, [url]).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


HTML = r'''
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Jira Easy Track</title>
<style>
:root { color-scheme: light dark; --bg:#f6f7f9; --card:#fff; --fg:#1d2330; --mut:#6b7385; --line:#dfe3ea; --acc:#2563eb; --bad:#dc2626; --ok:#16a34a; }
@media (prefers-color-scheme: dark) { :root { --bg:#14171d; --card:#1c2029; --fg:#e6e9f0; --mut:#98a1b3; --line:#2c3240; --acc:#5b8def; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg); font:14px/1.45 system-ui, Segoe UI, sans-serif; }
header { display:flex; gap:24px; align-items:center; padding:10px 24px; background:var(--card); border-bottom:1px solid var(--line); position:sticky; top:0; z-index:2; }
h1 { font-size:17px; margin:0; }
nav { display:flex; gap:4px; flex-wrap:wrap; }
nav button { background:none; border:0; padding:7px 14px; border-radius:6px; color:var(--mut); cursor:pointer; font:inherit; }
nav button.on { background:var(--acc); color:#fff; }
main { max-width:1200px; margin:20px auto; padding:0 24px; }
.tab { display:none; background:var(--card); border:1px solid var(--line); border-radius:10px; padding:20px; }
.tab.on { display:block; }
h2 { margin:0 0 14px; font-size:16px; }
h3 { margin:18px 0 6px; font-size:14px; }
h3 small { color:var(--mut); font-weight:400; margin-left:8px; }
label { display:block; margin-bottom:10px; color:var(--mut); font-size:12px; }
label input, label select { display:block; margin-top:3px; }
input, select { font:inherit; padding:6px 9px; border:1px solid var(--line); border-radius:6px; background:var(--bg); color:var(--fg); min-width:0; }
input.bad { border-color:var(--bad); }
.row { display:flex; gap:10px; align-items:flex-end; flex-wrap:wrap; margin-bottom:12px; }
.row label { margin:0; }
.grow { flex:1; min-width:240px; } .grow input { width:100%; }
.wide { width:100%; max-width:480px; }
button.btn { font:inherit; padding:7px 14px; border-radius:6px; border:1px solid var(--line); background:var(--card); color:var(--fg); cursor:pointer; }
button.pri { background:var(--acc); border-color:var(--acc); color:#fff; }
button.danger { background:var(--bad); border-color:var(--bad); color:#fff; }
button:disabled { opacity:.5; cursor:default; }
.hint { color:var(--mut); font-size:12px; margin:6px 0; }
.err { color:var(--bad); } .okc { color:var(--ok); }
table { border-collapse:collapse; width:100%; }
th, td { text-align:left; padding:5px 10px; border-bottom:1px solid var(--line); vertical-align:top; }
th { color:var(--mut); font-weight:500; font-size:12px; }
td input { width:86px; }
td.num, th.num { text-align:right; white-space:nowrap; }
#k-table td.num, #k-table th.num { text-align:left; }
.help { color:var(--mut); font-size:12px; margin:6px 0 14px; padding-left:18px; line-height:1.6; }
.help ul { margin:2px 0 4px; padding-left:18px; }
.help b { color:var(--fg); font-weight:600; }
.chip { display:inline-flex; gap:6px; align-items:center; background:var(--bg); border:1px solid var(--line); border-radius:99px; padding:2px 4px 2px 10px; margin-right:6px; }
.chip button { border:0; background:none; cursor:pointer; color:var(--mut); font-size:14px; }
.days { display:flex; gap:12px; flex-wrap:wrap; }
.days label { display:flex; gap:5px; align-items:center; margin:0; color:var(--fg); font-size:13px; }
.warn { color:#b45309; margin:6px 0; padding-left:18px; }
.stat { background:var(--bg); border-radius:8px; padding:10px 14px; margin:12px 0; }
.seg { border:1px solid var(--line); border-radius:8px; padding:12px 16px 4px; margin-bottom:14px; }
.seg > h3 { margin:0 0 10px; font-size:11px; text-transform:uppercase; letter-spacing:.06em; color:var(--mut); }
.done td { opacity:.55; }
a { color:var(--acc); text-decoration:none; }
progress { width:200px; vertical-align:middle; }
</style>
</head>
<body>
<header>
  <h1>Jira Easy Track</h1>
  <nav id="nav">
    <button data-tab="conn">1. Connection</button>
    <button data-tab="tasks">2. Tasks</button>
    <button data-tab="sched">3. Schedule</button>
    <button data-tab="prev">4. Preview</button>
    <button data-tab="clear">5. Clear</button>
  </nav>
</header>
<main>

<section class="tab" id="t-conn">
  <h2>Connect to Jira Cloud</h2>
  <label>Jira URL<input class="wide" id="c-base" placeholder="https://company.atlassian.net"></label>
  <label>Email<input class="wide" id="c-email" autocomplete="off"></label>
  <label>API token<input class="wide" id="c-token" type="password" autocomplete="off"></label>
  <p class="hint">Create a token at id.atlassian.com/manage-profile/security/api-tokens. It is stored only in this browser's localStorage and is sent only to Jira through the local server.</p>
  <button class="btn pri" id="c-test">Test and save</button> <span id="c-status"></span>
  <h3>Config file</h3>
  <p class="hint">Saves the connection (including the token, in plain text), JQL, displayed fields, pinned tasks and the working day settings to a JSON file next to the script. Once saved, changes are written automatically and loaded on every start.</p>
  <button class="btn" id="c-savecfg">Save to config file</button> <span data-cfg></span>
</section>

<section class="tab" id="t-tasks">
  <h2>Tasks and hours</h2>
  <div class="row">
    <label class="grow">JQL<input id="k-jql" data-b="jql"></label>
    <button class="btn pri" id="k-load">Load tasks</button>
  </div>
  <div class="row">
    <div>Fields: <span id="k-fields"></span></div>
    <label>Add field<input id="k-addfield" list="k-fieldlist" placeholder="name or id"></label>
    <datalist id="k-fieldlist"></datalist>
    <button class="btn" id="k-addbtn">+</button>
  </div>
  <div class="row">
    <label>Add task by key<input id="k-key" placeholder="PROJ-123"></label>
    <button class="btn" id="k-keybtn">Add</button>
    <label>Filter<input id="k-filter" placeholder="text"></label>
    <label style="display:flex;gap:6px;align-items:center;margin-bottom:6px"><input type="checkbox" id="k-only" style="margin:0"> only with hours</label>
  </div>
  <ul class="help">
    <li><b>Total</b>: hours spread across the working days of the period.</li>
    <li><b>Per day</b>: hours logged on every working day.</li>
    <li><b>Timing</b>: how Total is spread: evenly, towards the start, middle or end, or a random share per day.</li>
    <li><b>Range</b>: which days a task can be tracked on. It is preset when tasks are loaded, based on the task's status history; change it per task if needed.
      <ul>
        <li><b>Task window</b>: from the task's first move into status 1 to its first move into status 2 (set on the Schedule tab), within the period. Preset if the task has such a transition.</li>
        <li><b>Whole period</b>: every working day of the period. Preset if it does not.</li>
      </ul>
    </li>
    <li><b>Pin</b>: always keep the task in the list.</li>
    <li>Hours formats: 8, 1.5, 1:30, 1h 30m, 45m.</li>
  </ul>
  <div id="k-status"></div>
  <div style="overflow:auto"><table id="k-table"></table></div>
</section>

<section class="tab" id="t-sched">
  <h2>Schedule</h2>
  <div class="seg">
    <h3>Period</h3>
    <div class="row">
      <label>From<input type="date" data-b="sched.from"></label>
      <label>To<input type="date" data-b="sched.to"></label>
      <label class="grow">Days off / holidays (YYYY-MM-DD, comma-separated)<input data-b="sched.exclude" placeholder="2026-11-04, 2026-11-05"></label>
    </div>
  </div>
  <div class="seg">
    <h3>Working day</h3>
    <div class="row">
      <label>Day start<input type="time" data-b="sched.dayStart"></label>
      <label>Day end<input type="time" data-b="sched.dayEnd"></label>
      <label>Break from<input type="time" data-b="sched.breakStart"></label>
      <label>Break to<input type="time" data-b="sched.breakEnd"></label>
      <label>Step, min<select data-b="sched.step"><option>5</option><option>10</option><option>15</option><option>30</option><option>60</option></select></label>
    </div>
    <div class="days" id="s-days"></div>
    <div class="row" style="margin-top:12px">
      <button class="btn" id="s-savecfg">Save to config file</button> <span data-cfg></span>
    </div>
  </div>
  <div class="seg">
    <h3>Task tracking window</h3>
    <div class="row">
      <label>Status 1 (start)<select id="t-from" data-b="track.from"></select></label>
      <label>Status 2 (end)<select id="t-to" data-b="track.to"></select></label>
      <button class="btn" id="t-load">Load statuses</button> <span id="t-st"></span>
    </div>
    <p class="hint">A task in Task window mode is tracked only on working days from its first move into status 1 to its first move into status 2 (inclusive), within the selected period. Tasks that never entered status 1 use the whole period. Changing a status re-reads the history of the loaded tasks.</p>
  </div>
  <div class="seg">
    <h3>Distribution</h3>
    <label style="display:flex;gap:6px;align-items:center;color:var(--fg);font-size:13px"><input type="checkbox" id="s-varied" style="margin:0"> Realistic spread (different hours on different days; recalculate for a new variation)</label>
  </div>
  <div class="stat" id="s-stat"></div>
  <button class="btn pri" id="s-calc">Calculate distribution</button> <span id="s-calcst"></span>
</section>

<section class="tab" id="t-prev">
  <h2>Distribution preview</h2>
  <div id="p-box"></div>
</section>

<section class="tab" id="t-clear">
  <h2>Clear time tracking</h2>
  <p class="hint">Only your own worklogs within the selected period (inclusive) are deleted.</p>
  <div class="row">
    <label>From<input type="date" data-b="clear.from"></label>
    <label>To<input type="date" data-b="clear.to"></label>
    <button class="btn pri" id="x-find">Find my worklogs</button>
  </div>
  <div id="x-box"></div>
</section>

</main>
<script>
const TRACK_TOKEN = '__TOKEN__';
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const pad = (n) => String(n).padStart(2, '0');
const ymd = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const pYmd = (s) => { const [y, m, d] = s.split('-').map(Number); return new Date(y, m - 1, d); };
const addDays = (s, n) => { const d = pYmd(s); d.setDate(d.getDate() + n); return ymd(d); };
const hm = (s) => { const m = /^(\d{1,2}):(\d{2})$/.exec(s || ''); return m ? +m[1] * 60 + +m[2] : null; };
const fmtT = (m) => `${pad(Math.floor(m / 60))}:${pad(m % 60)}`;
const fmtD = (m) => { const h = Math.floor(m / 60), r = m % 60; return (h ? h + 'h' : '') + (h && r ? ' ' : '') + (r || !h ? r + 'm' : ''); };
const WD = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const SHIFTS = [['', 'Even'], ['start', 'Start'], ['mid', 'Middle'], ['end', 'End'], ['random', 'Random']];
const RANGES = [['window', 'Task window'], ['period', 'Whole period']];

function parseH(s) {
  s = String(s || '').trim().toLowerCase().replace(',', '.');
  if (!s) return 0;
  let m = /^(\d+):(\d{1,2})$/.exec(s);
  if (m) return +m[1] * 60 + +m[2];
  if (/^\d+(\.\d+)?$/.test(s)) return Math.round(parseFloat(s) * 60);
  m = /^(?:(\d+(?:\.\d+)?)\s*h)?\s*(?:(\d+)\s*(?:m|min))?$/.exec(s);
  if (m && (m[1] || m[2])) return Math.round((parseFloat(m[1]) || 0) * 60 + (+m[2] || 0));
  return NaN;
}

// ---------- state ----------
const LS = 'jiraTrackNoBS.v1';
const today = ymd(new Date());
const monthStart = today.slice(0, 8) + '01';
const DEF = {
  conn: { base: '', email: '', token: '' },
  jql: 'assignee = currentUser() ORDER BY updated DESC',
  fields: [{ id: 'summary', name: 'Summary' }],
  pinned: [],
  track: { from: 'In Progress', to: 'Done' },
  windows: {},
  plan: {},
  issues: [],
  sched: { from: monthStart, to: today, dayStart: '10:00', dayEnd: '19:00', breakStart: '13:00', breakEnd: '14:00', step: '15', days: [1, 2, 3, 4, 5], exclude: '', varied: false },
  clear: { from: monthStart, to: today },
};
let S;
try {
  const saved = JSON.parse(localStorage.getItem(LS) || '{}');
  S = { ...structuredClone(DEF), ...saved };
  S.sched = { ...DEF.sched, ...saved.sched };
  S.clear = { ...DEF.clear, ...saved.clear };
  S.conn = { ...DEF.conn, ...saved.conn };
  S.track = { from: saved.track?.from || DEF.track.from, to: saved.track?.to || DEF.track.to };
} catch { S = structuredClone(DEF); }
const CFG_KEYS = ['conn', 'jql', 'fields', 'pinned', 'track'];
const WORKDAY_KEYS = ['dayStart', 'dayEnd', 'breakStart', 'breakEnd', 'step', 'days', 'varied'];
let cfgOn = false;
let cfgTimer = null;
const save = () => {
  localStorage.setItem(LS, JSON.stringify(S));
  if (cfgOn) { clearTimeout(cfgTimer); cfgTimer = setTimeout(saveConfig, 500); }
};
const cfgStatus = (text, cls) => document.querySelectorAll('[data-cfg]').forEach((el) => setStatus(el, text, cls));

async function saveConfig() {
  try {
    const body = Object.fromEntries(CFG_KEYS.map((k) => [k, S[k]]));
    body.workday = Object.fromEntries(WORKDAY_KEYS.map((k) => [k, S.sched[k]]));
    const r = await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Track-Token': TRACK_TOKEN },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error(await r.text());
    cfgStatus('Saved to ' + (await r.json()).path, 'okc');
  } catch (e) { cfgStatus(e.message, 'err'); }
}

async function loadConfig() {
  try {
    const j = await (await fetch('/api/config', { headers: { 'X-Track-Token': TRACK_TOKEN } })).json();
    if (j.error) cfgStatus(j.error, 'err');
    if (!j.exists) return;
    const c = j.config || {};
    if (c.conn && typeof c.conn === 'object') S.conn = { ...DEF.conn, ...c.conn };
    if (typeof c.jql === 'string' && c.jql) S.jql = c.jql;
    if (Array.isArray(c.fields) && c.fields.every((f) => f && f.id)) S.fields = c.fields.map((f) => ({ id: String(f.id), name: String(f.name || f.id) }));
    if (Array.isArray(c.pinned)) S.pinned = c.pinned.map(String);
    const w = c.workday;
    if (w && typeof w === 'object') {
      ['dayStart', 'dayEnd', 'breakStart', 'breakEnd'].forEach((k) => { if (typeof w[k] === 'string') S.sched[k] = w[k]; });
      if (['5', '10', '15', '30', '60'].includes(String(w.step))) S.sched.step = String(w.step);
      if (Array.isArray(w.days)) S.sched.days = w.days.map(Number).filter((d) => d >= 0 && d <= 6);
      if (typeof w.varied === 'boolean') S.sched.varied = w.varied;
    }
    const tr = c.track;
    if (tr && typeof tr === 'object') {
      if (typeof tr.from === 'string' && tr.from) S.track.from = tr.from;
      if (typeof tr.to === 'string' && tr.to) S.track.to = tr.to;
    }
    cfgOn = true;
    cfgStatus('Loaded from ' + j.path, 'okc');
  } catch {
    // no config available, keep browser-stored state
  }
}

let stopReq = false;

let P = null;      // preview: { entries, warnings }
let found = null;  // worklogs found for clearing
let busy = false;
let catalog = null;

// ---------- Jira API ----------
class JErr extends Error { constructor(m, status) { super(m); this.status = status; } }
const b64 = (s) => btoa(String.fromCharCode(...new TextEncoder().encode(s)));
const baseUrl = () => S.conn.base;

async function jira(method, path, body) {
  const c = S.conn;
  if (!c.base || !c.email || !c.token) throw new JErr('Fill in the Connection tab first', 0);
  const r = await fetch('/api/jira', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Track-Token': TRACK_TOKEN },
    body: JSON.stringify({ base: c.base, auth: 'Basic ' + b64(c.email + ':' + c.token), method, path, body }),
  });
  if (!r.ok) throw new JErr((await r.text()) || 'Local server error (restart the script and reload the page)', r.status);
  const j = await r.json();
  if (j.status >= 200 && j.status < 300) return j.data;
  const d = j.data || {};
  const msg = [].concat(d.errorMessages || [], Object.values(d.errors || {})).join('; ') || (typeof d === 'string' ? d.slice(0, 200) : '') || 'HTTP ' + j.status;
  throw new JErr(msg, j.status);
}

async function searchIssues(jql, fields) {
  const out = [];
  let token;
  do {
    const r = await jira('POST', '/rest/api/3/search/jql', { jql, fields, maxResults: 100, nextPageToken: token });
    out.push(...r.issues);
    token = r.nextPageToken;
  } while (token && out.length < 2000);
  return out;
}

async function loadIssues(onProgress) {
  const ids = S.fields.map((f) => f.id);
  let list = await searchIssues(S.jql, ids);
  const have = new Set(list.map((i) => i.key));
  const want = [...new Set([...S.pinned, ...Object.keys(S.plan)])];
  const extra = want.filter((k) => !have.has(k));
  if (extra.length) {
    try { list = (await searchIssues(`key in (${extra.map((k) => '"' + k + '"').join(',')})`, ids)).concat(list); } catch {
      // the issue may have been deleted
    }
  }
  S.issues = list;
  await loadWindows(list.map((i) => i.key), onProgress);
  save();
}

function adf(n) {
  if (!n) return '';
  if (n.text) return n.text;
  return (n.content || []).map(adf).join(n.type === 'doc' ? ' ' : '');
}
function val(v) {
  if (v == null) return '';
  if (Array.isArray(v)) return v.map(val).filter(Boolean).join(', ');
  if (typeof v === 'object') return v.type === 'doc' ? adf(v) : v.displayName || v.name || v.value || v.key || v.title || '';
  return String(v);
}

const sumOf = (key) => val(S.issues.find((i) => i.key === key)?.fields?.summary);
const link = (key) => `<a href="${esc(baseUrl())}/browse/${esc(key)}" target="_blank" rel="noopener">${esc(key)}</a>`;
const setStatus = (el, text, cls) => { el.className = cls || ''; el.textContent = text; };

// ---------- tabs ----------
function show(tab) {
  document.querySelectorAll('.tab').forEach((t) => t.classList.toggle('on', t.id === 't-' + tab));
  document.querySelectorAll('#nav button').forEach((b) => b.classList.toggle('on', b.dataset.tab === tab));
  syncInputs();
  if (tab === 'tasks') renderTasks();
  if (tab === 'sched') renderSched();
  if (tab === 'prev') renderPreview();
  if (tab === 'clear') renderClear();
}
$('#nav').onclick = (e) => { const b = e.target.closest('button'); if (b) show(b.dataset.tab); };

function getPath(path) { const [a, b] = path.split('.'); return b ? S[a][b] : S[a]; }
function setPath(path, v) { const [a, b] = path.split('.'); if (b) S[a][b] = v; else S[a] = v; }
function syncInputs() { document.querySelectorAll('[data-b]').forEach((el) => { el.value = getPath(el.dataset.b); }); }
document.addEventListener('input', (e) => {
  const el = e.target;
  if (!el.dataset || !el.dataset.b) return;
  setPath(el.dataset.b, el.value);
  save();
  if (el.dataset.b.startsWith('sched')) renderStats();
  if (el.dataset.b.startsWith('track.') && S.conn.token && S.issues.length) refreshWindows();
});

// ---------- 1. connection ----------
function fillConn() {
  $('#c-base').value = S.conn.base;
  $('#c-email').value = S.conn.email;
  $('#c-token').value = S.conn.token;
}
function readConn() {
  let base = $('#c-base').value.trim().replace(/\/+$/, '');
  if (base && !/^https?:\/\//i.test(base)) base = 'https://' + base;
  S.conn = { base, email: $('#c-email').value.trim(), token: $('#c-token').value.trim() };
  $('#c-base').value = base;
}
$('#c-test').onclick = async () => {
  readConn();
  save();
  const st = $('#c-status');
  setStatus(st, 'Checking...');
  try {
    const me = await jira('GET', '/rest/api/3/myself');
    setStatus(st, 'Connected: ' + me.displayName, 'okc');
  } catch (e) { setStatus(st, e.message, 'err'); }
};
$('#c-savecfg').onclick = () => {
  readConn();
  cfgOn = true;
  save();
};

// ---------- 2. tasks ----------
function renderFields() {
  $('#k-fields').innerHTML = '<span class="chip">Key</span>' + S.fields.map((f, i) =>
    `<span class="chip">${esc(f.name)} <button data-rmf="${i}" title="remove">×</button></span>`).join('');
}

function renderTasks() {
  renderFields();
  const filter = $('#k-filter').value.trim().toLowerCase();
  const only = $('#k-only').checked;
  const head = '<tr><th>Key</th>' + S.fields.map((f) => `<th>${esc(f.name)}</th>`).join('') + '<th class="num">Total</th><th class="num">Per day</th><th>Timing</th><th>Range</th><th>Pin</th></tr>';
  const rows = S.issues.map((i) => {
    const p = S.plan[i.key] || {};
    const cells = S.fields.map((f) => { const v = val(i.fields?.[f.id]); return `<td>${esc(v.length > 200 ? v.slice(0, 200) + '…' : v)}</td>`; }).join('');
    const hay = (i.key + ' ' + S.fields.map((f) => val(i.fields?.[f.id])).join(' ')).toLowerCase();
    if (filter && !hay.includes(filter)) return '';
    if (only && !(p.total || p.fixed)) return '';
    return `<tr><td>${link(i.key)}</td>${cells}` +
      `<td class="num"><input data-k="${esc(i.key)}" data-f="total" value="${esc(p.total || '')}" placeholder="0"></td>` +
      `<td class="num"><input data-k="${esc(i.key)}" data-f="fixed" value="${esc(p.fixed || '')}" placeholder="0"></td>` +
      `<td><select data-k="${esc(i.key)}" data-f="shift">${SHIFTS.map(([v, l]) => `<option value="${v}"${(p.shift || '') === v ? ' selected' : ''}>${l}</option>`).join('')}</select></td>` +
      `<td><select data-k="${esc(i.key)}" data-f="range">${RANGES.map(([v, l]) => `<option value="${v}"${effRange(i.key) === v ? ' selected' : ''}>${l}</option>`).join('')}</select></td>` +
      `<td><input type="checkbox" style="width:auto" data-pin="${esc(i.key)}"${S.pinned.includes(i.key) ? ' checked' : ''}></td></tr>`;
  }).join('');
  $('#k-table').innerHTML = head + rows;
  $('#k-status').innerHTML = S.issues.length ? `<p class="hint">Tasks: ${S.issues.length}. ${planSummary()}</p>` : '<p class="hint">Click "Load tasks".</p>';
}

function planSummary() {
  const t = Object.values(S.plan).reduce((a, p) => a + (parseH(p.total) || 0), 0);
  const f = Object.values(S.plan).reduce((a, p) => a + (parseH(p.fixed) || 0), 0);
  return `To distribute: ${fmtD(t)}; fixed per day: ${fmtD(f)}.`;
}

$('#k-table').addEventListener('input', (e) => {
  const el = e.target;
  if (!el.dataset.k) return;
  const p = (S.plan[el.dataset.k] ??= { total: '', fixed: '', shift: '', range: '' });
  p[el.dataset.f] = el.value.trim();
  if (el.tagName === 'INPUT') el.classList.toggle('bad', Number.isNaN(parseH(el.value)));
  if (!p.total && !p.fixed && !p.shift && !p.range) delete S.plan[el.dataset.k];
  save();
  const hint = $('#k-status .hint');
  if (hint) hint.textContent = `Tasks: ${S.issues.length}. ${planSummary()}`;
});
$('#k-table').addEventListener('change', (e) => {
  const key = e.target.dataset.pin;
  if (!key) return;
  S.pinned = S.pinned.filter((k) => k !== key);
  if (e.target.checked) S.pinned.push(key);
  save();
});
$('#k-filter').oninput = renderTasks;
$('#k-only').onchange = renderTasks;

async function reload() {
  const st = $('#k-status');
  setStatus(st, 'Loading...');
  try { await loadIssues((d, n) => setStatus(st, `Reading task history ${d}/${n}...`)); renderTasks(); } catch (e) { setStatus(st, e.message, 'err'); }
}
$('#k-load').onclick = reload;

$('#k-fields').onclick = (e) => {
  const b = e.target.closest('[data-rmf]');
  if (!b) return;
  S.fields.splice(+b.dataset.rmf, 1);
  save();
  renderTasks();
};

$('#k-addfield').onfocus = async () => {
  if (catalog) return;
  try {
    catalog = await jira('GET', '/rest/api/3/field');
    $('#k-fieldlist').innerHTML = catalog.map((f) => `<option value="${esc(f.name)}">${esc(f.id)}</option>`).join('');
  } catch {
    // the error is shown when adding
  }
};
$('#k-addbtn').onclick = async () => {
  const q = $('#k-addfield').value.trim().toLowerCase();
  if (!q) return;
  if (!catalog) await $('#k-addfield').onfocus();
  const f = (catalog || []).find((x) => x.name.toLowerCase() === q || x.id.toLowerCase() === q);
  if (!f) return setStatus($('#k-status'), 'Field not found', 'err');
  if (!S.fields.some((x) => x.id === f.id)) S.fields.push({ id: f.id, name: f.name });
  $('#k-addfield').value = '';
  save();
  reload();
};

$('#k-keybtn').onclick = async () => {
  const key = $('#k-key').value.trim().toUpperCase();
  if (!/^[A-Z][A-Z0-9_]*-\d+$/.test(key)) return setStatus($('#k-status'), 'Invalid issue key', 'err');
  const had = S.pinned.includes(key);
  if (!had) S.pinned.push(key);
  try { await loadIssues(); $('#k-key').value = ''; renderTasks(); } catch (e) {
    if (!had) S.pinned = S.pinned.filter((k) => k !== key);
    setStatus($('#k-status'), e.message, 'err');
  }
};

// ---------- 3. schedule ----------
function renderSched() {
  if (!statusList.length && !statusTried && S.conn.token) { statusTried = true; loadStatuses(true); }
  $('#s-varied').checked = !!S.sched.varied;
  $('#s-days').innerHTML = [1, 2, 3, 4, 5, 6, 0].map((d) =>
    `<label><input type="checkbox" data-day="${d}" ${S.sched.days.includes(d) ? 'checked' : ''}>${WD[d]}</label>`).join('');
  renderStats();
}
$('#s-varied').onchange = (e) => { S.sched.varied = e.target.checked; save(); };
$('#s-savecfg').onclick = () => { cfgOn = true; save(); };

let statusList = [];
let statusTried = false;
const parseJiraDate = (s) => new Date(s.replace(/([+-]\d\d)(\d\d)$/, '$1:$2'));
const winValid = (key) => S.windows[key]?.sf === S.track.from && S.windows[key]?.st === S.track.to;
const defaultRange = (key) => (winValid(key) && S.windows[key].start ? 'window' : 'period');
const effRange = (key) => S.plan[key]?.range || defaultRange(key);

function renderStatusOptions() {
  const opts = [...new Set([...statusList, S.track.from, S.track.to])].map((n) => `<option>${esc(n)}</option>`).join('');
  $('#t-from').innerHTML = opts;
  $('#t-to').innerHTML = opts;
  $('#t-from').value = S.track.from;
  $('#t-to').value = S.track.to;
}

async function loadStatuses(silent) {
  const st = $('#t-st');
  if (!silent) setStatus(st, 'Loading...');
  try {
    const all = await jira('GET', '/rest/api/3/status');
    const order = { new: 0, indeterminate: 1, done: 2 };
    all.sort((a, b) => (order[a.statusCategory?.key] ?? 3) - (order[b.statusCategory?.key] ?? 3) || a.name.localeCompare(b.name));
    statusList = all.map((s) => s.name);
    renderStatusOptions();
    setStatus(st, `${statusList.length} statuses loaded`, 'okc');
  } catch (e) { if (!silent) setStatus(st, e.message, 'err'); }
}
$('#t-load').onclick = () => loadStatuses(false);

async function fetchWindow(key, from, to) {
  const hist = [];
  for (let at = 0; ;) {
    const r = await jira('GET', `/rest/api/3/issue/${encodeURIComponent(key)}/changelog?startAt=${at}&maxResults=100`);
    hist.push(...r.values);
    at += r.values.length;
    if (r.isLast || !r.values.length || at >= r.total) break;
  }
  const tr = hist
    .flatMap((h) => h.items.filter((i) => i.field === 'status').map((i) => ({ t: parseJiraDate(h.created), to: (i.toString || '').toLowerCase() })))
    .sort((a, b) => a.t - b.t);
  const s = tr.find((x) => x.to === from.toLowerCase());
  const e = tr.find((x) => x.to === to.toLowerCase() && (!s || x.t >= s.t));
  return { start: s ? ymd(s.t) : null, end: e ? ymd(e.t) : null };
}

// Windows that are complete (start and end known) are cached; the rest are re-read.
async function loadWindows(keys, onProgress, strict) {
  const sf = S.track.from, st = S.track.to;
  const todo = keys.filter((k) => !(winValid(k) && S.windows[k].start && S.windows[k].end));
  const total = todo.length;
  let done = 0, err = null;
  const worker = async () => {
    while (todo.length) {
      const k = todo.shift();
      try { S.windows[k] = { ...(await fetchWindow(k, sf, st)), sf, st }; } catch (e) { err ||= e; }
      if (onProgress) onProgress(++done, total);
    }
  };
  await Promise.all(Array.from({ length: Math.min(5, total) }, worker));
  save();
  if (err && strict) throw err;
}

async function refreshWindows() {
  const st = $('#t-st');
  await loadWindows(S.issues.map((i) => i.key), (d, n) => setStatus(st, `Updating task history ${d}/${n}...`));
  setStatus(st, 'Task history updated', 'okc');
}

async function ensureWindows() {
  const keys = Object.entries(S.plan)
    .filter(([, p]) => (parseH(p.total) > 0 || parseH(p.fixed) > 0) && p.range !== 'period')
    .map(([k]) => k);
  await loadWindows(keys, (d, n) => setStatus($('#s-calcst'), `Reading task history ${d}/${n}...`), true);
  setStatus($('#s-calcst'), '');
}
$('#s-days').onchange = (e) => {
  const d = +e.target.dataset.day;
  S.sched.days = S.sched.days.filter((x) => x !== d);
  if (e.target.checked) S.sched.days.push(d);
  save();
  renderStats();
};

function workDays() {
  const { from, to, days, exclude } = S.sched;
  const ex = new Set(exclude.split(/[\s,;]+/).filter(Boolean));
  const out = [];
  if (!from || !to) return out;
  for (let d = pYmd(from), n = 0; ymd(d) <= to && n < 400; d.setDate(d.getDate() + 1), n++) {
    if (days.includes(d.getDay()) && !ex.has(ymd(d))) out.push(ymd(d));
  }
  return out;
}

function dayGeometry() {
  const sc = S.sched;
  const ds = hm(sc.dayStart), de = hm(sc.dayEnd);
  if (ds == null || de == null || de <= ds) return null;
  let bs = hm(sc.breakStart), be = hm(sc.breakEnd);
  const hasBreak = bs != null && be != null && be > bs && bs >= ds && be <= de;
  if (!hasBreak) { bs = be = null; }
  return { ds, de, bs, be, hasBreak, len: de - ds - (hasBreak ? be - bs : 0) };
}

// t in [0..1] is the position within the period; returns the relative share of hours for that day
function shiftWeight(mode, t) {
  if (mode === 'start') return 1.9 - 1.8 * t;
  if (mode === 'end') return 0.1 + 1.8 * t;
  if (mode === 'mid') return 0.2 + Math.exp(-((t - 0.5) ** 2) / (2 * 0.18 ** 2));
  if (mode === 'random') return 0.15 + Math.random() * 1.85;
  return 1;
}

function layout() {
  const g = dayGeometry();
  if (!g) return { error: 'Invalid working day start/end time' };
  if (!S.sched.from || !S.sched.to || S.sched.from > S.sched.to) return { error: 'Invalid period' };
  const days = workDays();
  if (!days.length) return { error: 'No working days in the period' };
  const step = Number(S.sched.step) || 15;
  const units = (m) => Math.max(1, Math.round(m / step));
  const warnings = [];
  const tasks = Object.entries(S.plan)
    .map(([key, p]) => ({ key, total: parseH(p.total) || 0, fixed: parseH(p.fixed) || 0, shift: p.shift || '', range: p.range || defaultRange(key) }))
    .filter((t) => t.total > 0 || t.fixed > 0);
  const ranges = {};
  tasks.forEach((t) => {
    let lo = '', hi = '';
    if (t.range === 'window') {
      const w = S.windows[t.key];
      if (winValid(t.key) && w.start) { lo = w.start; hi = w.end || ''; }
      else warnings.push(`${t.key}: no transition to "${S.track.from}" found, using the whole period`);
    }
    t.ok = days.map((date) => (!lo || date >= lo) && (!hi || date <= hi));
    ranges[t.key] = lo ? `${lo} – ${hi || 'now'}` : 'whole period';
    if (!t.ok.some(Boolean)) warnings.push(`${t.key}: no working days inside the task window (${ranges[t.key]}), its hours were skipped`);
  });
  const cap = days.map(() => Math.floor(g.len / step));
  const alloc = days.map(() => []);

  tasks.filter((t) => t.fixed > 0).forEach((t) => {
    const u = units(t.fixed);
    let cut = false;
    days.forEach((_, d) => {
      if (!t.ok[d]) return;
      const x = Math.min(u, cap[d]);
      if (x < u) cut = true;
      if (x > 0) { alloc[d].push({ key: t.key, u: x }); cap[d] -= x; }
    });
    if (cut) warnings.push(`${t.key}: fixed hours do not fit in the working day, some days were truncated`);
  });

  const varTasks = tasks.filter((t) => t.total > 0);
  const dayF = days.map(() => (S.sched.varied ? 0.5 + Math.random() : 1));
  varTasks.forEach((t, ti) => {
    const idx = days.map((_, d) => d).filter((d) => t.ok[d]);
    const M = idx.length;
    if (!M) return;
    const U = units(t.total);
    const per = days.map(() => 0);
    const rot = Math.floor((ti * M) / varTasks.length);
    const w = idx.map((d, k) => shiftWeight(t.shift, M > 1 ? k / (M - 1) : 0.5) * dayF[d] * (S.sched.varied ? 0.75 + Math.random() * 0.5 : 1));
    const wSum = w.reduce((a, x) => a + x, 0);
    const deficit = (k) => (U * w[k]) / wSum - per[idx[k]];
    for (let n = 0; n < U; n++) {
      let best = -1;
      for (let k = 0; k < M; k++) {
        const d = idx[k];
        if (cap[d] <= 0) continue;
        if (best < 0 || deficit(k) > deficit(best) || (deficit(k) === deficit(best) && (cap[d] > cap[idx[best]] || (cap[d] === cap[idx[best]] && (k - rot + M) % M < (best - rot + M) % M)))) best = k;
      }
      if (best < 0) { warnings.push(`${t.key}: ${fmtD((U - n) * step)} did not fit (no free time left in the period)`); break; }
      per[idx[best]]++; cap[idx[best]]--;
    }
    per.forEach((u, d) => { if (u > 0) alloc[d].push({ key: t.key, u }); });
  });

  let id = 1;
  const entries = [];
  days.forEach((date, d) => {
    let t = g.ds;
    alloc[d].forEach((a) => {
      let rest = a.u * step;
      while (rest > 0) {
        if (g.hasBreak && t >= g.bs && t < g.be) t = g.be;
        const limit = g.hasBreak && t < g.bs ? g.bs : g.de;
        const len = Math.min(rest, limit - t);
        if (len <= 0) break;
        entries.push({ id: id++, date, key: a.key, start: t, min: len });
        t += len; rest -= len;
      }
    });
  });
  return { entries, warnings, days, g, tasks, ranges };
}

function renderStats() {
  const el = $('#s-stat');
  const g = dayGeometry();
  const days = workDays();
  if (!g || !days.length) { el.textContent = 'Check the period and working day times'; return; }
  const tasks = Object.values(S.plan);
  const total = tasks.reduce((a, p) => a + (parseH(p.total) || 0) + (parseH(p.fixed) || 0) * days.length, 0);
  const capTotal = days.length * g.len;
  el.innerHTML = `Working days: <b>${days.length}</b> · per day: <b>${fmtD(g.len)}</b> · available: <b>${fmtD(capTotal)}</b> · planned: <b class="${total > capTotal ? 'err' : ''}">${fmtD(total)}</b>`;
}

$('#s-calc').onclick = async () => {
  if (P && P.entries.some((e) => e.done) && !confirm('Some entries were already sent. Recalculating and sending again will create duplicates. Continue?')) return;
  const btn = $('#s-calc');
  if (btn.disabled) return;
  btn.disabled = true;
  try { await ensureWindows(); } catch (e) { btn.disabled = false; return alert(e.message); }
  btn.disabled = false;
  const r = layout();
  if (r.error) return alert(r.error);
  if (!r.entries.length) return alert('No tasks with hours. Fill in hours on the Tasks tab.');
  P = { entries: r.entries, warnings: r.warnings, ranges: r.ranges };
  show('prev');
};

// ---------- 4. preview and submit ----------
function jiraStarted(date, min) {
  const [y, m, d] = date.split('-').map(Number);
  const dt = new Date(y, m - 1, d, Math.floor(min / 60), min % 60);
  const off = -dt.getTimezoneOffset();
  const a = Math.abs(off);
  return `${ymd(dt)}T${pad(dt.getHours())}:${pad(dt.getMinutes())}:00.000${off >= 0 ? '+' : '-'}${pad(Math.floor(a / 60))}${pad(a % 60)}`;
}

function renderPreview() {
  const box = $('#p-box');
  if (!P) { box.innerHTML = '<p class="hint">Calculate the distribution on the Schedule tab first.</p>'; return; }
  const byDay = {};
  P.entries.forEach((e) => (byDay[e.date] ??= []).push(e));
  const total = P.entries.reduce((a, e) => a + e.min, 0);
  const sent = P.entries.filter((e) => e.done).length;
  const per = {};
  P.entries.forEach((e) => { per[e.key] = (per[e.key] || 0) + e.min; });
  const sumRows = Object.entries(per).map(([k, m]) => `<tr><td>${link(k)}</td><td>${esc(sumOf(k))}</td><td>${esc((P.ranges || {})[k] || '')}</td><td class="num">${fmtD(m)}</td></tr>`).join('');
  const days = Object.keys(byDay).sort().map((d) => {
    const es = byDay[d].sort((a, b) => a.start - b.start);
    const rows = es.map((e) => `<tr class="${e.done ? 'done' : ''}"><td>${fmtT(e.start)}–${fmtT(e.start + e.min)}</td><td>${link(e.key)}</td><td>${esc(sumOf(e.key))}</td>` +
      `<td class="num">${fmtD(e.min)}</td><td>${e.done ? '<span class="okc">sent</span>' : e.err ? `<span class="err" title="${esc(e.err)}">error: ${esc(e.err)}</span>` : `<button class="btn" data-rm="${e.id}" title="remove entry">×</button>`}</td></tr>`).join('');
    return `<h3>${d} ${WD[pYmd(d).getDay()]}<small>${fmtD(es.reduce((a, e) => a + e.min, 0))}</small></h3><table>${rows}</table>`;
  }).join('');
  box.innerHTML =
    (P.warnings.length ? `<ul class="warn">${P.warnings.map((w) => `<li>${esc(w)}</li>`).join('')}</ul>` : '') +
    `<div class="stat">Entries: <b>${P.entries.length}</b> · total: <b>${fmtD(total)}</b> · sent: <b>${sent}</b></div>` +
    `<div class="row"><button class="btn pri" id="p-send" ${busy ? 'disabled' : ''}>Approve and send to Jira</button>` +
    (busy ? '<button class="btn danger" id="p-stop">Stop</button>' : '') +
    `<button class="btn" id="p-recalc" ${busy ? 'disabled' : ''}>Recalculate</button><span id="p-status"></span></div>` +
    `<h3>By task</h3><table>${sumRows}</table>` + days;
}

$('#p-box').addEventListener('click', (e) => {
  const rm = e.target.closest('[data-rm]');
  if (rm) { P.entries = P.entries.filter((x) => x.id !== +rm.dataset.rm); renderPreview(); return; }
  if (e.target.id === 'p-send') send();
  if (e.target.id === 'p-stop') { stopReq = true; setStatus($('#p-status'), 'Stopping after the current request...'); }
  if (e.target.id === 'p-recalc') $('#s-calc').onclick();
});

async function send() {
  if (busy) return;
  const todo = P.entries.filter((e) => !e.done);
  if (!todo.length) return alert('All entries have already been sent.');
  const sum = todo.reduce((a, e) => a + e.min, 0);
  if (!confirm(`Send ${todo.length} worklogs (${fmtD(sum)}) to Jira?`)) return;
  busy = true;
  stopReq = false;
  renderPreview();
  let ok = 0, fail = 0, i = 0;
  for (const e of todo) {
    if (stopReq) break;
    i++;
    const st = $('#p-status');
    if (st) st.textContent = `Sending ${i}/${todo.length}...`;
    try {
      await jira('POST', `/rest/api/3/issue/${encodeURIComponent(e.key)}/worklog?adjustEstimate=leave`, { started: jiraStarted(e.date, e.start), timeSpentSeconds: e.min * 60 });
      e.done = true; e.err = ''; ok++;
    } catch (x) {
      e.err = x.message; fail++;
      if (x.status === 401 || x.status === 0) break;
    }
  }
  busy = false;
  renderPreview();
  setStatus($('#p-status'), `${stopReq ? 'Stopped. ' : ''}Sent: ${ok}, failed: ${fail}${ok + fail < todo.length || fail ? ' — click "Approve" again to send the remaining/failed ones' : ''}`, fail ? 'err' : 'okc');
}

// ---------- 5. clear ----------
function renderClear() {
  const box = $('#x-box');
  if (!found) { box.innerHTML = ''; return; }
  const total = found.items.reduce((a, w) => a + w.min, 0);
  const rows = found.items.map((w) => `<tr><td>${w.date}</td><td>${link(w.key)}</td><td>${esc(w.summary)}</td><td class="num">${fmtD(w.min)}</td></tr>`).join('');
  box.innerHTML = `<div class="stat">Found: <b>${found.items.length}</b> · total: <b>${fmtD(total)}</b></div>` +
    (found.items.length ? `<div class="row"><button class="btn danger" id="x-del" ${busy ? 'disabled' : ''}>Delete all found</button>${busy ? '<button class="btn" id="x-stop">Stop</button>' : ''}<span id="x-status"></span></div>` : '') +
    `<table>${rows}</table>`;
}

$('#x-find').onclick = async () => {
  if (busy) return;
  const { from, to } = S.clear;
  if (!from || !to || from > to) return alert('Invalid period');
  busy = true;
  found = null;
  $('#x-box').innerHTML = '<p class="hint" id="x-status">Searching...</p>';
  try {
    const me = await jira('GET', '/rest/api/3/myself');
    const issues = await searchIssues(`worklogAuthor = currentUser() AND worklogDate >= "${addDays(from, -1)}" AND worklogDate <= "${addDays(to, 1)}"`, ['summary']);
    const items = [];
    let n = 0;
    for (const is of issues) {
      $('#x-status').textContent = `Issue ${++n}/${issues.length}: ${is.key}`;
      for (let start = 0; ;) {
        const r = await jira('GET', `/rest/api/3/issue/${encodeURIComponent(is.key)}/worklog?startAt=${start}&maxResults=1000`);
        for (const w of r.worklogs) {
          if (w.author?.accountId !== me.accountId) continue;
          const date = ymd(new Date(w.started.replace(/([+-]\d\d)(\d\d)$/, '$1:$2')));
          if (date >= from && date <= to) items.push({ id: w.id, key: is.key, date, min: Math.round(w.timeSpentSeconds / 60), summary: val(is.fields.summary) });
        }
        start += r.worklogs.length;
        if (!r.worklogs.length || start >= r.total) break;
      }
    }
    items.sort((a, b) => a.date.localeCompare(b.date) || a.key.localeCompare(b.key));
    found = { items };
  } catch (e) {
    $('#x-box').innerHTML = `<p class="err">${esc(e.message)}</p>`;
    busy = false;
    return;
  }
  busy = false;
  renderClear();
};

$('#x-box').addEventListener('click', async (e) => {
  if (e.target.id === 'x-stop') { stopReq = true; setStatus($('#x-status'), 'Stopping after the current request...'); return; }
  if (e.target.id !== 'x-del' || busy || !found) return;
  const n = found.items.length;
  if (!confirm(`Delete ${n} of your worklogs for ${S.clear.from} — ${S.clear.to}? This cannot be undone.`)) return;
  busy = true;
  stopReq = false;
  renderClear();
  let ok = 0, fail = 0, lastErr = '';
  for (const w of [...found.items]) {
    if (stopReq) break;
    const st = $('#x-status');
    if (st) st.textContent = `Deleting ${ok + fail + 1}/${n}...`;
    try {
      await jira('DELETE', `/rest/api/3/issue/${encodeURIComponent(w.key)}/worklog/${w.id}?adjustEstimate=leave`);
      found.items = found.items.filter((x) => x !== w);
      ok++;
    } catch (x) {
      fail++; lastErr = x.message;
      if (x.status === 401 || x.status === 0) break;
    }
  }
  busy = false;
  renderClear();
  setStatus($('#x-status') || document.createElement('span'), '');
  const msg = `${stopReq ? 'Stopped. ' : ''}Deleted: ${ok}, failed: ${fail}${lastErr ? ' (' + lastErr + ')' : ''}`;
  const box = $('#x-box');
  box.insertAdjacentHTML('afterbegin', `<p class="${fail ? 'err' : 'okc'}">${esc(msg)}</p>`);
});

(async () => {
  await loadConfig();
  fillConn();
  renderStatusOptions();
  localStorage.setItem(LS, JSON.stringify(S));
  show(S.conn.token ? 'tasks' : 'conn');
})();
</script>
</body>
</html>
'''

if __name__ == '__main__':
    main()
