"""Browser presentation for the Anime Discovery library, jobs and name mappings."""
import html
import json
from urllib.parse import urlencode


def escape(value):
    return html.escape(str(value),quote=True)


def shell(title,active):
    tabs=[("/","Series"),("/jobs","Jobs"),("/recognized","Recognized names")]
    navigation="".join('<a class="tab'+(" selected" if name==active else "")+
                       '" href="'+route+'">'+name+'</a>' for route,name in tabs)
    return """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>"""+escape(title)+""" · Anime Discovery</title>
<style>
:root{color-scheme:dark;font:16px system-ui,-apple-system,sans-serif}
*{box-sizing:border-box}
body{margin:0;background:#0d1420;color:#e8edf7}
.container{max-width:1280px;margin:auto;padding:28px 24px 80px}
header{display:flex;justify-content:space-between;align-items:center;gap:16px}
.brand{font-size:1.3rem;letter-spacing:.01em;font-weight:750}
nav{display:flex;flex-wrap:wrap;gap:8px;margin:24px 0 30px;border-bottom:1px solid #34435a}
.tab{padding:12px 19px;color:#adbed4;text-decoration:none}
.tab:hover,.tab.selected{color:#fff}
.tab.selected{border-bottom:3px solid #5fb6ff}
h1{margin:0;font-size:1.65rem}h2{font-size:1.1rem;margin:0 0 14px}
.muted{color:#a8bad1}p{line-height:1.55}small{font-size:.84rem}
.panel{background:#172335;border:1px solid #2c3e56;border-radius:14px;
margin:18px 0;padding:20px;overflow-x:auto}
.toolbar{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:14px}
.inline{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
table{width:100%;border-collapse:collapse;margin-top:14px;font-size:.94rem}
th{text-align:left;color:#a9bfd8;font-weight:600}
th,td{padding:13px 12px;border-bottom:1px solid #2b3d54}
tbody tr:hover{background:#1e3046}
a{color:#87c8ff}input,select,button{background:#24344a;color:#eff5ff;
border:1px solid #47607e;border-radius:8px;padding:10px 12px;font:inherit}
input[type=checkbox]{width:18px;height:18px;accent-color:#56b2ff}
button{background:#17629b;cursor:pointer}
button:hover{background:#227dbf}
button:disabled{opacity:.45;cursor:default}
button.secondary{background:#25364a}
.status{font-size:.78rem;font-weight:700;letter-spacing:.035em;border-radius:20px;
padding:5px 9px;display:inline-block;background:#344357}
.status.completed{background:#173f39;color:#a6f6d4}
.status.running{background:#183f6d;color:#a7d5ff}
.status.waiting{background:#604923;color:#ffe5a4}
.status.blocked{background:#572c38;color:#ffd0d7}
.page-controls{display:flex;align-items:center;justify-content:flex-end;gap:10px;flex-wrap:wrap}
.empty{padding:30px;text-align:center;color:#b8c6d9}
.forms{display:flex;flex-wrap:wrap;gap:10px;align-items:center}
input.long{min-width:220px;flex:1}
.actions{position:sticky;bottom:12px;box-shadow:0 10px 30px #0008;background:#25334a;
border:1px solid #517092;padding:14px;border-radius:12px;display:flex;
align-items:center;justify-content:space-between;gap:14px;flex-wrap:wrap}
.hidden{display:none!important}
@media(max-width:650px){.container{padding:20px 12px}th,td{padding:10px 7px}
.panel{padding:13px}.hide-mobile{display:none}}
</style></head><body><main class="container"><header>
<span class="brand">◈ Anime Discovery</span>
<span class="muted">Homelab</span></header><nav aria-label="Main navigation">"""+navigation+"</nav>"


def request_panel(mappings):
    """One-time manual discovery, no episode picker or future monitoring."""
    out='''<section class="panel"><div class="toolbar"><h2>Request anime for trial</h2>
    <button type="button" onclick="document.getElementById('request-anime').showModal()">+ Request Anime</button>
    </div><p class="muted">Choose an anime title or known TVDB/AniDB ID.
    Anime Discovery searches available episodes once, then uses the usual
    acquisition pipeline. Autobrr remains responsible for future releases.</p></section>
    <dialog id="request-anime" style="background:#172335;color:#e8edf7;border:1px solid #52708f;
    border-radius:14px;padding:24px;width:min(520px,95vw)">
    <form method="dialog" style="text-align:right"><button class="secondary">Close</button></form>
    <h2>One-time Anime-Trial request</h2><form method="post" action="/request-anime" class="forms">
    <label>Anime name<input class="long" name="title" placeholder="Known anime title (optional)"></label>
    <label>TVDB ID<input name="tvdb_id" type="number" min="1" placeholder="Optional"></label>
    <label>AniDB ID<input name="anidb_id" type="number" min="1" placeholder="Optional"></label>
    <label>Season<input name="season" type="number" min="1" max="100" value="1" required></label>
    <p class="muted">Use any known name or ID from Recognized names.
    No episode numbers or future subscription are needed.</p>
    <button>Search missing episodes once</button></form></dialog>'''
    if mappings:
        out+='<p class="muted">Recognized: '+', '.join(escape(name) for name in sorted(mappings)[:8])+'</p>'
    return out



