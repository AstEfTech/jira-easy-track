"""Generates media/Jira_Easy_Track.gif: walks through the app tabs against a fake Jira (no real data is used).

    pip install pillow playwright      (uses the installed Microsoft Edge)
    py media/capture.py

The steps are in scenario.py. Env: GIF_OUT (output path), FRAMES_DIR (also dump the frames as PNG),
BROWSER_CHANNEL (default msedge; empty = Playwright's bundled Chromium, used in CI).
"""
import io, json, os, re, subprocess, sys, tempfile, time, urllib.request
from playwright.sync_api import sync_playwright
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
OUT = os.environ.get('GIF_OUT') or os.path.join(HERE, 'Jira_Easy_Track.gif')
DEBUG_DIR = os.environ.get('FRAMES_DIR')
W, H = 1300, 720
PORT = 4791

# ---------- fake Jira ----------
ME = 'acc-me'
BASE = 'https://demo-team.atlassian.net'
HOUR = 3600
ISSUES = {
    'KAN-1': ('Onboarding flow redesign', 12 * HOUR, '2026-10-12', '2026-10-20'),
    'KAN-2': ('Daily standup', 0, '2026-10-01', None),
    'KAN-3': ('Fix login redirect loop', 4 * HOUR, '2026-10-13', '2026-10-15'),
    'KAN-4': ('Payment API integration', 24 * HOUR, '2026-10-14', None),
    'KAN-5': ('Release notes for v2.4', 3 * HOUR, '2026-10-21', '2026-10-23'),
    'KAN-6': ('Migrate CI to GitHub Actions', 10 * HOUR, '2026-09-01', '2026-09-30'),
}
STATUSES = [('To Do', 'new'), ('In Progress', 'indeterminate'), ('In Review', 'indeterminate'), ('Blocked', 'indeterminate'), ('Done', 'done')]
FIELDS = [{'id': 'summary', 'name': 'Summary'}, {'id': 'status', 'name': 'Status'}, {'id': 'priority', 'name': 'Priority'}, {'id': 'assignee', 'name': 'Assignee'}, {'id': 'created', 'name': 'Created'}]
WL = {k: [] for k in ISSUES}
_id = [1000]


def add_wl(key, date, hhmm, minutes, who=ME):
    _id[0] += 1
    WL[key].append({'id': str(_id[0]), 'author': {'accountId': who}, 'started': f'{date}T{hhmm}:00.000+0200', 'timeSpentSeconds': minutes * 60})
    return WL[key][-1]


add_wl('KAN-1', '2026-10-14', '10:00', 120)
add_wl('KAN-1', '2026-10-15', '15:00', 90)
add_wl('KAN-4', '2026-10-19', '10:00', 180)


def issue_json(k):
    s, est, *_ = ISSUES[k]
    return {'key': k, 'fields': {'summary': s, 'created': '2026-09-20T09:00:00.000+0200', 'timeoriginalestimate': est or None}}


def changelog(k):
    _, _, a, b = ISSUES[k]
    vals = [{'created': f'{a}T09:30:00.000+0200', 'items': [{'field': 'status', 'fromString': 'To Do', 'toString': 'In Progress'}]}]
    if b:
        vals.append({'created': f'{b}T17:10:00.000+0200', 'items': [{'field': 'status', 'fromString': 'In Progress', 'toString': 'Done'}]})
    return {'values': vals, 'isLast': True, 'total': len(vals)}


