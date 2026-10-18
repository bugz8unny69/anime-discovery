#!/usr/bin/env python3
"""Local-only dashboard for Anime-Trial; no qBittorrent operations."""
import base64, hmac, html, json, os, secrets, subprocess, sys, threading, sqlite3, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from library_watch import LibraryWatcher
import anime_dashboard_auth as auth
from anime_config_runtime import get as config_get, data_path
from http.cookies import SimpleCookie

ROOT=Path('/mnt/media/Anime-Trial')
STATE=data_path('dashboard-decisions.json')
INBOX=data_path('inbox.db')
TOKEN=os.environ.get('ANIME_DASHBOARD_PASSWORD','')
BIND=config_get('dashboard.bind_host')
PORT=config_get('dashboard.bind_port')
SYNC=Path(__file__).with_name('anime_library_sync.py')
LOCK=threading.RLock()
WATCHER=None
LOGIN_FAILURES={}
CSRF=secrets.token_urlsafe(32)
REVIEW_STATE=data_path('review-resolutions.json')
IDENTITY_STATE=data_path('identity-mappings.json')
PUBLIC_URL=(config_get('dashboard.public_url') or '').strip().rstrip('/')
def allowed_origin(origin):
    if not origin:return True
    parsed=urlsplit(origin)
    if parsed.scheme not in ('http','https') or not parsed.netloc or parsed.username or parsed.password or parsed.path not in ('','/') or parsed.query or parsed.fragment:return False
    allowed={'http://127.0.0.1:'+str(PORT),'http://localhost:'+str(PORT)}
    if PUBLIC_URL:
        public=urlsplit(PUBLIC_URL)
        if public.scheme!='https' or not public.netloc or public.username or public.password or public.path not in ('','/') or public.query or public.fragment:
            return False
        allowed.add(public.scheme+'://'+public.netloc)
    return origin.rstrip('/') in allowed

def login_csrf_token():
    # Stateless signed token, bound to the configured auth secret.
    stamp=str(int(time.time()))
    nonce=secrets.token_hex(16)
    payload=stamp+'.'+nonce
    key=bytes.fromhex(auth.read()['session_secret'])
    signature=hmac.new(key, payload.encode(), 'sha256').hexdigest()
    return payload+'.'+signature

def valid_login_csrf(token):
    try:
        stamp,nonce,signature=token.split('.')
        if not stamp.isascii() or not stamp.isdecimal() or len(nonce)!=32 or len(signature)!=64:return False
        if abs(time.time()-int(stamp))>900:return False
        key=bytes.fromhex(auth.read()['session_secret'])
        expected=hmac.new(key,(stamp+'.'+nonce).encode(),'sha256').hexdigest()
        return hmac.compare_digest(expected,signature)
    except (ValueError,TypeError,KeyError,AttributeError):return False

def esc(x): return html.escape(str(x),quote=True)
def load():
    try: return json.loads(STATE.read_text())
    except FileNotFoundError: return {}
def save(data):
    STATE.parent.mkdir(parents=True,exist_ok=True)
    tmp=STATE.with_name(STATE.name+'.tmp')
    with tmp.open('w') as f:
        json.dump(data,f,indent=2); f.flush(); os.fsync(f.fileno())
    os.chmod(tmp,0o600); os.replace(tmp,STATE)
def shows():
    if not ROOT.is_dir() or ROOT.is_symlink(): return []
    return sorted(p.name for p in ROOT.iterdir() if p.is_dir() and not p.is_symlink())
def inbox_releases(limit=40):
    """Read-only snapshot of Autobrr notifications; never modifies inbox state."""
    if not INBOX.is_file():
        return [], 'Discovery inbox database not found'
    try:
        uri = 'file:' + str(INBOX) + '?mode=ro'
        with sqlite3.connect(uri, uri=True, timeout=3) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute(
                'SELECT id, source, release_name, info_hash, status, received_at '
                'FROM notifications ORDER BY id DESC LIMIT ?', (limit,)
            ).fetchall()
        releases=[dict(row) for row in rows]
        with sqlite3.connect(uri, uri=True, timeout=3) as evidence_db:
            exists=evidence_db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='discovery_review_evidence'").fetchone()
            if exists:
                evidence={r[0]:(r[1],r[2]) for r in evidence_db.execute('SELECT notification_id,info_hash,reason FROM discovery_review_evidence')}
                for release in releases:
                    saved=evidence.get(release['id'])
                    release['review_reason']=saved[1] if saved and saved[0]==release['info_hash'] else None
        return releases, None
    except (sqlite3.Error, OSError) as exc:
        return [], 'Unable to read discovery inbox: ' + type(exc).__name__