def tail():
    return "</main></body></html>"


def pager(path,result):
    page,total,pages,size=result["page"],result["total"],result["pages"],result["page_size"]
    def href(p):
        return path+"?"+urlencode({"page":p,"size":size})
    opts="".join('<option value="'+str(n)+'"'+(" selected" if n==size else "")+'>'+str(n)+'</option>'
                 for n in (20,50,100))
    return ('<div class="page-controls"><span class="muted">'+str(total)+' total</span>'
            '<label>Rows per page <select onchange="location.href='
            "'"+path+"?page=1&size=' + this.value"+'"'
            '>'+opts+'</select></label>'
            +('<a href="'+href(page-1)+'">← Previous</a>' if page>1 else '')
            +'<span>Page '+str(page)+' of '+str(pages)+'</span>'
            +('<a href="'+href(page+1)+'">Next →</a>' if page<pages else '')
            +'</div>')


def series_page(result,mappings=None):
    out=shell("Series","Series")
    out+="""<h1>Series</h1><p class="muted">Anime with completed episodes currently
staged in Anime-Trial. Incoming releases and downloads appear under Jobs.</p>
<section class="panel"><div class="toolbar">
<div><h2>Anime-Trial library</h2><span class="muted">Select one or more series to manage.</span></div>"""
    out+=pager("/",result)+"</div>"
    out+='''<form id="bulk" method="post" action="/series-bulk"><table>
<thead><tr><th><input type="checkbox" id="select-all" aria-label="Select page"></th>
<th>Anime</th><th class="hide-mobile">TVDB</th><th>Episodes staged</th>
<th>Latest episode</th><th>Status</th></tr></thead><tbody>'''
    for item in result["items"]:
        sid=item["id"]
        out+='<tr><td><input type="checkbox" name="series_ids" value="'+str(sid)+'" class="pick" aria-label="Select '+escape(item["title"])+'"></td>'
        out+='<td><a href="/series?id='+str(sid)+'">'+escape(item["title"])+'</a></td>'
        out+='<td class="hide-mobile">'+escape(item["tvdb_id"])+'</td>'
        out+='<td>'+str(item["staged_episodes"])+'</td><td>'+escape(item["latest_episode"])+'</td>'
        out+='<td><span class="status">'+escape(item["status"])+'</span></td></tr>'
    if not result["items"]:
        out+='<tr><td colspan="6" class="empty">No series have reached Anime-Trial yet. Watch Jobs for incoming episodes.</td></tr>'
    out+='''</tbody></table><input type="hidden" name="return_size" value="'''+str(result["page_size"])+'''">
<input type="hidden" name="return_page" value="'''+str(result["page"])+'''">
<div id="bulk-actions" class="actions hidden">
<strong id="selection-count">0 selected</strong><div class="inline">
<button type="submit" name="action" value="reject">Reject</button>
<button type="submit" class="secondary" name="action" value="clear-history">Clear history</button>
<button type="submit" class="secondary" name="action" value="reset">Reset</button>
</div></div></form></section>'''
    out+=pager("/",result)
    out+=request_panel(mappings or {})
    out+='''<script>
const checks=[...document.querySelectorAll(".pick")],all=document.getElementById("select-all");
const bar=document.getElementById("bulk-actions"),count=document.getElementById("selection-count");
function sync(){const n=checks.filter(x=>x.checked).length;
count.textContent=n+" selected";bar.classList.toggle("hidden",n===0);
all.checked=checks.length>0 && n===checks.length;all.indeterminate=n>0&&n<checks.length}
all.addEventListener("change",()=>{checks.forEach(x=>x.checked=all.checked);sync()});
checks.forEach(x=>x.addEventListener("change",sync));
document.getElementById("bulk").addEventListener("submit",e=>{
if(!checks.some(x=>x.checked))e.preventDefault()});
</script>'''
    return out+tail()


