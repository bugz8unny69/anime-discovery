"""Browser presentation for the Anime Discovery library, jobs and name mappings."""
import html
import json
from urllib.parse import urlencode


def escape(value):
    return html.escape(str(value),quote=True)


def shell(title,active):
    tabs=[("/","Series"),("/jobs","Jobs"),("/recognized","Recognized names"),("/settings","Settings")]
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
<form method="post" action="/logout"><button class="secondary" type="submit">Sign out</button></form></header><nav aria-label="Main navigation">"""+navigation+"</nav>"


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



def keep_review_page(series_id, error):
    """Human-readable, HTML-escaped form failure; API clients still get JSON.

    The library root is Sonarr's destination. The Anime-Trial staging path
    must separately be visible and readable to Sonarr at the exact path used
    by Anime Discovery, even when each service runs in a different container.
    """
    valid_id=(str(series_id) if str(series_id).isdigit()
              and int(series_id)>0 else None)
    back=("/series?id="+valid_id if valid_id else "/")
    reason=getattr(error,"reason",None)
    detail=str(error)[:400]
    already=(reason=="SONARR_EPISODE_ALREADY_PRESENT")
    out=shell("Existing Sonarr episode" if already else "Keep needs attention","Series")
    out+='<h1>'+("Episode already registered in Sonarr" if already
                  else "Keep needs attention")+'</h1>'
    out+='<section class="panel" role="alert">'
    out+='<h2>'+("Sonarr has an existing episode file" if already
                   else "Sonarr has not confirmed this import")+'</h2>'
    out+='<p>'+escape(detail)+'</p>'
    if reason:
        out+='<p class="muted">Diagnostic reason: <code>'+escape(reason)+'</code></p>'
    if already:
        out+='''<p>Sonarr's API reports an already registered episode file. This does
not prove it is identical to the Anime-Trial video, that it has Japanese and
English audio, or that the staged video was imported. Anime Discovery has
preserved the staged source and has not marked Keep complete.</p>
<p>Review the existing episode in Sonarr before choosing to replace it or
retain it. No Sonarr library file or torrent has been removed.</p>'''
    else:
        out+='''<p><strong>Check these Sonarr settings:</strong></p>
<ol>
<li>In Sonarr, <strong>Settings → Media Management → Root Folders</strong>
must point to the permanent anime library, not Anime-Trial.</li>
<li>Sonarr must separately be able to read the Anime-Trial staged files.
For this version of Anime Discovery, the staged path must be the
<strong>same absolute path from both services</strong>. Check NFS/container
mounts and the Sonarr service account's folder and file permissions.</li>
<li>In Sonarr, open <strong>Wanted → Manual Import</strong> and navigate to
the staged episode. Verify its series, season, episode, quality and language.
If those disagree, correct Sonarr's identification before trying Keep again.</li>
</ol>
<p>The Keep operation was not finalized here. Anime Discovery has not deleted
its staged files; a Sonarr series record may have already been created.
No replacement-release search is started.</p>'''
    out+='<p><a href="'+escape(back)+'">Back to anime</a> · '
    out+='<a href="/settings">Anime Discovery Sonarr settings</a></p>'
    out+='</section>'
    return out+tail()


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
staged in Anime-Trial. Completed series stay visible if trial files are missing so you can reset acquisitions. Incoming releases and downloads appear under Jobs.</p>
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
        count=str(item["staged_episodes"])
        if item.get("missing_staged_episodes"):
            count+=" ("+str(item["missing_staged_episodes"])+" missing)"
        out+='<td>'+count+'</td><td>'+escape(item["latest_episode"] or "—")+'</td>'
        out+='<td><span class="status">'+escape(item["status"])+'</span>'
        if item.get("sonarr_reconciliation") in ("ALREADY_MANAGED","PARTIALLY_MANAGED"):
            out+='<div><a href="/series-review-sonarr-cleanup?id='+str(sid)+'">Sonarr duplicates — review cleanup</a></div>'
        out+='</td></tr>'
    if not result["items"]:
        out+='<tr><td colspan="6" class="empty">No series have reached Anime-Trial yet. Watch Jobs for incoming episodes.</td></tr>'
    out+='''</tbody></table><input type="hidden" name="return_size" value="'''+str(result["page_size"])+'''">
<input type="hidden" name="return_page" value="'''+str(result["page"])+'''">
<div id="bulk-actions" class="actions hidden">
<strong id="selection-count">0 selected</strong>
<details><summary>Manage selected series</summary>
<p class="muted">These controls do not delete staged files or restart completed jobs.</p>
<div class="inline">
<button type="submit" name="action" value="reject">Reject series</button>
<button type="submit" class="secondary" name="action" value="clear-history">Hide old activity</button>
<button type="submit" class="secondary" name="action" value="reset">Remove rejection / quarantine</button>
</div></details></div></form></section>'''
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
from receipt through download and completion. Status and activity details refresh every
five seconds. Retry and Cancel are available only when a job needs review.
Retry continues the same attempt; Cancel permanently archives it without deleting
torrents or media. A later webhook can create a fresh attempt.</p><section class="panel">
<div class="toolbar"><h2>Acquisition activity</h2><div class="inline">
<span class="status running" id="live-indicator">● Live</span>'''
    out+=pager("/jobs",result)+"</div></div>"
    out+='''<table><thead><tr><th>Received</th><th>Release / Anime</th>
<th class="hide-mobile">Source</th><th>Episode</th><th>Status</th><th>Activity details</th><th>Actions</th></tr>
</thead><tbody id="job-rows"></tbody></table>
<div id="no-jobs" class="empty hidden">No release notifications yet.</div>
</section>'''
    out+=pager("/jobs",result)
    out+='''<dialog id="resolve-dialog" aria-labelledby="resolve-title" style="background:#172335;color:#e8edf7;border:1px solid #52708f;border-radius:14px;padding:24px;width:min(540px,95vw)">
<h2 id="resolve-title">Resolve unmatched release</h2><p id="resolve-release" class="muted"></p>
<form method="post" action="/approve" class="forms">
<input type="hidden" name="notification_id" id="resolve-id">
<label>TVDB series ID<input name="tvdb_id" type="number" min="1" required></label>
<label>AniDB series ID<input name="anidb_id" type="number" min="1" required></label>
<label>Season<input name="season" type="number" min="1" value="1" required></label>
<label>Episode<input name="episode" type="number" min="1" required></label>
<button type="submit">Approve &amp; queue</button>
<button type="button" class="secondary" id="resolve-cancel">Cancel</button>
</form></dialog>'''
    out+='''<dialog id="match-trace-dialog" style="background:#172335;color:#e8edf7;border:1px solid #52708f;border-radius:14px;padding:24px;width:min(760px,95vw);max-height:85vh;overflow:auto">
<h2>Identification workflow</h2>
<p id="match-trace-summary" class="muted"></p>
<div id="match-trace-body"></div>
<button type="button" class="secondary" id="match-trace-close">Close</button>
</dialog>'''
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
let title=td(tr,job.release);
if(typeof job.id==="number"){let id=document.createElement("small");id.className="muted";id.textContent=" · Notification #"+job.id;title.appendChild(id)}
if(job.series_title){title.appendChild(document.createElement("br"));
let small=document.createElement("small");small.className="muted";small.textContent=job.series_title;title.appendChild(small)}
td(tr,job.source).classList.add("hide-mobile");
td(tr,job.episode?"S"+String(job.season).padStart(2,"0")+"E"+String(job.episode).padStart(2,"0"):"—");
let cell=document.createElement("td"),status=document.createElement("span");
status.className="status "+(job.status==="COMPLETED"?"completed":
job.status==="RUNNING"||job.status==="DOWNLOADING"?"running":job.status.includes("WAITING")?"waiting":
(job.status==="BLOCKED"||job.status==="CANCELED")?"blocked":"");
status.textContent=job.status;cell.appendChild(status);
if(job.message){let small=document.createElement("small");small.className="muted";
small.textContent=" "+job.message;cell.appendChild(small)}
tr.appendChild(cell);
const detail=td(tr,job.activity_detail||"No further activity recorded");
detail.classList.add("muted");
let actions=document.createElement("td");
if(job.can_resolve){
  let btn=document.createElement("button");btn.type="button";btn.textContent="Resolve";
  btn.addEventListener("click",()=>{
    document.getElementById("resolve-id").value=String(job.id);
    document.getElementById("resolve-release").textContent=job.release+" · Notification #"+job.id;
    document.getElementById("resolve-dialog").showModal();
  });actions.appendChild(btn);
}
if(job.can_recheck){
  let btn=document.createElement("button");btn.type="button";
  btn.className="secondary";btn.textContent="Recheck identity";
  btn.addEventListener("click",async()=>{
    if(!confirm("Recheck verified provider identity for notification #"+job.id+"? No torrent will be submitted without successful verification."))return;
    btn.disabled=true;
    try{
      const csrf=document.querySelector('input[name="_csrf"]')?.value;
      const response=await fetch("/api/recheck-identity",{method:"POST",
        credentials:"same-origin",
        headers:{"Content-Type":"application/json","X-CSRF-Token":csrf},
        body:JSON.stringify({notification_id:job.id})});
      const outcome=await response.json();
      if(!response.ok)throw Error(outcome.error||"Identity recheck failed");
      await refresh();
    }catch(error){alert(error.message);btn.disabled=false}
  });
  actions.appendChild(btn);actions.appendChild(document.createTextNode(" "));
}
if(job.can_delete){
  let btn=document.createElement("button");btn.type="button";btn.className="secondary";btn.textContent="Delete";
  btn.addEventListener("click",async()=>{
    if(!confirm("Delete unmatched notification #"+job.id+"? No torrent or media will be deleted."))return;
    try{
      let csrf=document.querySelector('input[name="_csrf"]')?.value;
      let response=await fetch("/api/delete-notification",{method:"POST",credentials:"same-origin",
        headers:{"Content-Type":"application/json","X-CSRF-Token":csrf},
        body:JSON.stringify({notification_id:job.id})});
      let outcome=await response.json();
      if(!response.ok)throw Error(outcome.error||"Deletion failed");
      await refresh();
    }catch(error){alert(error.message)}
  });actions.appendChild(btn);
}
if(job.can_retry || job.can_cancel){
  for(const [operation,label] of [["retry","Retry Now"],["cancel","Cancel Job"]]){
    if(!(operation==="retry"?job.can_retry:job.can_cancel))continue;
    const btn=document.createElement("button");
    btn.type="button";btn.className=operation==="cancel"?"secondary":"";
    btn.textContent=label;
    btn.addEventListener("click",()=>manageJob(job,operation,btn));
    actions.appendChild(btn);
    actions.appendChild(document.createTextNode(" "));
  }
}
if(typeof job.id==="number" && job.status!=="COMPLETED"){
  let btn=document.createElement("button");btn.type="button";btn.className="secondary";
  btn.textContent="Matching details";btn.addEventListener("click",()=>openTrace(job.id));
  actions.appendChild(btn);
}
tr.appendChild(actions);tbody.appendChild(tr)}}
document.getElementById("resolve-cancel").addEventListener("click",()=>document.getElementById("resolve-dialog").close());
document.getElementById("match-trace-close").addEventListener("click",()=>document.getElementById("match-trace-dialog").close());
function traceLine(parent,text){
  const p=document.createElement("p");p.textContent=text;parent.appendChild(p);
}
async function openTrace(notificationId){
  const dialog=document.getElementById("match-trace-dialog");
  const summary=document.getElementById("match-trace-summary");
  const body=document.getElementById("match-trace-body");
  summary.textContent="Notification #"+notificationId;body.replaceChildren();
  dialog.showModal();
  try{
    const response=await fetch("/api/identity-trace?notification_id="+encodeURIComponent(notificationId),{cache:"no-store"});
    const data=await response.json();if(!response.ok)throw Error(data.error||"Trace unavailable");
    if(!data.available){traceLine(body,data.message);return}
    const ev=data.evidence||{};
    traceLine(body,"Decision: "+data.decision+" · Attempt "+data.attempts+
      " · Title threshold "+(ev.threshold_pct??"not recorded")+"%");
    traceLine(body,"Searched: "+(ev.title_queries||[]).join(" | "));
    traceLine(body,"Episode candidate: "+(ev.episode_candidate??"not parsed"));
    traceLine(body,"AniDB exact title candidates: "+(ev.anidb_candidates||[]).length);
    traceLine(body,"TVDB responses considered: "+(ev.tvdb_results_count??"not recorded"));
    for(const candidate of ev.candidate_scores||[]){
      traceLine(body,"TVDB #"+candidate.tvdb_id+" · "+candidate.name+
        " · score "+candidate.score_pct+"% / "+candidate.threshold_pct+"% · "+candidate.reason);
      traceLine(body,"Compared release: "+(candidate.best_query||"not available")+
        " ↔ TVDB title: "+(candidate.best_candidate_title||"not available"));
      if(candidate.candidate_titles?.length){
        traceLine(body,"Provider titles: "+candidate.candidate_titles.join(" | "));
      }
    }
    for(const step of ev.workflow||[]){
      traceLine(body,step.step+": "+JSON.stringify(Object.fromEntries(
        Object.entries(step).filter(([key])=>key!=="step"))));
    }
    for(const entry of ev.crossref_diagnostics||[]){
      traceLine(body,"Cross-reference TVDB #"+entry.tvdb_id+
        " · type "+entry.media_type+
        " · provider AniDB IDs: "+(entry.explicit_anidb_ids||[]).join(", ")+
        " · matched: "+(entry.matching_anidb_ids||[]).join(", ")+
        " · "+entry.reason);
    }
    traceLine(body,"Verified cross-reference pairs: "+(ev.matching_pairs||[]).length);
    traceLine(body,"Reasons: "+((ev.issues||[]).join(", ")||"No reason codes recorded"));
  }catch(error){traceLine(body,"Could not load matching details: "+error.message)}
}
async function manageJob(job,action,button){
  const subject=job.release+" (job #"+job.job_id+")";
  if(action==="cancel" && !confirm("Cancel future attempts for "+subject+
      "? This will not delete or stop any torrent or media."))return;
  button.disabled=true;
  try{
    const csrf=document.querySelector('input[name="_csrf"]')?.value;
    const response=await fetch("/api/manage-job",{method:"POST",credentials:"same-origin",
      headers:{"Content-Type":"application/json","X-CSRF-Token":csrf},
      body:JSON.stringify({job_id:job.job_id,action:action,
        expected_state:job.job_state,expected_attempts:job.attempts})});
    const outcome=await response.json();
    if(!response.ok)throw Error(outcome.error||"Job action failed");
    await refresh();
  }catch(error){alert(error.message);await refresh()}
  finally{button.disabled=false}
}
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
    reconciliation=detail.get("reconciliation")
    out+='<section class="panel"><h2>Sonarr reconciliation</h2>'
    if reconciliation:
        out+='<p><strong>'+escape(reconciliation["result"].replace("_"," "))+'</strong>'
        out+=' · Checked '+escape(reconciliation["checked_at"])+'</p>'
        if reconciliation["monitored"] is not None:
            out+='<p>Series monitored: '+("Yes" if reconciliation["monitored"] else "No")+'</p>'
        out+='<table><tr><th>Season</th><th>Episode</th><th>Sonarr status</th></tr>'
        for entry in reconciliation["episodes"]:
            out+='<tr><td>'+escape(entry["season"])+'</td><td>'+escape(entry["episode"])+'</td><td>'+escape(entry["status"])+'</td></tr>'
        out+='</table>'
        if reconciliation["result"] in ("ALREADY_MANAGED","PARTIALLY_MANAGED"):
            out+='<p>Existing Sonarr files are registered, not yet verified as JP+EN suitable replacements. No cleanup is authorized. External or uncertain torrents are never deleted.</p>'
            out+='<p><a href="/series-review-sonarr-cleanup?id='+str(series[0])+'">Review duplicate cleanup</a></p>'
    else:
        out+='<p>No Sonarr reconciliation check recorded yet.</p>'
    out+='<form method="post" action="/series-check-sonarr"><input type="hidden" name="series_id" value="'+str(series[0])+'"><button class="secondary">Check Sonarr now</button></form></section>'
    if series[3]=="SONARR_MANAGED_REVIEW":
        out+='<section class="panel" role="status"><h2>Already managed in Sonarr</h2>'
        out+='<p>The staged files were not imported again. Review redundant files before confirming deletion; external torrents remain protected.</p>'
        out+='<p><a href="/series-review-sonarr-cleanup?id='+str(series[0])+'">Review redundant files and torrents</a></p></section>'
    preserved=detail.get("cleanup_notices") or []
    if preserved:
        action=("Keep has been submitted to Sonarr." if series[3]=="SONARR_IMPORT_PENDING"
                else "Sonarr already manages these episodes; review cleanup." if series[3]=="SONARR_MANAGED_REVIEW"
                else "Keep completed.")
        out+='<section class="panel" role="status" aria-live="polite">'
        out+='<h2>Original qBittorrent files preserved</h2><p>'+escape(action)+' '
        out+='Anime Discovery will not delete these original torrents or their files because it did not create them or cannot verify ownership. '
        out+='After Sonarr finishes copying the episodes, remove these torrents and their files manually in qBittorrent if desired.</p>'
        out+='<ul>'
        for record in preserved:
            reason=("Already in qBittorrent before Anime Discovery submitted"
                    if record["ownership"]=="EXTERNAL"
                    else "Ownership could not be verified")
            out+='<li><code>'+escape(record["infohash"])+'</code> — '+escape(reason)+'</li>'
        out+='</ul></section>'
    out+='<section class="panel"><h2>Episodes</h2><table><tr><th>Season</th><th>Episode</th><th>Status</th></tr>'
    for season,episode,state in detail["episodes"]:
        out+='<tr><td>'+escape(season)+'</td><td>'+escape(episode)+'</td><td>'+escape(state)+'</td></tr>'
    out+='</table></section><section class="panel"><h2>Acquisition history</h2><table>'
    out+='<tr><th>Release</th><th>Season</th><th>Episode</th><th>Dispatch</th><th>Job</th><th>Staged path</th></tr>'
    for nid,release,season,episode,state,job,path in detail["releases"]:
        out+='<tr>'+''.join('<td>'+escape(v)+'</td>' for v in (release,season,episode,state,job,path))+'</tr>'
    out+='</table></section>'
    remembered=detail.get("remembered_seasons") or []
    if remembered:
        out+='<section class="panel"><h2>Remember verified anime</h2>'
        out+='<p class="muted">Add the independently verified title, TVDB series, season and season-specific AniDB production to Recognized Names. No episode number, release group or acquisition permission is saved.</p>'
        for row in remembered:
            out+='<form method="post" action="/series-remember" class="forms">'
            out+='<input type="hidden" name="series_id" value="'+str(series[0])+'">'
            out+='<input type="hidden" name="season" value="'+str(row["season"])+'">'
            out+='<button type="submit" class="secondary">Add Season '+escape(row["season"])+' to Recognized Names</button>'
            out+='<small class="muted"> '+escape(row["title"])+' · TVDB '+escape(row["tvdb_id"])+' · AniDB '+escape(row["anidb_id"])+'</small>'
            out+='</form>'
        out+='</section>'
    out+='<section class="panel"><h2>Series actions</h2>'
    out+='<form method="post" action="/series-action" class="forms"><input type="hidden" name="series_id" value="'+str(series[0])+'">'
    if series[3] in ("KEPT","SONARR_IMPORT_PENDING","SONARR_MANAGED_REVIEW"):
        out+=('<button type="button" disabled>Already managed in Sonarr</button></form>'
              if series[3]=="SONARR_MANAGED_REVIEW" else
              '<button type="button" disabled>Keep already submitted</button></form>')
    else:
        out+='<button name="action" value="keep">Keep in Sonarr</button></form>'
    out+='<details style="margin-top:18px"><summary>Manage series</summary>'
    out+='<p class="muted">Choose an operation below. Hide activity and remove rejection do not delete files or rerun episodes.</p>'
    out+='<form method="post" action="/series-action" class="forms"><input type="hidden" name="series_id" value="'+str(series[0])+'">'
    out+='<button class="secondary" name="action" value="clear-history">Hide old activity</button>'
    out+='<button class="secondary" name="action" value="reset">Remove rejection / quarantine</button>'
    out+='<button class="secondary" name="action" value="reject">Reject series</button></form>'
    out+='<p class="muted"><strong>Reset acquisitions:</strong> Delete this series\' completed staging copies and previous completed acquisition jobs, then recreate pending jobs from stored Autobrr notifications and verified identities. Original torrents and other series are preserved.</p>'
    out+='<form method="post" action="/series-reset-acquisitions" class="forms" id="acquisition-reset-form">'
    out+='<input type="hidden" name="series_id" value="'+str(series[0])+'"><input type="hidden" name="reset_confirm" value="RESET">'
    out+='<button type="submit" class="secondary">Reset acquisitions &amp; retry</button></form>'
    out+='</details></section>'
    out+="""<script>