def v20_rejected_history():
    """Read-only, fail-closed history of the explicitly scoped Episode 2 pilot."""
    path=Path('/var/lib/anime-discovery/v18-episode2-trial.db')
    if not path.is_file() or path.is_symlink(): return []
    try:
        with sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True,timeout=3) as db:
            rows=db.execute("SELECT at,action,torrent_hash FROM trial_events WHERE torrent_hash=? ORDER BY id DESC LIMIT 100",('175d53091888f5cd7e04f1bc6458034f0018e787',)).fetchall()
        if not rows: return []
        return [{'at':at,'action':action,'hash':torrent_hash,'name':'Solo Leveling S01E02','release':'[MiniDual ] S01E02-If I Had One More Chance (Dual).mkv'} for at,action,torrent_hash in rows]
    except (sqlite3.Error,OSError): return []

def review_resolutions():
    try:
        data=json.loads(REVIEW_STATE.read_text())
        return data if isinstance(data,dict) else {}
    except (FileNotFoundError,ValueError):return {}

def save_review_resolutions(data):
    REVIEW_STATE.parent.mkdir(parents=True,exist_ok=True)
    tmp=REVIEW_STATE.with_name(REVIEW_STATE.name+'.tmp')
    with tmp.open('w') as f:
        json.dump(data,f,indent=2);f.flush();os.fsync(f.fileno())
    os.chmod(tmp,0o600);os.replace(tmp,REVIEW_STATE)

def review_items():
    releases,error=inbox_releases(10000)
    if error:return [],error
    resolved=review_resolutions()
    return [r for r in releases if str(r['status']).upper().replace(' ','_')=='NEEDS_REVIEW' and str(r['id']) not in resolved],None

def run(*args):
    p=subprocess.run([sys.executable,str(SYNC),*args],capture_output=True,text=True,timeout=90,env=os.environ.copy())
    return p.returncode,(p.stdout+'\n'+p.stderr).strip()
# UI labels only: never change the raw inbox status or authorize acquisition.
STATUS_LABELS = {
    'UNTRUSTED': ('NEW', 'Discovered by Autobrr. Not yet evaluated or approved; no download starts from this inbox.'),
    'NEW': ('NEW', 'Discovered by Autobrr. Awaiting automated checks; no download has started.'),
    'ELIGIBLE': ('CHECKING', 'Passed initial eligibility checks. This label does not mean a download has started.'),
    'REVIEWING': ('CHECKING', 'The application is checking release details and trial rules.'),
    'DOWNLOADING': ('DOWNLOADING', 'A trial download is in progress.'),
    'STAGED': ('READY TO WATCH', 'Episode added to the Jellyfin trial library after media verification.'),
    'BLOCKED': ('NEEDS REVIEW', 'Processing was stopped by a rule or unresolved check. It may need attention; not necessarily a failure.'),
    'NEEDS_REVIEW': ('NEEDS REVIEW', 'This release needs your attention. Open the Needs Review queue to see it.'),
    'FAILED': ('FAILED', 'Processing failed. Check application logs for the reason.'),
}

def status_badge(raw):
    label, explanation = STATUS_LABELS.get(str(raw).upper(), (str(raw or 'UNKNOWN').upper(), 'Backend status: ' + str(raw or 'unknown') + '. No action is implied.'))
    return '<span class="status" title="' + esc(explanation) + '" aria-label="' + esc(label + ': ' + explanation) + '" tabindex="0">' + esc(label) + ' <span aria-hidden="true">ⓘ</span></span>'

