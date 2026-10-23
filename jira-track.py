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
CONFIG_KEYS = ('conn', 'jql', 'jqlTracked', 'fields', 'pinned', 'workday', 'track')


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
        if self.path == '/api/shutdown':
            self.reply(200, 'bye')
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
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
    port = int(os.environ.get('JIRA_TRACK_PORT') or 4777)
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
nav button { background:none; border:0; padding:0 14px; height:34px; line-height:34px; border-radius:6px; color:var(--mut); cursor:pointer; font:inherit; }
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
button.btn { font:inherit; padding:0 14px; height:34px; line-height:32px; vertical-align:middle; border-radius:6px; border:1px solid var(--line); background:var(--card); color:var(--fg); cursor:pointer; }
button.pri { background:var(--acc); border-color:var(--acc); color:#fff; }
button.danger { background:var(--bad); border-color:var(--bad); color:#fff; }
button:disabled { opacity:.5; cursor:default; }
.hint { color:var(--mut); font-size:12px; margin:6px 0; }
.err { color:var(--bad); } .okc { color:var(--ok); }
.busy::before { content:''; display:inline-block; width:12px; height:12px; margin-right:6px; vertical-align:-2px; border:2px solid var(--line); border-top-color:var(--acc); border-radius:50%; animation:spin .8s linear infinite; }
@keyframes spin { to { transform:rotate(360deg); } }
#x-del { width:17em; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
#x-del .busy::before { border-color:rgba(255,255,255,.35); border-top-color:#fff; }
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
details.stat > summary { cursor:pointer; }
.stat .how { margin:8px 0 0; padding-left:18px; color:var(--mut); font-size:12px; line-height:1.7; }
.stat .how b { color:var(--fg); font-weight:600; }
.seg { border:1px solid var(--line); border-radius:8px; padding:12px 16px 4px; margin-bottom:14px; }
.seg > h3 { margin:0 0 10px; font-size:11px; text-transform:uppercase; letter-spacing:.06em; color:var(--mut); }
details.fold > summary { cursor:pointer; user-select:none; color:var(--mut); font-size:12px; margin-bottom:8px; }
details.seg > summary { font-size:11px; text-transform:uppercase; letter-spacing:.06em; margin:0 0 10px; }
details.seg:not([open]) { padding-bottom:12px; }
details.seg:not([open]) > summary { margin-bottom:0; }
.split { justify-content:space-between; align-items:center; margin-top:12px; }
.lbl { color:var(--mut); font-size:12px; margin-bottom:3px; }
.chips { display:flex; flex-wrap:wrap; gap:6px; align-items:center; min-height:32px; }
.chips .chip { margin:0; }
.sub { text-transform:none; letter-spacing:0; margin-left:12px; color:var(--fg); font-size:12px; }
#s-ts-sum { display:inline-block; max-width:75%; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; vertical-align:bottom; }
td input.sug { font-style:italic; color:var(--mut); }
.done td { opacity:.55; }
a { color:var(--acc); text-decoration:none; }
progress { width:200px; vertical-align:middle; }
.views { display:inline-flex; border:1px solid var(--line); border-radius:6px; overflow:hidden; margin-left:auto; }
.views button { border:0; background:var(--card); color:var(--mut); padding:0 14px; height:32px; line-height:32px; cursor:pointer; font:inherit; }
.views button.on { background:var(--acc); color:#fff; }
.ptable { width:auto; min-width:100%; }
.ptable th.c, .ptable td.c { text-align:center; white-space:nowrap; padding:4px 8px; border-left:1px solid var(--line); }
.ptable th.c small { display:block; font-weight:400; }
.ptable .stk { position:sticky; left:0; background:var(--card); z-index:1; white-space:nowrap; }
.ptable td.sum { max-width:260px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.ptable td.has { background:color-mix(in srgb, var(--acc) 14%, transparent); }
.ptable td.sent { color:var(--ok); }
.ptable td.rm { cursor:pointer; }
.ptable td.rm:hover { background:color-mix(in srgb, var(--bad) 22%, transparent); }
.ltable { table-layout:fixed; }
.ltable td.t { width:130px; white-space:nowrap; }
.ltable td.k { width:130px; white-space:nowrap; }
.ltable td.num { text-align:right; }
.ltable td.st { width:170px; }
.ltable td.sum div { display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }
.ctable { table-layout:fixed; }
.ptable td.fail { color:var(--bad); }
.ptable td.gone { color:var(--mut); text-decoration:line-through; }
header .quit { margin-left:auto; }
.ptable tfoot td { font-weight:600; border-top:2px solid var(--line); }
</style>
</head>
<body>
<header>
  <h1>Jira Easy Track</h1>
  <nav id="nav">
    <button data-tab="conn">1. Setup</button>
    <button data-tab="tasks">2. Tasks</button>
    <button data-tab="prev">3. Preview</button>
    <button data-tab="clear">4. Review</button>
  </nav>
  <button class="btn danger quit" id="quit" title="Stop the local server">Stop app</button>
</header>
<main>

<section class="tab" id="t-conn">
  <h2>Setup</h2>
  <div class="seg">
    <h3>Authorization</h3>
    <label>Jira URL<input class="wide" id="c-base" placeholder="https://company.atlassian.net"></label>
    <label>Email<input class="wide" id="c-email" autocomplete="off"></label>
    <label>API token<input class="wide" id="c-token" type="password" autocomplete="off"></label>
    <p class="hint">Create a token at id.atlassian.com/manage-profile/security/api-tokens. It is stored only in this browser's localStorage and is sent only to Jira through the local server.</p>
    <div class="row"><button class="btn pri" id="c-test">Test and save</button> <span id="c-status"></span></div>
  </div>
  <div class="seg">
    <h3>Config file</h3>
    <p class="hint">Saves the connection (including the token, in plain text), JQL, displayed fields, pinned tasks (with their per day hours) and the working day settings to a JSON file next to the script. Once saved, changes are written automatically and loaded on every start.</p>
    <div class="row"><button class="btn" id="c-savecfg">Save to config file</button> <span data-cfg></span></div>
  </div>
  <details class="seg fold" open>
    <summary>Working day<span class="sub" id="s-wd-sum"></span></summary>
    <div class="row">
      <label>Day start<input type="time" data-b="sched.dayStart"></label>
      <label>Day end<input type="time" data-b="sched.dayEnd"></label>
      <label>Break from<input type="time" data-b="sched.breakStart"></label>
      <label>Break to<input type="time" data-b="sched.breakEnd"></label>
      <label>Step, min<select data-b="sched.step"><option>5</option><option>10</option><option>15</option><option>30</option><option>60</option></select></label>
    </div>
    <div class="days" id="s-days"></div>
  </details>
</section>

<section class="tab" id="t-tasks">
  <h2>Tasks and hours</h2>
  <details class="seg fold">
  <summary>How this works</summary>
  <ul class="help">
    <li><b>Tracked</b>: your time already tracked on the task in the Period.</li>
    <li><b>To track</b>: hours to add, spread across the working days of the period. If left empty, the task's original estimate from Jira is used (shown in italics; 0 if it has none). Type 0 to track nothing.</li>
    <li><b>Per day</b>: hours logged on every working day.</li>
    <li><b>Timing</b>: how To track is spread: evenly, towards the start, middle or end, or a random share per day.</li>
    <li><b>Range</b>: which days a task can be tracked on. It is preset when tasks are loaded, based on the task's status history; change it per task if needed.
      <ul>
        <li><b>Task window</b>: from the task's first move into status 1 to its first move into status 2 (set in Task tracking window), within the period. Preset if the task has such a transition.</li>
        <li><b>Whole period</b>: every working day of the period. Preset if it does not.</li>
      </ul>
    </li>
    <li><b>Pin</b>: pinned tasks (and their Per day hours) are saved to the config file; on start only pinned tasks are shown.</li>
    <li><b>Hours formats</b>: 8, 1.5, 1:30, 1h 30m, 45m.</li>
  </ul>
  </details>
  <details class="seg fold">
    <summary>Task tracking window<span class="sub" id="s-tw-sum"></span></summary>
    <div class="row">
      <label>Status 1 (start)<select id="t-from" data-b="track.from"></select></label>
      <label>Status 2 (end)<select id="t-to" data-b="track.to"></select></label>
      <button class="btn" id="t-load">Load statuses</button> <span id="t-st"></span>
    </div>
    <label style="display:flex;gap:6px;align-items:center;color:var(--fg);font-size:13px"><input type="checkbox" id="t-on" style="margin:0"> Show only tasks inside the tracking window</label>
    <p class="hint">The window of a task is from its first move into status 1 to its first move into status 2 (still open if it has not moved there yet).</p>
    <p class="hint">With the checkbox on, only tasks whose window overlaps the Period are listed. In Task window mode a task is tracked only on working days inside its window. Changing a status re-reads the history of the loaded tasks.</p>
  </details>
  <details class="seg fold">
    <summary>Distribution options<span class="sub" id="s-do-sum"></span></summary>
    <label style="display:flex;gap:6px;align-items:center;color:var(--fg);font-size:13px"><input type="checkbox" id="s-varied" style="margin:0"> Realistic spread (different hours on different days; recalculate for a new variation)</label>
    <label style="display:flex;gap:6px;align-items:center;color:var(--fg);font-size:13px"><input type="checkbox" id="s-tracked" style="margin:0"> Account for already tracked time</label>
    <p class="hint">Your worklogs already in Jira for the period are read on Calculate: their time slots are kept free in the working day, and a task's Per day is reduced by what is already tracked on it that day. To track is always added in full.</p>
  </details>
  <details class="seg fold">
    <summary>Period<span class="sub" id="s-per-sum"></span></summary>
    <div class="row">
      <label>From<input type="date" data-b="sched.from"></label>
      <label>To<input type="date" data-b="sched.to"></label>
    </div>
    <div class="row">
      <label class="grow">Days off / holidays (YYYY-MM-DD, comma-separated)<input data-b="sched.exclude" placeholder="2026-11-04, 2026-11-05"></label>
      <label class="grow">Extra working days (YYYY-MM-DD, comma-separated)<input data-b="sched.include" placeholder="2026-11-08, 2026-11-15"></label>
    </div>
  </details>
  <details class="seg fold">
    <summary>Task source<span class="sub" id="s-ts-sum"></span></summary>
    <div class="row">
      <label class="grow">JQL<input id="k-jql" data-b="jql"></label>
    </div>
    <label style="display:flex;gap:6px;align-items:center;color:var(--fg);font-size:13px"><input type="checkbox" id="k-jqltr" style="margin:0"> Also add tasks I tracked time on in the Period</label>
    <div class="row">
      <div class="grow"><div class="lbl">Fields</div><div class="chips" id="k-fields"></div></div>
      <label>Add field<input id="k-addfield" list="k-fieldlist" placeholder="name or id"></label>
      <datalist id="k-fieldlist"></datalist>
      <button class="btn" id="k-addbtn">+</button>
    </div>
    <div class="row">
      <label>Add task by key<input id="k-key" placeholder="PROJ-123"></label>
      <button class="btn" id="k-keybtn">Add</button>
    </div>
  </details>
  <div class="row" style="align-items:center"><button class="btn pri" id="k-load">Load tasks</button> <span id="k-loadst"></span></div>
  <div class="seg">
    <h3>Tasks</h3>
    <div class="row">
      <label>Filter<input id="k-filter" placeholder="text"></label>
      <label>Filter by<select id="k-ffield"></select></label>
      <label style="display:flex;gap:6px;align-items:center;margin-bottom:6px"><input type="checkbox" id="k-only" style="margin:0"> only with hours</label>
      <label style="display:flex;gap:6px;align-items:center;margin-bottom:6px"><input type="checkbox" id="k-pinned" style="margin:0" checked> only pinned</label>
    </div>
    <div id="k-status"></div>
    <div style="overflow:auto;margin-bottom:12px"><table id="k-table"></table></div>
  </div>
  <details class="stat" id="s-stat"><summary id="s-stat-sum"></summary><ul class="how" id="s-stat-how"></ul></details>
  <div class="row split">
    <div><button class="btn pri" id="s-calc">Calculate distribution</button> <span id="s-calcst"></span></div>
    <button class="btn" id="k-clear" title="Remove loaded tasks, hours and cached task history">Clear data</button>
  </div>
</section>

<section class="tab" id="t-prev">
  <h2>Distribution preview</h2>
  <div id="p-box"></div>
</section>

<section class="tab" id="t-clear">
  <h2>Review tracked time</h2>
  <p class="hint">Your own worklogs within the selected period (inclusive). Click a cell or × to delete its worklogs, click it again to restore them. Click a day in the Total row to delete the whole day.</p>
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
  jqlTracked: false,
  fields: [{ id: 'summary', name: 'Summary' }],
  pinned: [],
  track: { from: 'In Progress', to: 'Done', on: true },
  windows: {},
  plan: {},
  issues: [],
  sched: { from: monthStart, to: today, dayStart: '10:00', dayEnd: '19:00', breakStart: '13:00', breakEnd: '14:00', step: '15', days: [1, 2, 3, 4, 5], exclude: '', include: '', varied: false, useTracked: false },
  clear: { from: monthStart, to: today },
};
let S;
try {
  const saved = JSON.parse(localStorage.getItem(LS) || '{}');
  S = { ...structuredClone(DEF), ...saved };
  S.sched = { ...DEF.sched, ...saved.sched };
  // The Review period starts from the Tasks period on every launch, then changes independently.
  S.clear = { from: S.sched.from, to: S.sched.to };
  S.conn = { ...DEF.conn, ...saved.conn };
  delete S.dfilter;
  delete S.tview;
  S.track = { from: saved.track?.from || DEF.track.from, to: saved.track?.to || DEF.track.to, on: saved.track?.on !== false };
} catch { S = structuredClone(DEF); }
const CFG_KEYS = ['conn', 'jql', 'jqlTracked', 'fields', 'pinned', 'track'];
const WORKDAY_KEYS = ['dayStart', 'dayEnd', 'breakStart', 'breakEnd', 'step', 'days', 'varied', 'useTracked'];
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
    body.pinned = S.pinned.map((key) => ({ key, perDay: S.plan[key]?.fixed || '' }));
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
    if (typeof c.jqlTracked === 'boolean') S.jqlTracked = c.jqlTracked;
    if (Array.isArray(c.fields) && c.fields.every((f) => f && f.id)) S.fields = c.fields.map((f) => ({ id: String(f.id), name: String(f.name || f.id) }));
    if (Array.isArray(c.pinned)) {
      const items = c.pinned.map((p) => (p && typeof p === 'object' ? p : { key: p })).filter((p) => p.key);
      S.pinned = items.map((p) => String(p.key));
      items.forEach((p) => {
        if (typeof p.perDay !== 'string' && typeof p.perDay !== 'number') return;
        const k = String(p.key);
        const pl = (S.plan[k] ??= { total: '', fixed: '', shift: '', range: '' });
        pl.fixed = String(p.perDay);
        if (!pl.total && !pl.fixed && !pl.shift && !pl.range) delete S.plan[k];
      });
    }
    const w = c.workday;
    if (w && typeof w === 'object') {
      ['dayStart', 'dayEnd', 'breakStart', 'breakEnd'].forEach((k) => { if (typeof w[k] === 'string') S.sched[k] = w[k]; });
      if (['5', '10', '15', '30', '60'].includes(String(w.step))) S.sched.step = String(w.step);
      if (Array.isArray(w.days)) S.sched.days = w.days.map(Number).filter((d) => d >= 0 && d <= 6);
      if (typeof w.varied === 'boolean') S.sched.varied = w.varied;
      if (typeof w.useTracked === 'boolean') S.sched.useTracked = w.useTracked;
    }
    const tr = c.track;
    if (tr && typeof tr === 'object') {
      if (typeof tr.from === 'string' && tr.from) S.track.from = tr.from;
      if (typeof tr.to === 'string' && tr.to) S.track.to = tr.to;
      if (typeof tr.on === 'boolean') S.track.on = tr.on;
    }
    cfgOn = true;
    cfgStatus('Loaded from ' + j.path, 'okc');
  } catch {
    // no config available, keep browser-stored state
  }
}

// Each tab has its own Stop: pStop for sending on Preview, xStop for deleting on Clear.
let pStop = false;
let xStop = false;
let xBusy = false;  // Clear tab: searching or deleting

let P = null;      // preview: { entries, warnings }
let found = null;  // worklogs found for clearing
let busy = false;  // Preview tab: sending
let catalog = null;
let catalogTried = false;

// ---------- Jira API ----------
class JErr extends Error { constructor(m, status) { super(m); this.status = status; } }
const b64 = (s) => btoa(String.fromCharCode(...new TextEncoder().encode(s)));
const baseUrl = () => S.conn.base;

async function jira(method, path, body) {
  const c = S.conn;
  if (!c.base || !c.email || !c.token) throw new JErr('Fill in the Setup tab first', 0);
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

// Own worklogs started within from..to (inclusive, local dates); start is minutes from midnight.
async function findMyWorklogs(from, to, onProgress) {
  const me = await jira('GET', '/rest/api/3/myself');
  const issues = await searchIssues(`worklogAuthor = currentUser() AND worklogDate >= "${addDays(from, -1)}" AND worklogDate <= "${addDays(to, 1)}"`, ['summary']);
  const items = [];
  let n = 0;
  for (const is of issues) {
    if (onProgress) onProgress(++n, issues.length, is.key);
    for (let start = 0; ;) {
      const r = await jira('GET', `/rest/api/3/issue/${encodeURIComponent(is.key)}/worklog?startAt=${start}&maxResults=1000`);
      for (const w of r.worklogs) {
        if (w.author?.accountId !== me.accountId) continue;
        const dt = parseJiraDate(w.started);
        const date = ymd(dt);
        if (date >= from && date <= to) items.push({ id: w.id, key: is.key, date, start: dt.getHours() * 60 + dt.getMinutes(), min: Math.round(w.timeSpentSeconds / 60), summary: val(is.fields.summary), started: w.started, sec: w.timeSpentSeconds, comment: w.comment });
      }
      start += r.worklogs.length;
      if (!r.worklogs.length || start >= r.total) break;
    }
  }
  items.sort((a, b) => a.date.localeCompare(b.date) || a.key.localeCompare(b.key));
  return items;
}

const fieldIds = () => [...new Set([...S.fields.map((f) => f.id), 'created', 'timeoriginalestimate'])];

async function loadPinned(onProgress) {
  if (!S.pinned.length) { S.issues = []; save(); return; }
  S.issues = await searchIssues(`key in (${S.pinned.map((k) => '"' + k + '"').join(',')})`, fieldIds());
  await loadWindows(S.issues.map((i) => i.key), onProgress);
  save();
}

async function loadIssues(onProgress) {
  const ids = fieldIds();
  let list = await searchIssues(S.jql, ids);
  // Tasks with your worklogs in the Period are added after the JQL results and always listed (see viewIssues).
  if (S.jqlTracked && S.sched.from && S.sched.to && S.sched.from <= S.sched.to) {
    const seen = new Set(list.map((i) => i.key));
    const tracked = await searchIssues(`worklogAuthor = currentUser() AND worklogDate >= "${S.sched.from}" AND worklogDate <= "${S.sched.to}" ORDER BY updated DESC`, ids);
    tracked.forEach((i) => { i.wl = true; });
    list.forEach((i) => { if (tracked.some((t) => t.key === i.key)) i.wl = true; });
    list = list.concat(tracked.filter((i) => !seen.has(i.key)));
  }
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

let pinnedOnly = true;
const viewIssues = () => S.issues.filter((i) => (pinnedOnly ? S.pinned.includes(i.key) : (S.jqlTracked && i.wl) || inTrackWindow(i.key)));
const estMin = (key) => Math.round((S.issues.find((i) => i.key === key)?.fields?.timeoriginalestimate || 0) / 60);
const fmtH = (m) => (m % 60 ? `${Math.floor(m / 60)}:${pad(m % 60)}` : String(m / 60));
// Plan with To track (total) defaulted to the original estimate for the tasks in view when the user has not entered one.
function planOf() {
  const out = {};
  for (const i of viewIssues()) { const m = estMin(i.key); if (m) out[i.key] = { total: fmtH(m) }; }
  for (const [k, p] of Object.entries(S.plan)) out[k] = { ...p, total: p.total || out[k]?.total || '' };
  return out;
}

const sumOf = (key) => val(S.issues.find((i) => i.key === key)?.fields?.summary);
const link = (key) => `<a href="${esc(baseUrl())}/browse/${esc(key)}" target="_blank" rel="noopener">${esc(key)}</a>`;
const setStatus = (el, text, cls) => { el.className = cls || ''; el.textContent = text; };

// ---------- tabs ----------
function show(tab) {
  document.querySelectorAll('.tab').forEach((t) => t.classList.toggle('on', t.id === 't-' + tab));
  document.querySelectorAll('#nav button').forEach((b) => b.classList.toggle('on', b.dataset.tab === tab));
  syncInputs();
  if (tab === 'tasks') { renderTasks(); renderTrackOptions(); }
  if (tab === 'conn') renderSched();
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
  if (el.dataset.b.startsWith('sched') || el.dataset.b.startsWith('track.') || el.dataset.b === 'jql') renderStats();
  if (el.dataset.b.startsWith('sched.')) renderTasks();
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

// ---------- 3. tasks ----------
function renderFields() {
  $('#k-fields').innerHTML = '<span class="chip">Key</span>' + S.fields.map((f, i) =>
    `<span class="chip">${esc(f.name)} <button data-rmf="${i}" title="remove">×</button></span>`).join('');
}

// Tasks shown in the list: the current view narrowed by the filter box and "only with hours".
function listedIssues() {
  const filter = $('#k-filter').value.trim().toLowerCase();
  const only = $('#k-only').checked;
  const fcur = $('#k-ffield').value;
  return viewIssues().filter((i) => {
    const p = S.plan[i.key] || {};
    const hay = (fcur === '__key' ? i.key : val(i.fields?.[fcur])).toLowerCase();
    if (filter && !hay.includes(filter)) return false;
    return !only || !!(p.total || estMin(i.key) || p.fixed);
  });
}

function renderTasks() {
  renderFields();
  $('#k-pinned').checked = pinnedOnly;
  const ff = $('#k-ffield');
  const fopts = [['__key', 'Key'], ...S.fields.map((f) => [f.id, f.name])];
  let fcur = ff.value;
  if (!fopts.some((o) => o[0] === fcur)) fcur = S.fields.some((f) => f.id === 'summary') ? 'summary' : fopts[fopts.length > 1 ? 1 : 0][0];
  ff.innerHTML = fopts.map(([v, n]) => `<option value="${esc(v)}">${esc(n)}</option>`).join('');
  ff.value = fcur;
  const head = '<tr><th>Key</th>' + S.fields.map((f) => `<th>${esc(f.name)}</th>`).join('') + '<th class="num" title="Your time already tracked on the task in the Period">Tracked</th><th class="num">To track</th><th class="num">Per day</th><th>Timing</th><th>Range</th><th>Tracking window</th><th>Pin</th></tr>';
  const visible = viewIssues();
  const rows = listedIssues().map((i) => {
    const p = S.plan[i.key] || {};
    const est = estMin(i.key);
    const tot = p.total || (est ? fmtH(est) : '');
    const cells = S.fields.map((f) => { const v = val(i.fields?.[f.id]); return `<td>${esc(v.length > 200 ? v.slice(0, 200) + '…' : v)}</td>`; }).join('');
    return `<tr><td>${link(i.key)}</td>${cells}` +
      `<td class="num" data-trk="${esc(i.key)}">${esc(trackedText(i.key))}</td>` +
      `<td class="num"><input${!p.total && est ? ' class="sug"' : ''} data-k="${esc(i.key)}" data-f="total" value="${esc(tot)}" placeholder="0"${est ? ` title="Original estimate: ${esc(fmtD(est))}"` : ''}></td>` +
      `<td class="num"><input data-k="${esc(i.key)}" data-f="fixed" value="${esc(p.fixed || '')}" placeholder="0"></td>` +
      `<td><select data-k="${esc(i.key)}" data-f="shift">${SHIFTS.map(([v, l]) => `<option value="${v}"${(p.shift || '') === v ? ' selected' : ''}>${l}</option>`).join('')}</select></td>` +
      `<td><select data-k="${esc(i.key)}" data-f="range">${RANGES.map(([v, l]) => `<option value="${v}"${effRange(i.key) === v ? ' selected' : ''}>${l}</option>`).join('')}</select></td>` +
      `<td class="tw" data-tw="${esc(i.key)}" style="white-space:nowrap">${esc(twText(i.key))}</td>` +
      `<td><input type="checkbox" style="width:auto" data-pin="${esc(i.key)}"${S.pinned.includes(i.key) ? ' checked' : ''}></td></tr>`;
  }).join('');
  $('#k-table').innerHTML = head + rows;
  if (S.conn.token && periodOk() && !trackedFresh()) scheduleTracked();
  $('#k-status').innerHTML = visible.length ? `<p class="hint">${tasksCount(visible)}. ${planSummary()}</p>` : `<p class="hint">${pinnedOnly ? 'No pinned tasks. Untick "only pinned" or click "Load tasks", then pin the ones you need.' : 'Click "Load tasks".'}</p>`;
  renderStats();
}

// Dates are shown only for the "Task window" range; a single date when start and end are the same day.
function twText(key) {
  if (effRange(key) !== 'window' || !winValid(key)) return '';
  const { start, end } = S.windows[key];
  if (!start) return '';
  // Time the schedule allows inside the window (working days of the Period) minus your worklogs on those days (all tasks).
  const g = dayGeometry();
  let avail = '';
  if (g) {
    const wdays = workDays().filter((d) => d >= start && (!end || d <= end));
    const inWin = new Set(wdays);
    const ready = trackedFresh() && !trackedCache.err;
    const done = ready ? trackedCache.items.reduce((a, w) => a + (inWin.has(w.date) ? w.min : 0), 0) : 0;
    const loading = S.conn.token && periodOk() && !trackedFresh();
    avail = ` (${loading ? '...' : fmtD(Math.max(0, wdays.length * g.len - done))} available)`;
  }
  return (end === start ? start : `${start} – ${end || 'now'}`) + avail;
}

const tasksCount = (visible) => `Tasks: ${visible.length}${visible.length < S.issues.length ? ' of ' + S.issues.length : ''}`;

// A task is inside the tracking window when its status 1 → status 2 span overlaps the Period.
function inTrackWindow(key) {
  if (!S.track.on) return true;
  const w = winValid(key) ? S.windows[key] : null;
  return !!(w && w.start && w.start <= S.sched.to && (!w.end || w.end >= S.sched.from));
}

function planSummary() {
  const plan = Object.values(planOf());
  const t = plan.reduce((a, p) => a + (parseH(p.total) || 0), 0);
  const f = plan.reduce((a, p) => a + (parseH(p.fixed) || 0), 0);
  return `To distribute: ${fmtD(t)}; fixed per day: ${fmtD(f)}.`;
}

$('#k-table').addEventListener('input', (e) => {
  const el = e.target;
  if (!el.dataset.k) return;
  const p = (S.plan[el.dataset.k] ??= { total: '', fixed: '', shift: '', range: '' });
  p[el.dataset.f] = el.value.trim();
  if (el.tagName === 'INPUT') el.classList.toggle('bad', Number.isNaN(parseH(el.value)));
  if (el.dataset.f === 'total') el.classList.remove('sug');
  if (!p.total && !p.fixed && !p.shift && !p.range) delete S.plan[el.dataset.k];
  save();
  if (el.dataset.f === 'range') { const c = el.closest('tr').querySelector('.tw'); if (c) c.textContent = twText(el.dataset.k); }
  const hint = $('#k-status .hint');
  if (hint) hint.textContent = `${tasksCount(viewIssues())}. ${planSummary()}`;
  renderStats();
});
$('#k-table').addEventListener('change', (e) => {
  const key = e.target.dataset.pin;
  if (!key) return;
  S.pinned = S.pinned.filter((k) => k !== key);
  if (e.target.checked) S.pinned.push(key);
  save();
  renderStats();
});
$('#k-filter').oninput = renderTasks;
$('#k-ffield').onchange = renderTasks;
$('#k-only').onchange = renderTasks;
$('#k-jqltr').onchange = (e) => { S.jqlTracked = e.target.checked; save(); renderTasks(); };
$('#k-pinned').onchange = (e) => { pinnedOnly = e.target.checked; reload(); };
$('#k-clear').onclick = () => {
  if (!confirm('Remove loaded tasks, entered hours, cached task history and the current distribution from this browser?')) return;
  S.issues = [];
  S.plan = {};
  S.windows = {};
  P = null;
  trackedCache = null;
  save();
  renderTasks();
  renderStats();
  setStatus($('#s-calcst'), '');
};

async function reload() {
  const st = $('#k-status'), ls = $('#k-loadst'), btn = $('#k-load');
  setStatus(ls, 'Loading tasks...', 'busy');
  btn.disabled = true;
  try {
    await (pinnedOnly ? loadPinned : loadIssues)((d, n) => setStatus(ls, `Reading task history ${d}/${n}...`, 'busy'));
    renderTasks();
  } catch (e) { setStatus(st, e.message, 'err'); } finally {
    btn.disabled = false;
    setStatus(ls, '');
  }
}
$('#k-load').onclick = () => { pinnedOnly = false; reload(); };

$('#k-fields').onclick = (e) => {
  const b = e.target.closest('[data-rmf]');
  if (!b) return;
  S.fields.splice(+b.dataset.rmf, 1);
  save();
  renderTasks();
};

async function loadCatalog() {
  if (catalog) return;
  try {
    catalog = await jira('GET', '/rest/api/3/field');
    $('#k-fieldlist').innerHTML = catalog.map((f) => `<option value="${esc(f.name)}">${esc(f.id)}</option>`).join('');
  } catch {
    // the error is shown when adding
  }
}
$('#k-addfield').onfocus = loadCatalog;

$('#t-on').onchange = (e) => {
  S.track.on = e.target.checked;
  save();
  renderTasks();
  renderStats();
  if (S.track.on && S.conn.token && S.issues.length) refreshWindows();
};
$('#k-addbtn').onclick = async () => {
  const q = $('#k-addfield').value.trim().toLowerCase();
  if (!q) return;
  await loadCatalog();
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
  try { await (pinnedOnly ? loadPinned : loadIssues)(); $('#k-key').value = ''; renderTasks(); } catch (e) {
    if (!had) S.pinned = S.pinned.filter((k) => k !== key);
    setStatus($('#k-status'), e.message, 'err');
  }
};

// ---------- 2. schedule ----------
function renderTrackOptions() {
  if (!statusList.length && !statusTried && S.conn.token) { statusTried = true; loadStatuses(true); }
  if (!catalog && !catalogTried && S.conn.token) { catalogTried = true; loadCatalog(); }
  $('#s-varied').checked = !!S.sched.varied;
  $('#s-tracked').checked = !!S.sched.useTracked;
  $('#t-on').checked = !!S.track.on;
  renderStats();
}
function renderSched() {
  $('#s-days').innerHTML = [1, 2, 3, 4, 5, 6, 0].map((d) =>
    `<label><input type="checkbox" data-day="${d}" ${S.sched.days.includes(d) ? 'checked' : ''}>${WD[d]}</label>`).join('');
  renderStats();
}
$('#s-varied').onchange = (e) => { S.sched.varied = e.target.checked; save(); renderStats(); };
$('#s-tracked').onchange = (e) => { S.sched.useTracked = e.target.checked; save(); renderStats(); };

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
  renderTasks();
}

async function ensureWindows(onProgress) {
  const keys = Object.entries(planOf())
    .filter(([, p]) => (parseH(p.total) > 0 || parseH(p.fixed) > 0) && p.range !== 'period')
    .map(([k]) => k);
  await loadWindows(keys, onProgress, true);
}
$('#s-days').onchange = (e) => {
  const d = +e.target.dataset.day;
  S.sched.days = S.sched.days.filter((x) => x !== d);
  if (e.target.checked) S.sched.days.push(d);
  save();
  renderStats();
};

function workDays(from = S.sched.from, to = S.sched.to) {
  const { days, exclude, include } = S.sched;
  const ex = new Set(exclude.split(/[\s,;]+/).filter(Boolean));
  const inc = new Set(include.split(/[\s,;]+/).filter(Boolean));
  const out = [];
  if (!from || !to) return out;
  for (let d = pYmd(from), n = 0; ymd(d) <= to && n < 400; d.setDate(d.getDate() + 1), n++) {
    if ((days.includes(d.getDay()) || inc.has(ymd(d))) && !ex.has(ymd(d))) out.push(ymd(d));
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

// Working time of a day (without the break) minus the busy intervals, as sorted [start, end] segments.
function freeSegs(g, busy) {
  let segs = g.hasBreak ? [[g.ds, g.bs], [g.be, g.de]] : [[g.ds, g.de]];
  busy.forEach(([bs, be]) => {
    segs = segs.flatMap(([s, e]) => (be <= s || bs >= e ? [[s, e]] : [[s, bs], [be, e]].filter(([a, b]) => b > a)));
  });
  return segs;
}

// Tasks with hours, the days they may be tracked on (Range) and the already tracked time they cover.
// tracked: own worklogs already in Jira for the period (see findMyWorklogs), empty unless the option is on.
function planTasks(days, tracked, warnings) {
  const tasks = Object.entries(planOf())
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
  const trackedDay = {}, trackedBy = {}, busy = {};
  tracked.forEach((w) => {
    const td = (trackedDay[w.key] ??= {});
    td[w.date] = (td[w.date] || 0) + w.min;
    trackedBy[w.key] = (trackedBy[w.key] || 0) + w.min;
    (busy[w.date] ??= []).push([w.start, w.start + w.min]);
  });
  return { tasks, ranges, trackedDay, trackedBy, busy };
}

function layout(tracked = []) {
  const g = dayGeometry();
  if (!g) return { error: 'Invalid working day start/end time' };
  if (!S.sched.from || !S.sched.to || S.sched.from > S.sched.to) return { error: 'Invalid period' };
  const days = workDays();
  if (!days.length) return { error: 'No working days in the period' };
  const step = Number(S.sched.step) || 15;
  const units = (m) => Math.max(1, Math.round(m / step));
  const warnings = [];
  const { tasks, ranges, trackedDay, trackedBy, busy } = planTasks(days, tracked, warnings);
  const free = days.map((date) => freeSegs(g, busy[date] || []));
  const cap = free.map((segs) => Math.floor(segs.reduce((a, [s, e]) => a + e - s, 0) / step));
  const alloc = days.map(() => []);

  tasks.filter((t) => t.fixed > 0).forEach((t) => {
    let cut = false;
    days.forEach((date, d) => {
      if (!t.ok[d]) return;
      const done = trackedDay[t.key]?.[date] || 0;
      const u = done ? Math.round(Math.max(0, t.fixed - done) / step) : units(t.fixed);
      if (!u) return;
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
    const U = units(t.total);
    if (!M) return;
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
    const segs = free[d];
    let si = 0, t = segs.length ? segs[0][0] : 0;
    alloc[d].forEach((a) => {
      let rest = a.u * step;
      while (rest > 0 && si < segs.length) {
        if (t >= segs[si][1]) { if (++si < segs.length) t = segs[si][0]; continue; }
        const len = Math.min(rest, segs[si][1] - t);
        entries.push({ id: id++, date, key: a.key, start: t, min: len });
        t += len; rest -= len;
      }
    });
  });
  return { entries, warnings, days, g, tasks, ranges, trackedBy };
}

let trackedCache = null;  // own worklogs of the period: { from, to, items, err }
let trackedTimer = null, trackedPending = '';
const trackedFresh = () => trackedCache && trackedCache.from === S.sched.from && trackedCache.to === S.sched.to;

async function loadTracked(onProgress) {
  const { from, to } = S.sched;
  trackedPending = from + '|' + to;
  try { trackedCache = { from, to, items: await findMyWorklogs(from, to, onProgress) }; } catch (e) {
    trackedCache = { from, to, items: [], err: e.message };
    throw e;
  } finally { trackedPending = ''; }
  return trackedCache.items;
}

// Reads the tracked time for the stats line and the Tracked column in the background, once the inputs stop changing.
function scheduleTracked() {
  if (trackedPending === S.sched.from + '|' + S.sched.to) return;
  clearTimeout(trackedTimer);
  trackedTimer = setTimeout(() => loadTracked().catch(() => {}).finally(() => { renderStats(); updateTrackedCells(); }), 600);
}

const periodOk = () => !!(S.sched.from && S.sched.to && S.sched.from <= S.sched.to);

// Time already tracked on the task in the Period: "..." while loading, "?" on error.
function trackedText(key) {
  if (!S.conn.token || !periodOk()) return '';
  if (!trackedFresh()) return '...';
  if (trackedCache.err) return '?';
  const m = trackedCache.items.reduce((a, w) => a + (w.key === key ? w.min : 0), 0);
  return m ? fmtD(m) : '';
}
const updateTrackedCells = () => {
  document.querySelectorAll('#k-table [data-trk]').forEach((td) => {
    td.textContent = trackedText(td.dataset.trk);
    td.title = trackedFresh() && trackedCache.err ? trackedCache.err : '';
  });
  document.querySelectorAll('#k-table [data-tw]').forEach((td) => { td.textContent = twText(td.dataset.tw); });
};

function renderStats() {
  const s = S.sched;
  const wd = [1, 2, 3, 4, 5, 6, 0].filter((d) => s.days.includes(d)).map((d) => WD[d]).join(', ');
  $('#s-wd-sum').textContent = `${s.dayStart}–${s.dayEnd}${s.breakStart && s.breakEnd ? `, break ${s.breakStart}–${s.breakEnd}` : ''} · ${wd || 'no days'}`;
  $('#s-tw-sum').textContent = `${S.track.from} → ${S.track.to}${S.track.on ? '' : ' · filter off'}`;
  $('#s-per-sum').textContent = `${s.from} → ${s.to}`;
  $('#s-ts-sum').textContent = $('#s-ts-sum').title = S.jql + (S.jqlTracked ? ' + tasks with my worklogs' : '');
  $('#k-jqltr').checked = !!S.jqlTracked;
  $('#s-do-sum').textContent = [s.varied && 'Realistic spread', s.useTracked && 'Account for tracked time'].filter(Boolean).join(' · ');
  const el = $('#s-stat-sum'), how = $('#s-stat-how');
  const g = dayGeometry();
  const days = workDays();
  if (!g || !days.length) { el.textContent = 'Check the period and working day times'; how.innerHTML = ''; return; }
  // With the option on, "already tracked" always keeps its place: "..." while loading, "error" on failure.
  let tracked = [], trackedCell = '';
  if (s.useTracked) {
    if (!S.conn.token) trackedCell = '<span class="err" title="Fill in the Setup tab first">error</span>';
    else if (!trackedFresh()) { trackedCell = '...'; scheduleTracked(); }
    else if (trackedCache.err) trackedCell = `<span class="err" title="${esc(trackedCache.err)}">error</span>`;
    else tracked = trackedCache.items;
  }
  // planned: what the user entered for the tasks shown in the list; the tasks' Tracking windows are not applied here.
  const listed = new Set(listedIssues().map((i) => i.key));
  const plan = Object.entries(planOf()).filter(([k]) => listed.has(k)).map(([, p]) => p);
  const toTrack = plan.reduce((a, p) => a + (parseH(p.total) || 0), 0);
  const perDay = plan.reduce((a, p) => a + (parseH(p.fixed) || 0), 0);
  const planned = toTrack + perDay * days.length;
  const work = days.length * g.len;
  const trackedTot = tracked.reduce((a, w) => a + w.min, 0);
  const available = Math.max(0, work - trackedTot);
  const pending = s.useTracked && trackedCell;
  el.innerHTML = `Working days: <b>${days.length}</b> · per day: <b>${fmtD(g.len)}</b> · total working time: <b>${fmtD(work)}</b>` +
    (s.useTracked ? ` · already tracked: <b>${trackedCell || fmtD(trackedTot)}</b>` : '') +
    ` · available: <b>${pending ? '...' : fmtD(available)}</b> · planned: <b class="${!pending && planned > available ? 'err' : ''}">${fmtD(planned)}</b>`;
  const wdNames = [1, 2, 3, 4, 5, 6, 0].filter((d) => s.days.includes(d)).map((d) => WD[d]).join(', ') || 'none';
  const dayLen = g.de - g.ds;
  how.innerHTML = [
    `<b>Working days</b> = ${days.length}: ${esc(wdNames)} from ${esc(s.from)} to ${esc(s.to)}, minus days off, plus extra working days`,
    `<b>per day</b> = ${fmtT(g.de)} − ${fmtT(g.ds)} (${fmtD(dayLen)})` + (g.hasBreak ? ` − break ${fmtT(g.bs)}–${fmtT(g.be)} (${fmtD(g.be - g.bs)})` : '') + ` = ${fmtD(g.len)}`,
    `<b>total working time</b> = ${days.length} working days × ${fmtD(g.len)} per day = ${fmtD(work)}`,
    s.useTracked ? `<b>already tracked</b> = your worklogs on all tasks from ${esc(s.from)} to ${esc(s.to)} = ${pending ? '...' : fmtD(trackedTot)}` : '',
    s.useTracked ? `<b>available</b> = ${fmtD(work)} total working time − ${pending ? '...' : fmtD(trackedTot)} already tracked = ${pending ? '...' : fmtD(available)}`
      : `<b>available</b> = total working time = ${fmtD(available)} (already tracked time is not subtracted: "Account for already tracked time" is off)`,
    `<b>planned</b> = ${fmtD(toTrack)} To track + ${fmtD(perDay)} Per day × ${days.length} working days = ${fmtD(planned)} (tasks shown in the list); shown in red when it exceeds available`,
    'The Tracking window of each task is not taken into account in these numbers.',
  ].filter(Boolean).map((x) => `<li>${x}</li>`).join('');
}

// Progress of the calculation, shown both on the Tasks tab and on the Preview tab (Recalculate).
function calcStatus(text, cls) {
  setStatus($('#s-calcst'), text, cls);
  const ps = $('#p-status');
  if (ps) setStatus(ps, text, cls);
  const rb = $('#p-recalc');
  if (rb) rb.disabled = busy || cls === 'busy';
}

$('#s-calc').onclick = async () => {
  const useTracked = S.sched.useTracked;
  if (!useTracked && P && P.entries.some((e) => e.done) && !confirm('Some entries were already sent. Recalculating and sending again will create duplicates. Continue?')) return;
  const btn = $('#s-calc');
  if (btn.disabled) return;
  btn.disabled = true;
  const again = !!P;
  calcStatus(again ? 'Recalculating...' : 'Calculating...', 'busy');
  let tracked = [];
  try {
    await ensureWindows((d, n) => calcStatus(`Reading task history ${d}/${n}...`, 'busy'));
    const { from, to } = S.sched;
    if (useTracked && from && to && from <= to) tracked = await loadTracked((n, total) => calcStatus(`Reading tracked time ${n}/${total}...`, 'busy'));
    calcStatus(again ? 'Recalculating...' : 'Calculating...', 'busy');
    await new Promise((res) => setTimeout(res));  // let the status paint before the synchronous layout
  } catch (e) { btn.disabled = false; calcStatus(''); return alert(e.message); }
  btn.disabled = false;
  const r = layout(tracked);
  calcStatus('');
  if (r.error) return alert(r.error);
  if (!r.entries.length) return alert(useTracked && tracked.length ? 'Nothing left to distribute: the hours are already tracked or the working days are full.' : 'No tasks with hours. Fill in hours on the Tasks tab.');
  P = { entries: r.entries, warnings: r.warnings, ranges: r.ranges, days: r.days, trackedBy: useTracked ? r.trackedBy : null };
  show('prev');
  calcStatus(`${again ? 'Recalculated' : 'Calculated'} at ${new Date().toLocaleTimeString()}`, 'okc');
};

// ---------- 4. preview and submit ----------
function jiraStarted(date, min) {
  const [y, m, d] = date.split('-').map(Number);
  const dt = new Date(y, m - 1, d, Math.floor(min / 60), min % 60);
  const off = -dt.getTimezoneOffset();
  const a = Math.abs(off);
  return `${ymd(dt)}T${pad(dt.getHours())}:${pad(dt.getMinutes())}:00.000${off >= 0 ? '+' : '-'}${pad(Math.floor(a / 60))}${pad(a % 60)}`;
}

let pView = 'table';

// Sorted by the first move into the tracking status, then by creation date.
function taskOrder(keys) {
  const date = (k) => {
    if (winValid(k) && S.windows[k].start) return S.windows[k].start;
    const c = S.issues.find((i) => i.key === k)?.fields?.created;
    return c ? ymd(parseJiraDate(c)) : '9999-99-99';
  };
  return keys.map((k) => [k, date(k)])
    .sort((a, b) => a[1].localeCompare(b[1]) || a[0].localeCompare(b[0], undefined, { numeric: true }))
    .map((x) => x[0]);
}

// Tasks × days table of worklog entries ({ key, date, start, min, done, err }).
// opts.rmAttr / opts.dayAttr: data attribute put on clickable cells ("key|date") / day totals ("date") while opts.canRm;
// opts.rmVerb: word for their tooltips; opts.restore: fully done cells stay clickable (to restore); opts.doneCls: class of fully done cells; opts.sum: summary by key.
function entriesTable(entries, days, opts = {}) {
  const sum = opts.sum || sumOf;
  const cell = {}, dayTot = {}, taskTot = {};
  entries.forEach((e) => {
    const c = ((cell[e.key] ??= {})[e.date] ??= { min: 0, n: 0, done: 0, err: '', t: [] });
    c.min += e.min; c.n++; c.t.push(`${fmtT(e.start)}–${fmtT(e.start + e.min)}`);
    if (e.done) c.done++;
    if (e.err) c.err = e.err;
    dayTot[e.date] = (dayTot[e.date] || 0) + e.min;
    taskTot[e.key] = (taskTot[e.key] || 0) + e.min;
  });
  const groups = (f) => {
    const out = [];
    days.forEach((d) => { const k = f(d), l = out[out.length - 1]; if (l && l.k === k) l.n++; else out.push({ k, n: 1 }); });
    return out;
  };
  const monthName = (k) => new Date(+k.slice(0, 4), +k.slice(5, 7) - 1, 1).toLocaleString('en', { month: 'short' });
  const head =
    `<tr><th rowspan="3" class="stk">Task</th><th rowspan="3">Summary</th><th rowspan="3" class="num">Total</th>` +
    groups((d) => d.slice(0, 4)).map((g) => `<th class="c" colspan="${g.n}">${g.k}</th>`).join('') + '</tr>' +
    '<tr>' + groups((d) => d.slice(0, 7)).map((g) => `<th class="c" colspan="${g.n}">${monthName(g.k)}</th>`).join('') + '</tr>' +
    '<tr>' + days.map((d) => `<th class="c" title="${d}">${d.slice(8)}<small>${WD[pYmd(d).getDay()]}</small></th>`).join('') + '</tr>';
  const body = taskOrder(Object.keys(taskTot)).map((k) => {
    const tds = days.map((d) => {
      const c = cell[k]?.[d];
      if (!c) return '<td class="c"></td>';
      const cls = c.err ? 'fail' : c.done === c.n ? opts.doneCls || 'sent' : '';
      const rm = opts.rmAttr && opts.canRm && (c.done < c.n || opts.restore);
      const verb = c.done === c.n ? 'restore' : opts.rmVerb || 'remove';
      return `<td class="c has ${cls}${rm ? ' rm' : ''}"${rm ? ` ${opts.rmAttr}="${esc(k)}|${d}"` : ''} title="${esc(c.t.join(', ') + (c.err ? ' — ' + c.err : '') + (rm ? ` (click to ${verb})` : ''))}">${fmtD(c.min)}</td>`;
    }).join('');
    return `<tr><td class="stk">${link(k)}</td><td class="sum" title="${esc(sum(k))}">${esc(sum(k))}</td><td class="num">${fmtD(taskTot[k])}</td>${tds}</tr>`;
  }).join('');
  const dayLeft = {};
  entries.forEach((e) => { if (!e.done) dayLeft[e.date] = true; });
  const foot = `<tr><td class="stk">Total</td><td></td><td class="num">${fmtD(entries.reduce((a, e) => a + e.min, 0))}</td>` +
    days.map((d) => {
      const rm = opts.dayAttr && opts.canRm && dayLeft[d];
      return `<td class="c${rm ? ' rm' : ''}"${rm ? ` ${opts.dayAttr}="${d}" title="click to ${opts.rmVerb || 'remove'} all entries of the day"` : ''}>${dayTot[d] ? fmtD(dayTot[d]) : ''}</td>`;
    }).join('') + '</tr>';
  return `<div class="pscroll" style="overflow:auto"><table class="ptable"><thead>${head}</thead><tbody>${body}</tbody><tfoot>${foot}</tfoot></table></div>`;
}

function renderPreview() {
  const box = $('#p-box');
  if (!P) { box.innerHTML = '<p class="hint">Calculate the distribution on the Tasks tab first.</p>'; return; }
  const oldScroll = box.querySelector('.pscroll');
  const sx = oldScroll ? oldScroll.scrollLeft : 0, sy = oldScroll ? oldScroll.scrollTop : 0;
  const byDay = {};
  P.entries.forEach((e) => (byDay[e.date] ??= []).push(e));
  const total = P.entries.reduce((a, e) => a + e.min, 0);
  const sent = P.entries.filter((e) => e.done).length;
  const per = {};
  P.entries.forEach((e) => { per[e.key] = (per[e.key] || 0) + e.min; });
  const tb = P.trackedBy;
  const trackedTot = tb ? Object.values(tb).reduce((a, m) => a + m, 0) : 0;
  const sumRows = Object.entries(per).map(([k, m]) => `<tr><td>${link(k)}</td><td>${esc(sumOf(k))}</td><td>${esc((P.ranges || {})[k] || '')}</td><td class="num">${fmtD(m)}</td>` +
    (tb ? `<td class="num">${tb[k] ? '+ ' + fmtD(tb[k]) + ' already tracked' : ''}</td>` : '') + '</tr>').join('');
  const days = Object.keys(byDay).sort().map((d) => {
    const es = byDay[d].sort((a, b) => a.start - b.start);
    const rows = es.map((e) => `<tr class="${e.done ? 'done' : ''}"><td class="t">${fmtT(e.start)}–${fmtT(e.start + e.min)}</td><td class="k">${link(e.key)}</td><td class="sum"><div title="${esc(sumOf(e.key))}">${esc(sumOf(e.key))}</div></td>` +
      `<td class="num" style="width:70px">${fmtD(e.min)}</td><td class="num st">${e.done ? '<span class="okc">sent</span>' : e.err ? `<span class="err" title="${esc(e.err)}">error: ${esc(e.err)}</span>` : `<button class="btn" data-rm="${e.id}" title="remove entry" ${busy ? 'disabled' : ''}>×</button>`}</td></tr>`).join('');
    return `<h3>${d} ${WD[pYmd(d).getDay()]}<small>${fmtD(es.reduce((a, e) => a + e.min, 0))}</small></h3><table class="ltable">${rows}</table>`;
  }).join('');
  box.innerHTML =
    (P.warnings.length ? `<ul class="warn">${P.warnings.map((w) => `<li>${esc(w)}</li>`).join('')}</ul>` : '') +
    `<div class="stat">Entries: <b>${P.entries.length}</b> · total: <b>${fmtD(total)}</b> · sent: <b>${sent}</b>${tb ? ` · already tracked in Jira: <b>${fmtD(trackedTot)}</b>` : ''}</div>` +
    `<div class="row"><button class="btn pri" id="p-send" ${busy ? 'disabled' : ''}>Approve and send to Jira</button>` +
    (busy ? '<button class="btn danger" id="p-stop">Stop</button>' : '') +
    `<button class="btn" id="p-recalc" ${busy ? 'disabled' : ''}>Recalculate</button><span id="p-status"></span>` +
    `<span class="views"><button data-view="table" class="${pView === 'table' ? 'on' : ''}">Table</button><button data-view="list" class="${pView === 'list' ? 'on' : ''}">List</button></span></div>` +
    (pView === 'table' ? entriesTable(P.entries, P.days, { rmAttr: 'data-rmcell', canRm: !busy }) : `<h3>By task</h3><table>${sumRows}</table>` + days);
  const ns = box.querySelector('.pscroll');
  if (ns) { ns.scrollLeft = sx; ns.scrollTop = sy; }
}

$('#p-box').addEventListener('click', (e) => {
  const rm = e.target.closest('[data-rm]');
  if (rm) { if (!busy) { P.entries = P.entries.filter((x) => x.id !== +rm.dataset.rm); renderPreview(); } return; }
  const rc = e.target.closest('[data-rmcell]');
  if (rc) {
    if (busy) return;
    const [k, d] = rc.dataset.rmcell.split('|');
    P.entries = P.entries.filter((x) => !(x.key === k && x.date === d && !x.done));
    renderPreview();
    return;
  }
  const vw = e.target.closest('[data-view]');
  if (vw) { pView = vw.dataset.view; renderPreview(); return; }
  if (e.target.id === 'p-send') send();
  if (e.target.id === 'p-stop') { pStop = true; setStatus($('#p-status'), 'Stopping after the current request...'); }
  if (e.target.id === 'p-recalc') $('#s-calc').onclick();
});

async function send() {
  if (busy) return;
  const todo = P.entries.filter((e) => !e.done);
  if (!todo.length) return alert('All entries have already been sent.');
  const sum = todo.reduce((a, e) => a + e.min, 0);
  if (!confirm(`Send ${todo.length} worklogs (${fmtD(sum)}) to Jira?`)) return;
  busy = true;
  pStop = false;
  renderPreview();
  let ok = 0, fail = 0, i = 0;
  for (const e of todo) {
    if (pStop) break;
    i++;
    const st = $('#p-status');
    if (st) setStatus(st, `Sending ${i}/${todo.length}...`, 'busy');
    try {
      await jira('POST', `/rest/api/3/issue/${encodeURIComponent(e.key)}/worklog?adjustEstimate=leave`, { started: jiraStarted(e.date, e.start), timeSpentSeconds: e.min * 60 });
      e.done = true; e.err = ''; ok++;
    } catch (x) {
      e.err = x.message; fail++;
      if (x.status === 401 || x.status === 0) break;
    } finally {
      renderPreview();
    }
  }
  busy = false;
  if (ok) trackedCache = null;
  renderPreview();
  setStatus($('#p-status'), `${pStop ? 'Stopped. ' : ''}Sent: ${ok}, failed: ${fail}${ok + fail < todo.length || fail ? ' — click "Approve" again to send the remaining/failed ones' : ''}`, fail ? 'err' : 'okc');
}

$('#quit').onclick = async () => {
  if (!confirm('Stop the app? The local server will shut down.')) return;
  try { await fetch('/api/shutdown', { method: 'POST', headers: { 'X-Track-Token': TRACK_TOKEN } }); } catch (e) {}
  document.body.innerHTML = '<p style="padding:40px;text-align:center">The app has been stopped. You can close this tab.</p>';
};

// ---------- 4. review ----------
let xView = 'table';

// Search progress or error, kept here so the search goes on (and shows) after switching tabs: { text, cls } or null.
let xSearch = null;

function renderClear() {
  const box = $('#x-box');
  if (!found) { box.innerHTML = xSearch ? `<p class="${xSearch.cls}">${esc(xSearch.text)}</p>` : ''; return; }
  const oldScroll = box.querySelector('.pscroll');
  const sx = oldScroll ? oldScroll.scrollLeft : 0, sy = oldScroll ? oldScroll.scrollTop : 0;
  const total = found.items.reduce((a, w) => a + w.min, 0);
  const deleted = found.items.filter((w) => w.deleted).length;
  const xst = found.status;
  const rows = found.items.map((w) => `<tr class="${w.deleted ? 'done' : ''}"><td>${w.date}</td><td>${fmtT(w.start)}–${fmtT(w.start + w.min)}</td><td>${link(w.key)}</td><td>${esc(w.summary)}</td><td class="num">${fmtD(w.min)}</td>` +
    `<td class="num">${w.err ? `<span class="err" title="${esc(w.err)}">error: ${esc(w.err)}</span> ` : ''}${w.deleted ? '<span class="err">deleted</span> ' : ''}` +
    `<button class="btn" data-xdel="${esc(w.id)}" title="${w.deleted ? 'restore' : 'delete'} this worklog" ${xBusy ? 'disabled' : ''}>${w.deleted ? '↺' : '×'}</button></td></tr>`).join('');
  box.innerHTML = `<div class="stat">Found: <b>${found.items.length}</b> · total: <b>${fmtD(total)}</b> · deleted: <b>${deleted}</b></div>` +
    (found.items.length ? '<div class="row" style="align-items:center">' +
      // Delete all found shows the progress and the result of deleting/restoring in place of its label;
      // while it runs, the same button stops it.
      `<button class="btn danger" id="x-del" title="${esc(xBusy ? 'Click to stop' : (xst && xst.title) || '')}"${!xBusy && deleted === found.items.length ? ' disabled' : ''}>` +
      (xst ? `<span class="${xst.cls === 'busy' ? 'busy' : ''}">${esc(xst.text)}</span>` : 'Delete all found') + '</button>' +
      (xBusy && !xStop ? '<span class="hint" style="margin:0">Click the button again to stop</span>' : '') +
      `<span class="views"><button data-xview="table" class="${xView === 'table' ? 'on' : ''}">Table</button><button data-xview="list" class="${xView === 'list' ? 'on' : ''}">List</button></span></div>` : '') +
    (!found.items.length ? '' : xView === 'table' ? clearTable() :
      `<table class="ctable"><colgroup><col style="width:110px"><col style="width:110px"><col style="width:130px"><col><col style="width:90px"><col style="width:200px"></colgroup>${rows}</table>`);
  const ns = box.querySelector('.pscroll');
  if (ns) { ns.scrollLeft = sx; ns.scrollTop = sy; }
}

// Click a cell to delete its worklogs (again to restore them), click a day total to delete the whole day (asks first).
function clearTable() {
  const days = [...new Set([...workDays(found.from, found.to), ...found.items.map((w) => w.date)])].sort();
  const sums = Object.fromEntries(found.items.map((w) => [w.key, w.summary]));
  const entries = found.items.map((w) => ({ key: w.key, date: w.date, start: w.start, min: w.min, done: w.deleted, err: w.err }));
  return entriesTable(entries, days, { rmAttr: 'data-xcell', dayAttr: 'data-xday', canRm: !xBusy, rmVerb: 'delete', restore: true, doneCls: 'gone', sum: (k) => sums[k] });
}

$('#x-find').onclick = async () => {
  if (xBusy) return;
  const { from, to } = S.clear;
  if (!from || !to || from > to) return alert('Invalid period');
  xBusy = true;
  found = null;
  xSearch = { text: 'Searching...', cls: 'hint busy' };
  renderClear();
  try {
    const items = await findMyWorklogs(from, to, (n, total, key) => { xSearch.text = `Issue ${n}/${total}: ${key}`; renderClear(); });
    found = { items, from, to };
    xSearch = null;
  } catch (e) {
    xSearch = { text: e.message, cls: 'err' };
  }
  xBusy = false;
  renderClear();
};

// Deletes the worklogs one by one, or restores deleted ones (re-created with the same start, duration and comment).
// The Stop button of this tab interrupts it.
async function runWorklogs(todo, restore) {
  const n = todo.length;
  xBusy = true;
  xStop = false;
  let ok = 0, fail = 0, lastErr = '';
  for (const w of todo) {
    if (xStop) break;
    if (!xStop) found.status = { text: `${restore ? 'Restoring' : 'Deleting'} ${ok + fail + 1}/${n}...`, cls: 'busy' };
    renderClear();
    try {
      if (restore) {
        const body = { started: w.started, timeSpentSeconds: w.sec };
        if (w.comment) body.comment = w.comment;
        const r = await jira('POST', `/rest/api/3/issue/${encodeURIComponent(w.key)}/worklog?adjustEstimate=leave`, body);
        w.id = r.id; w.deleted = false;
      } else {
        await jira('DELETE', `/rest/api/3/issue/${encodeURIComponent(w.key)}/worklog/${w.id}?adjustEstimate=leave`);
        w.deleted = true;
      }
      w.err = '';
      ok++;
    } catch (x) {
      w.err = x.message;
      fail++; lastErr = x.message;
      if (x.status === 401 || x.status === 0) break;
    }
  }
  xBusy = false;
  if (ok) trackedCache = null;
  // A short result for the button (the full error is in its tooltip and in the failed rows), back to the label after a while.
  const res = found.status = { text: `${restore ? 'Restored' : 'Deleted'} ${ok}/${n}${fail ? `, failed ${fail}` : ''}`, cls: fail ? 'err' : 'okc', title: (xStop ? 'Stopped. ' : '') + lastErr };
  setTimeout(() => { if (found && found.status === res) { found.status = null; renderClear(); } }, 4000);
  renderClear();
}

$('#x-box').addEventListener('click', async (e) => {
  if (e.target.closest('#x-del')) return xBusy ? stopWorklogs() : deleteAllFound();
  const vw = e.target.closest('[data-xview]');
  if (vw) { xView = vw.dataset.xview; renderClear(); return; }
  if (xBusy || !found) return;
  const left = (f) => found.items.filter((w) => !w.deleted && f(w));
  // A worklog or a cell is deleted on the first click and restored on the next one.
  const toggle = (f) => {
    const todo = left(f);
    if (todo.length) return runWorklogs(todo, false);
    const gone = found.items.filter((w) => w.deleted && f(w));
    if (gone.length) runWorklogs(gone, true);
  };
  const one = e.target.closest('[data-xdel]');
  if (one) { toggle((w) => String(w.id) === one.dataset.xdel); return; }
  const xc = e.target.closest('[data-xcell]');
  if (xc) {
    const [k, d] = xc.dataset.xcell.split('|');
    toggle((w) => w.key === k && w.date === d);
    return;
  }
  const xd = e.target.closest('[data-xday]');
  if (xd) {
    const todo = left((w) => w.date === xd.dataset.xday);
    if (todo.length && confirm(`Delete ${todo.length} of your worklogs for ${xd.dataset.xday} (${fmtD(todo.reduce((a, w) => a + w.min, 0))})?`)) runWorklogs(todo, false);
  }
});

function stopWorklogs() {
  if (!xBusy || !found) return;
  xStop = true;
  found.status = { text: 'Stopping...', cls: 'busy' };
  renderClear();
}

function deleteAllFound() {
  if (xBusy || !found) return;
  const todo = found.items.filter((w) => !w.deleted);
  if (!todo.length) return;
  if (!confirm(`Delete ${todo.length} of your worklogs for ${found.from} — ${found.to}?`)) return;
  runWorklogs(todo, false);
}

(async () => {
  await loadConfig();
  fillConn();
  renderStatusOptions();
  localStorage.setItem(LS, JSON.stringify(S));
  show(cfgOn ? 'tasks' : 'conn');
  if (cfgOn && S.conn.token && S.pinned.length) reload();
})();
</script>
</body>
</html>
'''

if __name__ == '__main__':
    main()
