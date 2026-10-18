#!/usr/bin/env python3
"""Minimal, reversible dashboard extension for existing pilot rejection history."""
from pathlib import Path
import shutil, time, py_compile
p=Path('/opt/anime-discovery/dashboard.py')
s=p.read_text()
if 'v20_rejected_history' in s:
    print('V20_ALREADY_INSTALLED');raise SystemExit(0)
needle='def review_resolutions():'
assert s.count(needle)==1
addition='''def v20_rejected_history():
    """Read-only, fail-closed history of the explicitly scoped Episode 2 pilot."""
    path=Path('/var/lib/anime-discovery/v18-episode2-trial.db')
    if not path.is_file() or path.is_symlink(): return []
    try:
        with sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True,timeout=3) as db:
            rows=db.execute("SELECT at,action,torrent_hash FROM trial_events WHERE torrent_hash=? ORDER BY id DESC LIMIT 100",('175d53091888f5cd7e04f1bc6458034f0018e787',)).fetchall()
        if not rows: return []
        return [{'at':at,'action':action,'hash':torrent_hash,'name':'Solo Leveling S01E02','release':'[MiniDual ] S01E02-If I Had One More Chance (Dual).mkv'} for at,action,torrent_hash in rows]
    except (sqlite3.Error,OSError): return []

'''
s=s.replace(needle,addition+needle)
needle2='    reviews,review_error=review_items()'
assert s.count(needle2)==1
addition2='''    v20_history=v20_rejected_history()
    v20_latest=v20_history[0]['action'] if v20_history else None
    v20_rows=''.join('<li class="v20-row" data-search="'+esc((r['name']+' '+r['release']+' '+r['hash']+' '+r['action']).lower())+'">'+esc(r['at'])+' · '+esc(r['action'])+' · '+esc(r['name'])+' · <small>'+esc(r['hash'])+'</small></li>' for r in v20_history)
    v20_panel='<section class="dashboard-section" id="rejected-history"><h2>Rejected release history</h2><p class="section-description">Search by anime, episode, release, torrent hash, or action. Historical entries remain visible after restoration.</p><label for="v20-search">Search rejected history</label> <input id="v20-search" type="search" oninput="v20Filter()" placeholder="Solo Leveling, S01E02, hash…" style="padding:10px;background:#101725;color:white;border:1px solid #8194b2;border-radius:7px;width:min(95%,420px)"><ul id="v20-results">'+(v20_rows or '<li>No pilot rejection history yet.</li>')+'</ul><p><small>Latest trial action: '+esc(v20_latest or 'None')+'. Restore for Trial remains available through the protected CLI: sudo ./trial_episode2.py restore (only after Reject). This view does not trigger downloads.</small></p></section>'
'''
s=s.replace(needle2,addition2+needle2)
needle3='    <section class="dashboard-section" id="needs-review">'
assert s.count(needle3)==1
s=s.replace(needle3,'''    {v20_panel}
    <script>function v20Filter() {{ const q=document.getElementById('v20-search').value.toLowerCase().trim(); document.querySelectorAll('.v20-row').forEach(r=>r.hidden=!r.dataset.search.includes(q)); }}</script>
'''+needle3)
backup=p.with_name('dashboard.py.before-v20-'+time.strftime('%Y%m%d-%H%M%S'))
shutil.copy2(p,backup)
tmp=p.with_name('dashboard.py.v20-tmp')
tmp.write_text(s)
try: py_compile.compile(str(tmp),doraise=True)
except Exception: tmp.unlink(missing_ok=True);raise
shutil.copymode(p,tmp)
tmp.replace(p)
print('V20_INSTALLED backup='+str(backup))