const resetForm=document.getElementById("acquisition-reset-form");
if(resetForm)resetForm.addEventListener("submit",function(event){
  if(!confirm("Delete this series' completed trial copies and prior acquisition jobs, then recreate fresh jobs from saved Autobrr records? Original torrents remain untouched."))event.preventDefault();
});
</script>"""
    return out+tail()

def sonarr_cleanup_review_page(title,review):
    """Human review screen; no DELETE on GET, confirmation is CSRF protected."""
    out=shell(title+" — review cleanup","Series")
    out+='<h1>Review redundant Anime-Trial cleanup</h1>'
    out+='<p><a href="/series?id='+str(review["series_id"])+'">Back to series</a></p>'
    out+='<p>Sonarr registered episode files have been checked against their canonical IDs and their actual Japanese and English audio tracks. Different releases may not be byte-identical. This action never deletes the permanent Sonarr library.</p>'
    out+='<section class="panel"><h2>Trial episodes</h2>'
    out+='<table><tr><th>Season</th><th>Episode</th><th>Cleanup eligibility</th><th>Bytes</th></tr>'
    for item in review["episodes"]:
        reason=(item.get("reason") or "")
        status=("Eligible (JP+EN verified)" if item["status"]=="REGISTERED"
                else "Retain — "+item["status"]+(" ("+reason+")" if reason else ""))
        out+='<tr><td>'+escape(item["season"])+'</td><td>'+escape(item["episode"])+'</td><td>'+escape(status)+'</td><td>'+escape(item.get("size") or "-")+'</td></tr>'
    out+='</table><p>'+str(review["eligible"])+' eligible staged file(s), '+str(review["bytes_eligible"])+' bytes.</p></section>'
    out+='<section class="panel"><h2>Original qBittorrent data</h2><ul>'
    for record in review["torrents"]:
        out+='<li><code>'+escape(record["infohash"])+'</code>: '+escape(record["ownership"])+'</li>'
    out+='</ul><p>Only torrents with independently verified Anime Discovery ownership and a safe complete file manifest can be removed. EXTERNAL, UNCERTAIN or shared torrents are preserved. Their cleanup is manual.</p></section>'
    if review["eligible"]:
        out+='<section class="panel"><h2>Confirm selected eligible cleanup</h2>'
        out+='<p>After a fresh safety recheck, eligible Anime-Trial video files will be deleted. Fully verified Anime Discovery-owned torrents will be removed with their files. Other torrents are preserved. This cannot be undone.</p>'
        out+='<form method="post" action="/series-confirm-sonarr-cleanup">'
        out+='<input type="hidden" name="series_id" value="'+str(review["series_id"])+'">'
        out+='<input type="hidden" name="review_fingerprint" value="'+escape(review["review_fingerprint"])+'">'
        out+='<label><input type="checkbox" name="confirm" value="DELETE_VERIFIED_DUPLICATES" required> I authorize deletion of eligible redundant staged files and proven-owned torrents only.</label>'
        out+='<button type="submit">Confirm deletion of verified duplicates</button></form></section>'
    else:
        out+='<section class="panel"><p>No episodes are currently eligible for safe cleanup.</p></section>'
    return out+tail()


def sonarr_cleanup_result_page(series_id,result):
    out=shell("Duplicate cleanup result","Series")
    out+='<h1>Duplicate cleanup outcome</h1>'
    out+='<p>Audit #'+escape(result["audit_id"])+'</p>'
    out+='<p>Staged episodes removed: '+escape(len(result["removed_notification_ids"]))+'</p>'
    out+='<p>Owned torrents removed: '+escape(len(result["removed_owned_torrents"]))+'</p>'
    out+='<h2>Preserved torrents</h2><ul>'
    for item in result["preserved_torrents"]:
        out+='<li><code>'+escape(item["infohash"])+'</code> — '+escape(item["ownership"])+'</li>'
    out+='</ul>'
    if result["errors"]:
        out+='<h2>Items retained for review</h2><ul>'
        for error in result["errors"]:out+='<li>'+escape(error)+'</li>'
        out+='</ul>'
    out+='<p><a href="/series?id='+str(series_id)+'">Return to series</a></p>'
    return out+tail()