def jira(method, path, body):
    p = path.split('?')[0]
    q = dict(re.findall(r'[?&](\w+)=([^&]*)', path))
    if p == '/rest/api/3/myself':
        return 200, {'accountId': ME, 'displayName': 'Alex Morgan', 'emailAddress': 'alex.morgan@example.com'}
    if p == '/rest/api/3/status':
        return 200, [{'name': n, 'statusCategory': {'key': c}} for n, c in STATUSES]
    if p == '/rest/api/3/field':
        return 200, FIELDS
    if p == '/rest/api/3/search/jql':
        jql = body['jql']
        m = re.search(r'key in \(([^)]*)\)', jql)
        if m:
            keys = re.findall(r'"([^"]+)"', m.group(1))
        elif 'worklogAuthor' in jql:
            a, b = re.findall(r'"(\d{4}-\d\d-\d\d)"', jql)[:2]
            keys = [k for k, ws in WL.items() if any(a <= w['started'][:10] <= b and w['author']['accountId'] == ME for w in ws)]
        else:
            keys = list(ISSUES)
        return 200, {'issues': [issue_json(k) for k in keys if k in ISSUES]}
    m = re.match(r'/rest/api/3/issue/([\w-]+)/changelog', p)
    if m:
        return 200, changelog(m.group(1))
    m = re.match(r'/rest/api/3/issue/([\w-]+)/worklog(?:/(\d+))?$', p)
    if m:
        k, wid = m.groups()
        if method == 'GET':
            return 200, {'worklogs': WL[k], 'total': len(WL[k])}
        if method == 'POST':
            time.sleep(0.07)
            w = add_wl(k, body['started'][:10], body['started'][11:16], body['timeSpentSeconds'] // 60)
            return 201, w
        if method == 'DELETE':
            time.sleep(0.07)
            WL[k] = [w for w in WL[k] if w['id'] != wid]
            return 204, None
    return 404, {'errorMessages': ['not mocked: ' + path]}


def route_jira(route):
    p = json.loads(route.request.post_data)
    status, data = jira(p['method'], p['path'], p.get('body'))
    route.fulfill(status=200, content_type='application/json', body=json.dumps({'status': status, 'data': data}))


# ---------- frames ----------
frames = []  # [png bytes, ms]


def snap(page, ms=100):
    png = page.screenshot()
    if frames and frames[-1][0] == png:
        frames[-1][1] += ms
    else:
        frames.append([png, ms])


def hold(page, ms):
    snap(page, ms)


CURSOR_JS = '''
() => {
  if (document.getElementById('__cur')) return;
  const c = document.createElement('div');
  c.id = '__cur';
  c.style.cssText = 'position:fixed;left:0;top:0;width:22px;height:22px;z-index:99999;pointer-events:none;transform:translate(-100px,-100px);transition:none';
  c.innerHTML = '<svg width="22" height="22" viewBox="0 0 22 22"><path d="M3 2 L3 17 L7 13.5 L10 20 L12.5 18.8 L9.6 12.5 L15 12.5 Z" fill="#fff" stroke="#000" stroke-width="1.3" stroke-linejoin="round"/></svg>';
  document.body.appendChild(c);
  window.__cp = [-100, -100];
}
'''
pos = [600, 360]


def place(page, x, y, down=False):
    page.evaluate('([x,y,d]) => { const c = document.getElementById("__cur"); c.style.transform = `translate(${x}px,${y}px) scale(${d ? 0.82 : 1})`; }', [x, y, down])


def move(page, loc, dx=0.5, dy=0.5, steps=5, ms=45):
    loc.scroll_into_view_if_needed()
    b = loc.bounding_box()
    tx, ty = b['x'] + b['width'] * dx, b['y'] + b['height'] * dy
    sx, sy = pos
    for i in range(1, steps + 1):
        t = i / steps
        t = t * t * (3 - 2 * t)
        place(page, sx + (tx - sx) * t, sy + (ty - sy) * t)
        snap(page, ms)
    pos[:] = [tx, ty]
    page.mouse.move(tx, ty)


def click(page, loc, **kw):
    move(page, loc, **kw)
    place(page, *pos, down=True)
    snap(page, 70)
    loc.click()
    place(page, *pos)


def scroll_to(page, y, steps=6, ms=40):
    cur = page.evaluate('window.scrollY')
    for i in range(1, steps + 1):
        t = i / steps
        t = t * t * (3 - 2 * t)
        page.evaluate('y => window.scrollTo(0, y)', cur + (y - cur) * t)
        snap(page, ms)


def type_in(page, loc, text, per=60):
    click(page, loc)
    loc.press('Control+a')
    for ch in text:
        loc.press_sequentially(ch)
        snap(page, per)
    snap(page, 150)


def save_gif():
    if DEBUG_DIR:
        os.makedirs(DEBUG_DIR, exist_ok=True)
        for i, (png, ms) in enumerate(frames):
            open(os.path.join(DEBUG_DIR, f'{i:03d}_{ms}.png'), 'wb').write(png)
    imgs = [Image.open(io.BytesIO(p)).convert('RGB') for p, _ in frames]
    # one shared palette keeps colors stable between frames
    sample = Image.new('RGB', (W, H * min(len(imgs), 12)))
    for i, k in enumerate(range(0, len(imgs), max(1, len(imgs) // 12))[:12]):
        sample.paste(imgs[k], (0, i * H))
    pal = sample.quantize(colors=255, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    q = [im.quantize(palette=pal, dither=Image.Dither.NONE) for im in imgs]
    q[0].save(OUT, save_all=True, append_images=q[1:], duration=[max(20, int(ms * 0.8)) for _, ms in frames], loop=0, optimize=False, disposal=1)
    print('frames', len(frames), 'seconds', sum(ms for _, ms in frames) / 1000, 'size MB', os.path.getsize(OUT) / 1e6)


def main():
    tmp = tempfile.mkdtemp()
    cfg = os.path.join(tmp, 'cfg.json')
    json.dump({
        'conn': {'base': BASE, 'email': 'alex.morgan@example.com', 'token': 'demo-token-not-real'},
        'jql': 'assignee = currentUser() ORDER BY updated DESC', 'jqlTracked': True,
        'fields': [{'id': 'summary', 'name': 'Summary'}],
        'pinned': [{'key': 'KAN-2', 'perDay': '0:30'}],
        'workday': {'dayStart': '10:00', 'dayEnd': '19:00', 'breakStart': '13:00', 'breakEnd': '14:00', 'step': '30', 'days': [1, 2, 3, 4, 5], 'varied': True, 'useTracked': True},
        'track': {'from': 'In Progress', 'to': 'Done', 'on': True},
    }, open(cfg, 'w'))
    env = dict(os.environ, JIRA_TRACK_CONFIG=cfg, JIRA_TRACK_PORT=str(PORT))
    srv = subprocess.Popen([sys.executable, os.path.join(REPO, 'jira-track.py'), '--no-open'], env=env, stdout=subprocess.PIPE)
    try:
        for _ in range(50):
            try:
                urllib.request.urlopen(f'http://127.0.0.1:{PORT}/', timeout=1)
                break
            except Exception:
                time.sleep(0.2)
        with sync_playwright() as pw:
            br = pw.chromium.launch(channel=os.environ.get('BROWSER_CHANNEL', 'msedge') or None)
            ctx = br.new_context(viewport={'width': W, 'height': H}, color_scheme='dark', locale='en-GB', timezone_id='Europe/Warsaw')
            ctx.add_init_script("localStorage.getItem('jiraTrackNoBS.v1') || localStorage.setItem('jiraTrackNoBS.v1', JSON.stringify({sched:{from:'2026-10-12',to:'2026-10-23'}}))")
            ctx.route('**/api/jira', route_jira)
            page = ctx.new_page()
            page.on('dialog', lambda d: d.accept())
            page.goto(f'http://127.0.0.1:{PORT}/')
            page.wait_for_timeout(1500)
            page.evaluate(CURSOR_JS)
            import scenario
            scenario.run(page)
            save_gif()
            br.close()
    finally:
        srv.terminate()


if __name__ == '__main__':
    sys.path.insert(0, HERE)
    import capture  # scenario imports this module, so run it from there to share the frames list
    capture.main()