def page(message='', selected=None, confirm=False, requested_item=''):
    with LOCK: decisions=load()
    names=sorted(set(shows())|set(decisions))
    selected=selected or []
    cards=''.join(f'''<article class="show-card" data-decision="{esc('kept' if decisions.get(name,'').upper()=='KEEP' else 'rejected' if decisions.get(name,'').upper()=='REJECT' else 'undecided')}"><label class="pick"><input type="checkbox" name="selected" value="{esc(name)}" form="bulk" {'checked' if name in selected else ''}><span>Select</span></label><h2>{esc(name)}</h2><p>Decision: <b>{esc(decisions.get(name,'Undecided'))}</b></p>
    <form method="post"><input type="hidden" name="csrf" value="{CSRF}"><input type="hidden" name="show" value="{esc(name)}">
    <button name="action" value="keep">Keep</button><button name="action" value="preview">Preview reject</button>
    <button class="danger" name="action" value="reject" onclick="return confirm('Delete Anime-Trial copies of this show?')">Reject &amp; remove trial copies</button>
    </form></article>''' for name in names)
    releases, inbox_error = inbox_releases()
    discovery_cards = ''.join(
        '<li class="discovery-row"><div class="discovery-title">' + esc(item['release_name']) + '</div>'
        '<div class="discovery-meta">Inbox #' + esc(item['id']) + ' · ' + esc(item['source'])
        + ' · ' + status_badge(item['status']) + '</div>'
        '<div class="discovery-hash">Hash: ' + esc(item['info_hash'] or 'unavailable') + '</div></li>'
        for item in releases
    )
    # Active pilot rejection is shown in the existing Rejected tab, not only audit history.
    pilot_history=v20_rejected_history()
    pilot_rejected=bool(pilot_history and pilot_history[0]['action']=='REJECTED')
    if pilot_rejected:
        cards += ('<article class="show-card" data-decision="rejected" data-search="solo leveling s01e02 minidual 175d53091888f5cd7e04f1bc6458034f0018e787">'
                  '<h2>Solo Leveling · S01E02</h2><p>Rejected trial release: [MiniDual ] S01E02-If I Had One More Chance (Dual).mkv</p>'
                  '<p>Webhook replay blocked. Restore requires the protected CLI until a privileged action broker is installed.</p>'
                  '<code>sudo /opt/anime-discovery/trial_episode2.py restore</code></article>')
    v20_history=v20_rejected_history()
    v20_latest=v20_history[0]['action'] if v20_history else None
    v20_rows=''.join('<li class="v20-row" data-search="'+esc((r['name']+' '+r['release']+' '+r['hash']+' '+r['action']).lower())+'">'+esc(r['at'])+' · '+esc(r['action'])+' · '+esc(r['name'])+' · <small>'+esc(r['hash'])+'</small></li>' for r in v20_history)
    v20_panel='<section class="dashboard-section" id="rejected-history"><h2>Rejected release history</h2><p class="section-description">Search by anime, episode, release, torrent hash, or action. Historical entries remain visible after restoration.</p><label for="v20-search">Search rejected history</label> <input id="v20-search" type="search" oninput="v20Filter()" placeholder="Solo Leveling, S01E02, hash…" style="padding:10px;background:#101725;color:white;border:1px solid #8194b2;border-radius:7px;width:min(95%,420px)"><ul id="v20-results">'+(v20_rows or '<li>No pilot rejection history yet.</li>')+'</ul><p><small>Latest trial action: '+esc(v20_latest or 'None')+'. Restore for Trial remains available through the protected CLI: sudo ./trial_episode2.py restore (only after Reject). This view does not trigger downloads.</small></p></section>'
    reviews,review_error=review_items()
    def review_card(r):
        rid=str(r['id'])
        details=(requested_item==rid)
        # Approval is a recorded selection only. It never calls a download endpoint.
        form=('<form method="post"><input type="hidden" name="csrf" value="'+CSRF+'"><input type="hidden" name="review_id" value="'+esc(rid)+'">'
              '<button name="action" value="review_skip" onclick="return confirm(\'Dismiss this release from review?\')">Skip this release</button></form>')
        form+=('<button type="button" class="review-open" onclick="openReview('+esc(rid)+')">Review</button>')
        form+=('<dialog id="review-modal-'+esc(rid)+'" aria-labelledby="review-title-'+esc(rid)+'">'
               '<h3 id="review-title-'+esc(rid)+'">Review Anime Identity</h3>'
               '<p><strong>Release:</strong> '+esc(r['release_name'])+'</p>'
               '<p><small>Source: '+esc(r['source'])+' · Inbox #'+esc(rid)+' · Hash: '+esc(r['info_hash'] or 'unavailable')+'</small></p>'
               '<p>Enter the AniDB anime ID and TVDB <strong>series</strong> ID for this release. '
               'These IDs are saved as an unverified identity suggestion. They are not authorized for automatic downloads, Sonarr, or Shoko until a future identity verifier confirms the match.</p>'
               '<form method="post" class="identity-form">'
               '<input type="hidden" name="csrf" value="'+CSRF+'">'
               '<input type="hidden" name="review_id" value="'+esc(rid)+'">'
               '<input type="hidden" name="confirm_hash" value="'+esc(r['info_hash'] or '')+'">'
               '<label>AniDB anime ID <input name="anidb_id" inputmode="numeric" pattern="[1-9][0-9]*" required maxlength="12" placeholder="e.g. 12345"></label>'
               '<label>TVDB series ID <input name="tvdb_id" inputmode="numeric" pattern="[1-9][0-9]*" required maxlength="12" placeholder="e.g. 123456"></label>'
               '<p><small>Check IDs at <a href="https://anidb.net" target="_blank" rel="noopener noreferrer">AniDB</a> and '
               '<a href="https://thetvdb.com" target="_blank" rel="noopener noreferrer">TheTVDB</a> before confirming.</small></p>'
               '<button name="action" value="review_identity">Save identity (no download)</button>'
               '<button type="button" onclick="closeReview('+esc(rid)+')">Cancel</button></form></dialog>')
        return '<article id="review-'+esc(rid)+'"><h3>'+esc(r['release_name'])+'</h3><p>'+status_badge(r['status'])+' · Inbox #'+esc(rid)+'</p><p><small>Review reason: '+esc(r.get('review_reason') or 'Not yet evaluated')+'</small></p>'+form+'</article>'
    review_cards=''.join(review_card(r) for r in reviews)
    confirm_form=""
    if confirm:
        hidden=''.join(f'<input type="hidden" name="selected" value="{esc(n)}">' for n in selected)
        confirm_form=f'''<article class="warning"><h2>Confirm bulk Reject</h2><p>Remove trial copies for {len(selected)} selected show(s):</p><ul>{''.join(f'<li>{esc(n)}</li>' for n in selected)}</ul><p>Original torrent files will not be modified. One Jellyfin scan will be requested after cleanup.</p><form method="post"><input type="hidden" name="csrf" value="{CSRF}">{hidden}<button class="danger" name="action" value="bulk_reject_confirm">Confirm Reject ({len(selected)})</button><a href="/">Cancel</a></form></article>'''
    return f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Anime Discovery · Trial</title>
    <style>body{{font:16px system-ui;background:#101725;color:#eaf0ff;max-width:850px;margin:35px auto;padding:0 16px}}article{{background:#1b2638;border:1px solid #39475e;border-radius:12px;padding:18px;margin:14px 0}}button{{padding:10px 14px;margin:5px 6px 5px 0;border:0;border-radius:8px;cursor:pointer}}.danger{{background:#ef9b9b}}pre{{white-space:pre-wrap;background:#243146;padding:14px;border-radius:8px}}small{{color:#afc1d9}}.pick{{display:none;float:right;cursor:pointer}}body.selecting .pick{{display:block}}.warning{{border-color:#ef9b9b}}a{{color:#b8d6ff;margin:12px}}#bulk-controls{{display:none}}body.selecting #bulk-controls{{display:block}}button:disabled{{opacity:.5}}.tabs{{display:flex;gap:8px;flex-wrap:wrap;margin:18px 0}}.tab{{background:#26364e;color:#eaf0ff}}.tab.active{{background:#b8d6ff;color:#101725;font-weight:700}}.show-card[hidden]{{display:none}}.status{{display:inline-block;padding:3px 8px;border:1px solid #8092ad;border-radius:6px;color:#eaf0ff;cursor:help}}.status:focus{{outline:2px solid #b8d6ff;outline-offset:2px}}
    .dashboard-section{{margin:30px 0 0;padding-top:20px;border-top:2px solid #425571}}.dashboard-section>h2{{margin:0 0 8px;font-size:1.4rem}}.section-description{{margin:0 0 16px;color:#afc1d9}}.discovery-list{{list-style:none;margin:0;padding:0;border:1px solid #39475e;border-radius:12px;overflow:hidden;background:#1b2638}}.discovery-row{{padding:13px 16px;border-bottom:1px solid #39475e}}.discovery-row:last-child{{border-bottom:0}}.discovery-title{{font-weight:650;line-height:1.45;overflow-wrap:anywhere}}.discovery-meta{{margin-top:8px;color:#afc1d9;font-size:.83rem}}.discovery-hash{{margin-top:5px;color:#93a6c0;font-size:.76rem;overflow-wrap:anywhere}}.system-panel{{background:#1b2638;border:1px solid #39475e;border-radius:12px;padding:16px;margin-top:12px}}.system-panel h3{{margin:0 0 8px;font-size:1rem}}.system-panel p{{margin:0}}
    dialog{{background:#1b2638;color:#eaf0ff;border:1px solid #7b92b3;border-radius:14px;max-width:min(620px,90vw);max-height:85vh;overflow:auto;padding:24px}}dialog::backdrop{{background:rgba(0,0,0,.78)}}.identity-form label{{display:block;margin:14px 0}}.identity-form input{{display:block;margin-top:6px;padding:10px;background:#101725;color:white;border:1px solid #8194b2;border-radius:7px;width:min(95%,320px)}}.review-open{{background:#b8d6ff;color:#101725;font-weight:700}}
    </style></head><body><form method="post" action="/logout" style="float:right"><input type="hidden" name="csrf" value="{CSRF}"><button type="submit">Log out</button></form><h1>Anime Discovery · Trial</h1><p><small>Local-only · Torrent originals are never modified</small></p>
    <section class="dashboard-section" id="my-anime"><h2>My Anime</h2><p class="section-description">Manage shows you are trying, keeping, or rejecting.</p>
    <nav class="tabs" aria-label="Show status"><button type="button" class="tab active" data-tab="undecided" onclick="setTab('undecided')">Undecided (<span id="count-undecided">0</span>)</button><button type="button" class="tab" data-tab="kept" onclick="setTab('kept')">Kept (<span id="count-kept">0</span>)</button><button type="button" class="tab" data-tab="rejected" onclick="setTab('rejected')">Rejected (<span id="count-rejected">0</span>)</button></nav>
    <label for="show-search">Search shows / rejected releases</label> <input id="show-search" type="search" placeholder="Anime, episode, release or hash" oninput="filterShows()" style="padding:10px;background:#101725;color:white;border:1px solid #8194b2;border-radius:7px;width:min(95%,420px)">
    <button type="button" id="toggle" onclick="document.body.classList.toggle('selecting');this.textContent=document.body.classList.contains('selecting')?'Cancel selection':'Select mode'">Select mode</button>
    {('<pre>'+esc(message)+'</pre>') if message else ''}{confirm_form}
    <form id="bulk" method="post"><input type="hidden" name="csrf" value="{CSRF}"></form>
    <div id="bulk-controls"><button type="button" onclick="document.querySelectorAll('.show-card:not([hidden]) .pick input').forEach(x=>x.checked=true)">Select all</button><button type="button" onclick="document.querySelectorAll('.pick input').forEach(x=>x.checked=false)">Clear</button><button form="bulk" name="action" value="bulk_keep">Keep selected</button><button class="danger" form="bulk" name="action" value="bulk_reject_preview">Reject selected…</button></div>
    {cards or '<p>No trial shows yet.</p>'}
    <p id="empty-tab" hidden>No shows in this tab.</p></section>
    <script>
    function openReview(id) {{ document.getElementById('review-modal-'+id).showModal(); }}
    function closeReview(id) {{ document.getElementById('review-modal-'+id).close(); }}
    let currentTab='undecided';
    function filterShows() {{
      const q=document.getElementById('show-search').value.toLowerCase().trim();
      document.querySelectorAll('.show-card').forEach(card => {{
        const hay=(card.dataset.search || card.textContent).toLowerCase();
        card.hidden=card.dataset.decision!==currentTab || !hay.includes(q);
        if(card.hidden)card.querySelectorAll('.pick input').forEach(input=>input.checked=false);
      }});
      document.getElementById('empty-tab').hidden=!!document.querySelector('.show-card:not([hidden])');
    }}
    function setTab(tab) {{
      currentTab=tab;
      filterShows();
      document.querySelectorAll('.tab').forEach(button => {{
        const active=button.dataset.tab===tab;
        button.classList.toggle('active',active);
        button.setAttribute('aria-pressed',String(active));
      }});
    }}
    ['undecided','kept','rejected'].forEach(tab => {{
      document.getElementById('count-' + tab).textContent = document.querySelectorAll('.show-card[data-decision="' + tab + '"]').length;
    }});
    setTab(new URLSearchParams(location.search).get('tab') === 'rejected' ? 'rejected' : 'undecided');
    if (new URLSearchParams(location.search).get('tab') === 'needs-review') {{ document.getElementById('needs-review').scrollIntoView(); }}
    const reviewItem = new URLSearchParams(location.search).get('item');
    if (reviewItem && /^[0-9]+$/.test(reviewItem) && document.getElementById('review-modal-'+reviewItem)) {{ openReview(reviewItem); }}
    </script>
    {v20_panel}
    <script>function v20Filter() {{ const q=document.getElementById('v20-search').value.toLowerCase().trim(); document.querySelectorAll('.v20-row').forEach(r=>r.hidden=!r.dataset.search.includes(q)); }}</script>
    <section class="dashboard-section" id="needs-review"><h2>Needs Review (<span id="review-count">{len(reviews)}</span>)</h2><p><small>Only explicitly flagged releases appear here. Skipping dismisses the review and stops reminders; it does not reject the anime or change any torrent.</small></p>
    {('<p>'+esc(review_error)+'</p>') if review_error else (review_cards or '<p>No releases need review.</p>')}</section>
    <section class="dashboard-section" id="discoveries"><h2>Recent Discoveries</h2><p class="section-description">Read-only Autobrr inbox. Hover over or focus a status ⓘ for its meaning. NEW releases are not automatically downloaded.</p>
    {('<p>'+esc(inbox_error)+'</p>') if inbox_error else ('<ul class="discovery-list">'+discovery_cards+'</ul>' if discovery_cards else '<p>No incoming releases yet.</p>')}</section>
    <section class="dashboard-section" id="system-status"><h2>System Status</h2><p class="section-description">Jellyfin library maintenance and refresh activity.</p>
    <div class="system-panel"><h3>Automatic Jellyfin refresh</h3><p><small>{esc(WATCHER.status if WATCHER else "Not running")}</small></p></div>
    <div class="system-panel"><h3>Jellyfin library scan</h3><form method="post"><input type="hidden" name="csrf" value="{CSRF}"><button name="action" value="scan">Request library scan</button></form></div></section>
    <p><small>Keep records a dashboard decision only. Automatic episode acquisition and controller blocking after Reject are not yet connected.</small></p></body></html>'''

class Handler(BaseHTTPRequestHandler):
    def log_message(self,fmt,*args): print('dashboard request',self.address_string(),fmt % args,flush=True)
    def secure_cookie(self):
        return bool(PUBLIC_URL.startswith('https://')) or self.headers.get('X-Forwarded-Proto','').lower()=='https'
    def cookie_value(self,name):
        try:
            jar=SimpleCookie();jar.load(self.headers.get('Cookie',''))
            return jar[name].value if name in jar else ''
        except Exception:return ''
    def authorized(self):
        return auth.valid_session(self.cookie_value('anime_session'))
    def send_html(self,body,status=200,cookie=None):
        data=body.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type','text/html; charset=utf-8')
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
        if cookie:self.send_header('Set-Cookie',cookie)
        self.send_header('Content-Length',str(len(data)))
        self.end_headers();self.wfile.write(data)
    def login_page(self,message='',status=200):
        error='<p class="error">'+esc(message)+'</p>' if message else ''
        login_token=login_csrf_token()
        body=f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Anime Discovery · Sign in</title><style>
        *{{box-sizing:border-box}}body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#101725;color:#eaf0ff;font:16px system-ui,sans-serif;padding:20px}}
        main{{width:min(420px,100%);background:#1b2638;border:1px solid #39475e;border-radius:18px;padding:36px;box-shadow:0 16px 40px #0005}}
        h1{{font-size:1.6rem;margin:0 0 8px}}p{{color:#afc1d9;margin:0 0 28px}}label{{display:block;margin:18px 0 7px}}input{{display:block;width:100%;padding:13px;background:#101725;border:1px solid #8295b2;color:white;border-radius:9px;font-size:1rem}}input:focus{{outline:2px solid #b8d6ff}}button{{width:100%;background:#b8d6ff;color:#101725;border:0;border-radius:9px;padding:14px;font-weight:750;font-size:1rem;margin-top:26px;cursor:pointer}}.error{{color:#ffb9b9;margin:12px 0}}
        </style></head><body><main><h1>🎬 Anime Discovery</h1><p>Sign in to manage your anime library</p>{error}<form method="post" action="/login"><input type="hidden" name="login_csrf" value="{login_token}"><label for="username">Username</label><input id="username" name="username" value="admin" autocomplete="username" required autofocus><label for="password">Password</label><input id="password" name="password" type="password" autocomplete="current-password" required><button type="submit">Sign in</button></form></main></body></html>''' 
        self.send_html(body,status,cookie=self.login_csrf_cookie(login_token))
    def login_csrf_cookie(self,value):
        secure='; Secure' if self.secure_cookie() else ''
        return f'anime_login_csrf={value}; Path=/login; HttpOnly; SameSite=Strict; Max-Age=900'+secure
    def redirect(self,location,cookie=None):
        self.send_response(303);self.send_header('Location',location)
        self.send_header('Cache-Control','no-store')
        if cookie:self.send_header('Set-Cookie',cookie)
        self.send_header('Content-Length','0');self.end_headers()
    def session_cookie(self,value,max_age):
        secure='; Secure' if self.secure_cookie() else ''
        return f'anime_session={value}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}'+secure
    def respond(self,msg='',status=200,selected=None,confirm=False):
        requested=parse_qs(urlsplit(self.path).query).get('item',[''])[0]
        data=page(msg,selected,confirm,requested_item=requested).encode()
        self.send_response(status);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Security-Policy',"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'");self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    def do_GET(self):
        route=urlsplit(self.path).path
        if route=='/login':
            if self.authorized():self.redirect('/');return
            self.login_page();return
        if route!='/':self.send_error(404);return
        if not self.authorized():self.redirect('/login');return
        self.respond()
    def do_POST(self):
        route=urlsplit(self.path).path
        if route not in ('/','/login','/logout'):self.send_error(404);return
        origin=self.headers.get('Origin','')
        if route=='/logout' and not origin:
            self.send_error(403,'Missing Origin');return
        if origin not in ('','null') and not allowed_origin(origin):
            self.send_error(403);return
        try:
            n=int(self.headers.get('Content-Length','0'))
            if n<=0 or n>8192:raise ValueError('Invalid request size')
            fields=parse_qs(self.rfile.read(n).decode(),keep_blank_values=True)
            one=lambda key:fields.get(key,[''])[0]
            if route=='/login':
                form_token=one('login_csrf')
                if not form_token or not hmac.compare_digest(form_token,self.cookie_value('anime_login_csrf')) or not valid_login_csrf(form_token):
                    self.send_error(403,'Invalid login form token');return
                # Rate limit by direct peer (Nginx); intentionally ignore spoofable forwarding headers.
                peer=self.client_address[0]
                with LOCK:
                    failures=[t for t in LOGIN_FAILURES.get(peer,[]) if time.monotonic()-t<900]
                    LOGIN_FAILURES[peer]=failures
                    blocked=len(failures)>=5
                if blocked:
                    self.login_page('Too many attempts. Try again in 15 minutes.',429);return
                if not auth.verify(one('username'),one('password')):
                    with LOCK:LOGIN_FAILURES.setdefault(peer,[]).append(time.monotonic())
                    self.login_page('Invalid username or password',401);return
                with LOCK:LOGIN_FAILURES.pop(peer,None)
                self.redirect('/',self.session_cookie(auth.session_token(),7*86400));return
            if not self.authorized():self.redirect('/login');return
            if route=='/logout':
                if not hmac.compare_digest(one('csrf'),CSRF):raise ValueError('Invalid form token')
                self.redirect('/login',self.session_cookie('',0));return
            if not hmac.compare_digest(one('csrf'),CSRF):raise ValueError('Invalid form token')
            action,show=one('action'),one('show')
            if action=='review_identity':
                review_id=one('review_id'); confirm_hash=one('confirm_hash')
                anidb_id=one('anidb_id').strip();tvdb_id=one('tvdb_id').strip()
                if not review_id.isdecimal():raise ValueError('Invalid review ID')
                if any(not x.isascii() or not x.isdecimal() or x.startswith('0') or len(x)>12 for x in (anidb_id,tvdb_id)):
                    raise ValueError('Both IDs must be positive numeric IDs (up to 12 digits)')
                with LOCK:
                    items,error=inbox_releases(10000)
                    if error:raise ValueError('Review inbox unavailable')
                    row=next((r for r in items if str(r['id'])==review_id and str(r['status']).upper().replace(' ','_')=='NEEDS_REVIEW'),None)
                    if row is None:raise ValueError('Review is no longer active')
                    resolved=review_resolutions()
                    if review_id in resolved:raise ValueError('Review already resolved')
                    if not confirm_hash or not hmac.compare_digest(str(row['info_hash'] or ''),confirm_hash):
                        raise ValueError('Release identity changed; reopen review')
                    try: mappings=json.loads(IDENTITY_STATE.read_text())
                    except FileNotFoundError:mappings={}
                    if not isinstance(mappings,dict):raise ValueError('Identity mapping store invalid')
                    for key,entry in mappings.items():
                        if key==review_id:continue
                        if isinstance(entry,dict) and (entry.get('anidb_id')==anidb_id and entry.get('tvdb_id')!=tvdb_id or entry.get('tvdb_id')==tvdb_id and entry.get('anidb_id')!=anidb_id):
                            raise ValueError('Conflicting saved ID mapping. Review existing mappings before proceeding.')
                    mapping={'anidb_id':anidb_id,'tvdb_id':tvdb_id,'release_name':row['release_name'],
                             'source':row['source'],'info_hash':row['info_hash'],'verification':'USER_PROVIDED_UNVERIFIED','usable_for_automation':False}
                    mappings[review_id]=mapping
                    IDENTITY_STATE.parent.mkdir(parents=True,exist_ok=True)
                    tmp=IDENTITY_STATE.with_name(IDENTITY_STATE.name+'.tmp')
                    with tmp.open('w') as f:json.dump(mappings,f,indent=2);f.flush();os.fsync(f.fileno())
                    os.chmod(tmp,0o600);os.replace(tmp,IDENTITY_STATE)
                    resolved[review_id]={'decision':'IDENTITY_RECORDED','anidb_id':anidb_id,'tvdb_id':tvdb_id,
                                         'verification':'USER_PROVIDED_UNVERIFIED','usable_for_automation':False,'info_hash':row['info_hash']}
                    save_review_resolutions(resolved)
                return self.respond('AniDB and TVDB IDs saved as user-provided (not independently verified). Review reminders stop. No download, Sonarr, or Shoko action was started.')
            if action=='review_skip':
                review_id=one('review_id')
                if not review_id.isdecimal():raise ValueError('Invalid review ID')
                with LOCK:
                    items,error=inbox_releases(10000)
                    if error or not any(str(r['id'])==review_id and str(r['status']).upper().replace(' ','_')=='NEEDS_REVIEW' for r in items):
                        raise ValueError('Review is no longer active')
                    data=review_resolutions();data[review_id]='SKIPPED';save_review_resolutions(data)
                return self.respond('Review dismissed. No torrent or anime decision was changed.')
            if action.startswith('bulk_'):
                selected=list(dict.fromkeys(fields.get('selected',[])))
                known=set(shows())|set(load())
                if not selected or len(selected)>200 or any(n not in known for n in selected):
                    raise ValueError('Select between 1 and 200 known shows')
                if action=='bulk_reject_preview':
                    return self.respond('Review the selected shows before confirming removal.',selected=selected,confirm=True)
                if action=='bulk_keep':
                    with LOCK:
                        state=load()
                        for name in selected:state[name]='KEEP'
                        save(state)
                    return self.respond(f'KEEP recorded for {len(selected)} shows; automatic downloads are not yet connected.')
                if action=='bulk_reject_confirm':
                    # Serialize bulk mutation with individual requests; one scan after all removals.
                    with LOCK:
                        state=load(); results=[];removed=0
                        for name in selected:
                            code,out=run('reject','--show',name,'--confirm-show',name,'--execute','--no-scan')
                            results.append(f'{name}: '+('REMOVED' if code==0 else 'FAILED')+'\n'+out)
                            if code==0:
                                state[name]='REJECT';removed+=1;save(state)
                        if removed:
                            code,out=run('scan')
                            results.append('Jellyfin refresh: '+out)
                            if code:results.append('WARNING: Jellyfin refresh failed; retry scan from dashboard')
                        return self.respond('\n\n'.join(results),200 if removed==len(selected) else 500)
                raise ValueError('Unknown bulk action')
            if action=='scan':
                code,out=run('scan');return self.respond(out,200 if code==0 else 500)
            if show not in set(shows())|set(load()):raise ValueError('Unknown show')
            if action=='preview':
                code,out=run('reject','--show',show);return self.respond(out,200 if code==0 else 500)
            if action=='keep':
                with LOCK:
                    state=load();state[show]='KEEP';save(state)
                return self.respond('KEEP recorded for '+show+'; automatic downloads are not yet connected.')
            if action=='reject':
                code,out=run('reject','--show',show,'--confirm-show',show,'--execute')
                if code==0:
                    with LOCK:
                        state=load();state[show]='REJECT';save(state)
                return self.respond(out,200 if code==0 else 500)
            raise ValueError('Unknown action')
        except Exception as e:self.respond('STOP: '+str(e),400)

if __name__=='__main__':
    if not auth.read():
        if len(TOKEN)>=12:
            auth.set_password(TOKEN)
            print('Initialized admin password from ANIME_DASHBOARD_PASSWORD; remove env secret after confirming login',flush=True)
        else:sys.exit('Initialize with: python3 anime_dashboard_auth.py passwd (or set ANIME_DASHBOARD_PASSWORD to 12+ chars for one-time migration)')
    if BIND not in ('127.0.0.1','::1'):sys.exit('Refusing non-loopback bind; use a trusted tunnel or authenticated reverse proxy')
    def background_scan():
        code, output = run('scan')
        if code != 0 or 'SCAN_PENDING' in output:
            raise RuntimeError(output[:200] or 'scan failed')
        print('Library watcher:', output, flush=True)
    WATCHER = LibraryWatcher(ROOT, background_scan)
    WATCHER.start()
    print(f'Dashboard at http://{BIND}:{PORT}',flush=True)
    ThreadingHTTPServer((BIND,PORT),Handler).serve_forever()