def jobs_page(result):
    out=shell("Jobs","Jobs")
    out+='''<h1>Jobs</h1><p class="muted">Every incoming Autobrr release appears here,
from receipt through download and completion. Status updates automatically every
five seconds. No page reload required.</p><section class="panel">
<div class="toolbar"><h2>Acquisition activity</h2><div class="inline">
<span class="status running" id="live-indicator">● Live</span>'''
    out+=pager("/jobs",result)+"</div></div>"
    out+='''<table><thead><tr><th>Received</th><th>Release / Anime</th>
<th class="hide-mobile">Source</th><th>Episode</th><th>Status</th></tr>
</thead><tbody id="job-rows"></tbody></table>
<div id="no-jobs" class="empty hidden">No release notifications yet.</div>
</section>'''
    out+=pager("/jobs",result)
    out+='''<section class="panel"><h2>Unmatched releases</h2>
<p class="muted">If a release cannot be matched using your recognized-name
mappings, it stays here until approved.</p>
<form method="post" action="/approve" class="forms">
<input name="notification_id" type="number" min="1" placeholder="Job ID" required>
<input name="tvdb_id" type="number" min="1" placeholder="TVDB ID" required>
<input name="anidb_id" type="number" min="1" placeholder="AniDB ID" required>
<input name="season" type="number" min="1" placeholder="Season" required>
<input name="episode" type="number" min="1" placeholder="Episode" required>
<button>Approve &amp; queue</button></form></section>'''
    out+='<script>const initial='+json.dumps(result,separators=(",",":")).replace("<","\\u003c")+';'
    out+=r'''
const tbody=document.getElementById("job-rows"),blank=document.getElementById("no-jobs");
const live=document.getElementById("live-indicator");
function td(tr,value){let el=document.createElement("td");el.textContent=value??"";tr.appendChild(el);return el}
function update(data){
tbody.replaceChildren();blank.classList.toggle("hidden",data.items.length!==0);
for(const job of data.items){
const tr=document.createElement("tr");
td(tr,job.received_at?new Date(job.received_at*1000).toLocaleString():"One-time request");
let title=td(tr,job.release);if(job.series_title){title.appendChild(document.createElement("br"));
let small=document.createElement("small");small.className="muted";small.textContent=job.series_title;title.appendChild(small)}
td(tr,job.source).classList.add("hide-mobile");
td(tr,job.episode?"S"+String(job.season).padStart(2,"0")+"E"+String(job.episode).padStart(2,"0"):"—");
let cell=document.createElement("td"),status=document.createElement("span");
status.className="status "+(job.status==="COMPLETED"?"completed":
job.status==="RUNNING"?"running":job.status.includes("WAITING")?"waiting":
job.status==="BLOCKED"?"blocked":"");
status.textContent=job.status;cell.appendChild(status);
if(job.message){let small=document.createElement("small");small.className="muted";
small.textContent=" "+job.message;cell.appendChild(small)}
tr.appendChild(cell);tbody.appendChild(tr)}}
update(initial);
async function refresh(){if(document.hidden)return;
try{let response=await fetch("/api/jobs"+location.search,{cache:"no-store"});
if(!response.ok)throw Error("status "+response.status);
update(await response.json());live.textContent="● Live";live.className="status running"}
catch(e){live.textContent="Updates paused";live.className="status waiting"}}
setInterval(refresh,5000);
</script>'''
    return out+tail()


def recognized_page(mappings,editable):
    out=shell("Recognized anime names","Recognized names")
    out+='''<h1>Recognized anime names</h1>
<p class="muted">Exact title aliases used to recognize incoming Autobrr
releases before they enter the Anime-Trial library.</p>
<section class="panel"><h2>Title mappings</h2><table>
<tr><th>Release alias</th><th>TVDB</th><th>AniDB</th><th>Season</th></tr>'''
    for alias,item in sorted(mappings.items()):
        out+="<tr><td>"+escape(alias)+"</td><td>"+escape(item["tvdb_id"])+"</td><td>"+escape(item["anidb_id"])+"</td><td>"+escape(item.get("season",1))+"</td></tr>"
    if not mappings:
        out+='<tr><td colspan="4" class="empty">No recognized names configured yet.</td></tr>'
    out+="</table></section>"
    if editable:
        out+='''<section class="panel"><h2>Manage title aliases</h2>
<form class="forms" method="post" action="/alias">
<input name="alias" class="long" placeholder="Anime title / release alias" required>
<input name="tvdb_id" type="number" min="1" placeholder="TVDB ID" required>
<input name="anidb_id" type="number" min="1" placeholder="AniDB ID" required>
<input name="season" type="number" min="1" value="1" required>
<button>Save</button></form>
<form class="forms" method="post" action="/alias-remove">
<input name="alias" class="long" placeholder="Alias to remove" required>
<button class="secondary">Remove alias</button></form></section>'''
    return out+tail()


def detail_page(detail):
    series=detail["series"]
    out=shell(series[1],"Series")
    out+='<h1>'+escape(series[1])+'</h1><p class="muted">TVDB '+escape(series[2])+' · '+escape(series[3])+'</p>'
    out+='<section class="panel"><h2>Episodes</h2><table><tr><th>Season</th><th>Episode</th><th>Status</th></tr>'
    for season,episode,state in detail["episodes"]:
        out+='<tr><td>'+escape(season)+'</td><td>'+escape(episode)+'</td><td>'+escape(state)+'</td></tr>'
    out+='</table></section><section class="panel"><h2>Acquisition history</h2><table>'
    out+='<tr><th>Release</th><th>Season</th><th>Episode</th><th>Dispatch</th><th>Job</th><th>Staged path</th></tr>'
    for nid,release,season,episode,state,job,path in detail["releases"]:
        out+='<tr>'+''.join('<td>'+escape(v)+'</td>' for v in (release,season,episode,state,job,path))+'</tr>'
    out+='</table></section>'
    out+='<form method="post" action="/series-action" class="forms"><input type="hidden" name="series_id" value="'+str(series[0])+'">'
    out+='<button name="action" value="reject">Reject</button><button name="action" value="clear-history">Clear history</button><button name="action" value="reset">Reset</button></form>'
    return out+tail()
