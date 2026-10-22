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
    layout_class="container jobs-wide" if active=="Jobs" else "container"
    return """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>"""+escape(title)+""" · Anime Discovery</title>
<style>
:root{color-scheme:dark;font:16px system-ui,-apple-system,sans-serif}
*{box-sizing:border-box}
body{margin:0;background:#0d1420;color:#e8edf7}
.container{max-width:1280px;margin:auto;padding:28px 24px 80px}
.container.jobs-wide{max-width:1600px}
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
td{overflow-wrap:anywhere;word-break:normal;vertical-align:top}
.jobs-table th,.jobs-table td{padding:7px 8px}.jobs-table{min-width:850px}
.jobs-table td:last-child{min-width:175px}.jobs-table td:last-child button{padding:6px 9px;margin:2px;font-size:.87rem}
.job-release{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;max-width:270px}
.job-details summary{cursor:pointer;color:#a8bad1;max-width:300px}
.job-details summary span{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.job-details[open] summary span{display:block} td button{max-width:100%;white-space:normal}
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

.match-trace{background:#172335;color:#e8edf7;border:1px solid #52708f;border-radius:14px;padding:24px;width:min(900px,96vw);max-height:90vh;overflow:auto}
.match-trace h3{font-size:1rem;margin:0 0 12px}.match-trace .trace-lead{font-size:1.15rem;font-weight:700;margin:6px 0}
.trace-section{border-top:1px solid #34465c;padding:18px 0}.trace-section:first-child{border-top:0}
.trace-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}
.trace-card{padding:13px;background:#202f43;border:1px solid #354960;border-radius:10px;min-width:0;overflow-wrap:anywhere}
.trace-label{display:block;color:#b1c4dd;font-size:.84rem;margin-bottom:5px}
.trace-check{display:flex;align-items:flex-start;gap:10px;padding:10px 0;border-bottom:1px solid #304159}
.trace-check:last-child{border-bottom:0}.trace-check strong{display:block}
.trace-state{font-weight:700;white-space:nowrap}.trace-pass{color:#9dedc5}.trace-fail{color:#ffc0c7}.trace-unknown{color:#ffe0a0}
.trace-advanced{padding:12px;background:#111e2e;border-radius:10px;overflow-wrap:anywhere}
.trace-advanced summary{cursor:pointer;font-weight:650}.trace-advanced pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:.79rem;line-height:1.5}
@media(max-width:650px){.match-trace{padding:14px;width:96vw}.trace-grid{grid-template-columns:1fr}}
.hidden{display:none!important}
@media(max-width:650px){.container{padding:20px 12px}th,td{padding:10px 7px}
.panel{padding:13px}.hide-mobile{display:none}}
</style></head><body><main class="""+layout_class+""""><header>
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
        return path+"?"+urlencode({"page":p,"size":size,**({"status":result["status_filter"]} if path=="/jobs" and result.get("status_filter","ALL")!="ALL" else {})})
    suffix=("&status="+result["status_filter"].replace(" ","%20") if path=="/jobs" and result.get("status_filter","ALL")!="ALL" else "")
    opts="".join('<option value="'+str(n)+'"'+(" selected" if n==size else "")+'>'+str(n)+'</option>'
                 for n in (20,50,100))
    return ('<div class="page-controls"><span class="muted">'+str(total)+' total</span>'
            '<label>Rows per page <select onchange="location.href='
            "'"+path+"?page=1&size=' + this.value + '"+suffix+"'"+'"'
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
    out+='''<h1>Jobs</h1><p class="muted">Track incoming releases and acquisition jobs. Status updates every five seconds.</p><section class="panel">
<div class="toolbar"><h2>Acquisition activity</h2><div class="inline">
<span class="status running" id="live-indicator">● Live</span>'''
    selected=result.get("status_filter","ALL")
    statuses=("ALL","RECEIVED","IDENTIFYING","NEEDS REVIEW","QUEUED","RUNNING","DOWNLOADING",
              "WAITING FOR DOWNLOAD","WAITING FOR SEARCH","ON HOLD",
              "SKIPPED DUPLICATE","COMPLETED","BLOCKED","CANCELED")
    options="".join('<option value="'+escape(st)+'"'+(" selected" if st==selected else "")+'>'+escape("All statuses" if st=="ALL" else st.title())+'</option>' for st in statuses)
    out+='<label>Status <select id="job-status-filter">'+options+'</select></label>'
    out+=pager("/jobs",result)+"</div></div>"
    out+='''<table class="jobs-table"><thead><tr><th>Received</th><th>Release / Anime</th>
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
    out+='''<dialog id="match-trace-dialog" class="match-trace" aria-labelledby="match-trace-title">
<h2 id="match-trace-title">Identification details</h2>
<p id="match-trace-summary" class="muted" aria-live="polite"></p>
<div id="match-trace-body" aria-live="polite"></div>
<div class="inline" style="margin-top:18px">
<button type="button" id="match-trace-retry" class="hidden">Retry identification</button>
<button type="button" class="secondary" id="match-trace-close">Close</button>
</div>
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
let title=td(tr,"");let release=document.createElement("span");release.className="job-release";release.textContent=job.release;release.title=job.release;title.appendChild(release);
if(typeof job.id==="number"){
let id=document.createElement("small");id.className="muted";
id.textContent=" · Notification #"+job.id+" · ";
title.appendChild(id);
let trace=document.createElement("button");trace.type="button";trace.className="secondary";
trace.textContent="Trace AD-"+job.id;
trace.title="View durable activity history for this notification";
trace.addEventListener("click",async()=>{
 try{
  const response=await fetch("/api/activity-trace?notification_id="+encodeURIComponent(job.id),{cache:"no-store"});
  const data=await response.json();
  if(!response.ok)throw Error(data.error||"Trace unavailable");
  const lines=data.events.map(e=>new Date(e.recorded_at*1000).toLocaleString()+
   " · "+(e.job_id===null?"":("Job #"+e.job_id+" · "))+
   (e.hook?e.hook+" · ":"")+e.event+(e.outcome?" · "+e.outcome:""));
  alert("Trace "+data.trace_id+"\\n"+(lines.length?lines.join("\\n"):"No durable hook events yet"));
 }catch(error){alert(error.message)}
});
title.appendChild(trace);
}
if(job.series_title){title.appendChild(document.createElement("br"));
let small=document.createElement("small");small.className="muted";small.textContent=job.series_title;title.appendChild(small)}
td(tr,job.source).classList.add("hide-mobile");
td(tr,job.episode?"S"+String(job.season).padStart(2,"0")+"E"+String(job.episode).padStart(2,"0"):"—");
let cell=document.createElement("td"),status=document.createElement("span");
status.className="status "+(job.status==="COMPLETED"?"completed":
job.status==="RUNNING"||job.status==="DOWNLOADING"?"running":job.status.includes("WAITING")?"waiting":
(job.status==="BLOCKED"||job.status==="CANCELED")?"blocked":job.status==="ON HOLD"?"waiting":"");
status.textContent=job.status;cell.appendChild(status);
if(job.message){let small=document.createElement("small");small.className="muted";
small.textContent=" "+job.message;cell.appendChild(small)}
tr.appendChild(cell);
const detail=td(tr,"");const disclosure=document.createElement("details");disclosure.className="job-details";const summary=document.createElement("summary");const preview=document.createElement("span");preview.textContent=job.activity_detail||"No further activity recorded";summary.appendChild(preview);disclosure.appendChild(summary);detail.appendChild(disclosure);
let actions=document.createElement("td");
if(job.status==="CANCELED" && typeof job.job_id==="number" &&
   !["TORRENTS_REMOVED","DOWNLOADS_CLEARED"].includes(job.cleanup_status)){
  let btn=document.createElement("button");btn.type="button";btn.className="secondary";
  btn.textContent=job.cleanup_status==="CLEANUP_NEEDED"?"Retry cleanup":"Review cleanup";
  btn.addEventListener("click",async()=>{
    try{
      const response=await fetch("/api/cleanup-preview?job_id="+encodeURIComponent(job.job_id),
        {credentials:"same-origin"});
      const plan=await response.json();
      if(!response.ok)throw Error(plan.error||"Cleanup preview unavailable");
      const count=plan.records.length;
      const summary=count?count+" candidate torrent(s); "+
        plan.records.filter(item=>item.eligible).length+" ownership-verified.": "No verified torrent candidates.";
      if(!plan.can_remove_torrents){
        alert(summary+" Cleanup is blocked to protect unknown or shared resources. No files were deleted.");
        return;
      }
      const size=Number(plan.possible_download_bytes||0);
      const footprint=(size/1073741824).toFixed(2)+" GiB of verified download data";
      const canDelete=plan.can_delete_download_files===true;
      const pending=plan.records.some(item=>item.reconcile_only);
      const guidance=pending
        ? summary+" An earlier request may have completed. Confirm to reconcile its recorded outcome; missing torrents will not be removed again."
        : canDelete
          ? summary+" "+footprint+". Choose whether to preserve or remove only those verified downloads. Staged and library files are always preserved."
          : summary+" Torrent-only cleanup is available. Files will be preserved because complete download-file verification is unavailable.";
      if(!confirm(guidance))return;
      const typed=prompt(canDelete
        ? 'Type REMOVE TORRENT ONLY (preserve files) or REMOVE OWNED DOWNLOAD FILES (delete only preflight-verified downloads).'
        : 'Type REMOVE TORRENT ONLY to preserve all files.');
      if(typed!=="REMOVE TORRENT ONLY" &&
         !(canDelete && typed==="REMOVE OWNED DOWNLOAD FILES"))return;
      const csrf=document.querySelector('input[name="_csrf"]')?.value;
      const done=await fetch("/api/cleanup-confirm",{method:"POST",credentials:"same-origin",
        headers:{"Content-Type":"application/json","X-CSRF-Token":csrf},
        body:JSON.stringify({job_id:job.job_id,confirmation:typed})});
      const result=await done.json();
      if(!done.ok)throw Error(result.error||"Cleanup requires review");
      alert(result.removed+" torrent entry/entries removed. "+
        (result.download_file_cleanup_requested
          ? "Verified download-file deletion was requested; staged media preserved."
          : "Downloaded and staged files were preserved."));
      await refresh();
    }catch(error){alert(error.message)}
  });actions.appendChild(btn);
}
if(job.can_resolve){
  let btn=document.createElement("button");btn.type="button";btn.textContent="Resolve";
  btn.addEventListener("click",()=>{
    document.getElementById("resolve-id").value=String(job.id);
    document.getElementById("resolve-release").textContent=job.release+" · Notification #"+job.id;
    document.getElementById("resolve-dialog").showModal();
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
if(typeof job.id==="number" && job.status!=="COMPLETED" && job.status!=="CANCELED"){
  let btn=document.createElement("button");btn.type="button";btn.className="secondary";
  btn.textContent="Matching details";btn.addEventListener("click",()=>openTrace(job.id,job.status==="NEEDS REVIEW"&&job.can_resolve===true));
  actions.appendChild(btn);
}
tr.appendChild(actions);tbody.appendChild(tr)}}
document.getElementById("resolve-cancel").addEventListener("click",()=>document.getElementById("resolve-dialog").close());
document.getElementById("match-trace-close").addEventListener("click",()=>document.getElementById("match-trace-dialog").close());
function traceNode(tag,cls,text){
  const node=document.createElement(tag);
  if(cls)node.className=cls;
  if(text!==undefined && text!==null)node.textContent=String(text);
  return node;
}
function traceSection(root,title){
  const section=traceNode("section","trace-section");
  section.appendChild(traceNode("h3","",title));root.appendChild(section);return section;
}
function traceCard(root,label,value){
  const box=traceNode("div","trace-card");
  box.appendChild(traceNode("span","trace-label",label));
  box.appendChild(traceNode("strong","",value??"Not recorded"));root.appendChild(box);
}
function traceCheck(root,label,state,detail){
  const item=traceNode("div","trace-check");
  const symbol=state==="pass"?"✓":state==="fail"?"✕":"?";
  const cls=state==="pass"?"trace-pass":state==="fail"?"trace-fail":"trace-unknown";
  item.appendChild(traceNode("span","trace-state "+cls,symbol));
  const info=traceNode("div","");
  info.appendChild(traceNode("strong","",label));
  info.appendChild(traceNode("small","muted",detail||"Evidence not recorded"));
  item.appendChild(info);root.appendChild(item);
}
function traceYesNo(value){return value===true?"pass":value===false?"fail":"unknown"}
function traceIssueExplanation(code){
  const descriptions={
    SEASON_EPISODE_MAPPING_UNVERIFIED:"Anime-Lists has not established a unique season/episode mapping. No episode can be approved.",
    RELEASE_SEASON_PROVIDER_MISMATCH:"The parsed release season disagrees with the verified provider mapping.",
    VERIFIED_EPISODE_MAPPING_MISSING:"The correct internal AniDB episode ID has not been independently verified.",
    MULTIPLE_TVDB_ANIDB_CROSSREFS:"Multiple provider identity pairs remain plausible.",
    AMBIGUOUS_SEASON_SPECIFIC_ANIDB:"More than one season-specific AniDB production remains plausible.",
    TVDB_EPISODE_NOT_UNIQUELY_CONFIRMED:"TVDB did not uniquely confirm the mapped episode.",
    BATCH_FILE_MANIFEST_REQUIRED:"Season packs require a verified file manifest before episode selection.",
    EPISODE_NUMBER_UNRESOLVED:"The release title did not establish a unique episode number.",
    NO_ANIDB_EXACT_TITLE_MATCH:"No exact normalized AniDB title was found.",
    ALL_TVDB_TITLES_BELOW_THRESHOLD:"TVDB provider names did not meet the title matching threshold.",
    NO_EXPLICIT_TVDB_ANIDB_CROSSREF:"No independently corroborated AniDB/TVDB identity link was found."
  };
  return descriptions[code]||"This recorded check requires review; consult Advanced diagnostics for provider evidence.";
}
function traceNumber(value){return Number.isSafeInteger(value)&&value>0?String(value):"Not verified"}
function traceCandidateId(value){return typeof value==="string"&&/^\\d+$/.test(value)?value:
  Number.isSafeInteger(value)&&value>0?String(value):"unknown"}
async function openTrace(notificationId,canRetryIdentity=false){
  const dialog=document.getElementById("match-trace-dialog");
  const retry=document.getElementById("match-trace-retry");
  retry.classList.toggle("hidden",!canRetryIdentity);
  retry.disabled=false;
  retry.onclick=canRetryIdentity?()=>retryIdentity(notificationId,retry,dialog):null;
  const summary=document.getElementById("match-trace-summary");
  const body=document.getElementById("match-trace-body");
  summary.textContent="Notification #"+notificationId+" · Loading evidence…";body.replaceChildren();
  dialog.showModal();
  try{
    const response=await fetch("/api/identity-trace?notification_id="+encodeURIComponent(notificationId),{cache:"no-store"});
    const data=await response.json();if(!response.ok)throw Error("Identification evidence is unavailable");
    if(!data.available){summary.textContent="Notification #"+notificationId;body.appendChild(traceNode("p","muted",data.message||"No identification evidence recorded"));return}
    const ev=data.evidence||{},scores=Array.isArray(ev.candidate_scores)?ev.candidate_scores:[],
      refs=Array.isArray(ev.crossref_diagnostics)?ev.crossref_diagnostics:[],
      issues=Array.isArray(ev.issues)?ev.issues:[],
      workflow=Array.isArray(ev.workflow)?ev.workflow:[],
      queries=Array.isArray(ev.title_queries)?ev.title_queries:[];
    summary.textContent="Notification #"+notificationId+" · Attempt "+(data.attempts??"unknown")+" · "+(data.decision||"Unknown decision");
    const intro=traceSection(body,"Decision and next step");
    intro.appendChild(traceNode("p","trace-lead",issues.includes("SEASON_EPISODE_MAPPING_UNVERIFIED")?"Season and episode mapping not verified":
      issues.includes("RELEASE_SEASON_PROVIDER_MISMATCH")?"Season mapping needs review":
      data.decision==="NEEDS_REVIEW"?"Manual identification review required":data.decision||"Identification evidence"));
    intro.appendChild(traceNode("p","muted",issues.includes("SEASON_EPISODE_MAPPING_UNVERIFIED")
      ?"The AniDB and TVDB series may match, but Anime-Lists did not verify a unique destination season and episode. No season was assumed. Verify both before using Resolve."
      :issues.includes("RELEASE_SEASON_PROVIDER_MISMATCH")
      ?"The anime identity may match, but the release season differs from the provider mapping. Verify the season before using Resolve."
      :data.decision==="NEEDS_REVIEW"?"Review the candidates and any failed or unverified checks below. Use Resolve only with independently verified IDs and season.":"Review the recorded identity evidence below."));
    if(issues.length){
      const explanation=traceSection(body,"Why verification stopped");
      for(const code of issues.slice(0,20)){
        const label=typeof code==="string"?code:"UNKNOWN_ISSUE";
        traceCheck(explanation,label.replace(/_/g," "),"fail",traceIssueExplanation(label));
      }
    }
    const parsed=traceSection(body,"Release and lookup");
    const grid=traceNode("div","trace-grid");parsed.appendChild(grid);
    traceCard(grid,"Searched title",queries.length?queries.join(" · "):"Not recorded");
    traceCard(grid,"Episode candidate",ev.episode_candidate??"Not parsed");
    traceCard(grid,"TVDB candidates returned",ev.tvdb_results_count??"Not recorded");
    traceCard(grid,"Title threshold",ev.threshold_pct==null?"Not recorded":ev.threshold_pct+"%");
    const checks=traceSection(body,"Verification checks");
    if(scores.length){
      for(const score of scores){
        const passed=score.passed===true?true:score.passed===false?false:null;
        traceCheck(checks,"TVDB #"+(score.tvdb_id??"unknown")+" — "+(score.name||"Unnamed candidate"),traceYesNo(passed),
          "Title score "+(score.score_pct??"unknown")+"% · minimum "+(score.threshold_pct??ev.threshold_pct??"unknown")+"% · "+(score.reason||"No reason recorded"));
      }
    }else traceCheck(checks,"TVDB title check","unknown","No candidate scores recorded");
    if(refs.length){
      for(const ref of refs){
        const matched=Array.isArray(ref.matching_anidb_ids)?ref.matching_anidb_ids:[];
        traceCheck(checks,"AniDB ↔ TVDB #"+(ref.tvdb_id??"unknown"),matched.length?"pass":ref.reason==="EXPLICIT_ANIDB_MATCH"?"pass":"unknown",
          "Matched AniDB IDs: "+(matched.length?matched.join(", "):"None recorded")+" · "+(ref.reason||"No reason recorded"));
      }
    }else traceCheck(checks,"AniDB ↔ TVDB cross-reference","unknown","No cross-reference diagnostic records");
    const season=workflow.find(step=>step.step==="Provider season agreement");
    const seasonKnown=season && typeof season.passed==="boolean";
    traceCheck(checks,"Season agreement",seasonKnown?traceYesNo(season.passed):issues.includes("RELEASE_SEASON_PROVIDER_MISMATCH")?"fail":"unknown",
      season?"Release season: "+(season.release_season??"unknown")+" · mapped season: "+(season.mapped_season??"unknown"):
      issues.includes("RELEASE_SEASON_PROVIDER_MISMATCH")?"Release and mapped provider seasons disagree":"No season comparison recorded");
    const matches=traceSection(body,"Candidate identities");
    if(scores.length){
      for(const candidate of scores){
        const card=traceNode("div","trace-card");
        card.appendChild(traceNode("strong","",candidate.name||"Unnamed TVDB candidate"));
        card.appendChild(traceNode("p","muted","TVDB #"+(candidate.tvdb_id??"unknown")+" · "+(candidate.score_pct??"unknown")+"% title match"));
        card.appendChild(traceNode("p","","Compared release: "+(candidate.best_query||"Not recorded")+" ↔ provider title: "+(candidate.best_candidate_title||"Not recorded")));
        if(Array.isArray(candidate.candidate_titles)&&candidate.candidate_titles.length)
          card.appendChild(traceNode("small","muted","Alternate/provider titles: "+candidate.candidate_titles.join(" · ")));
        matches.appendChild(card);
      }
    }else matches.appendChild(traceNode("p","muted","No TVDB candidate identity details recorded"));
    const ani=traceSection(body,"AniDB and Anime-Lists evidence");
    ani.appendChild(traceNode("p","muted","AniDB candidate count: "+(Array.isArray(ev.anidb_candidates)?ev.anidb_candidates.length:"Not recorded")+
      ". Candidate titles and IDs are shown when present in the saved evidence."));
    if(Array.isArray(ev.anidb_candidates)){
      for(const candidate of ev.anidb_candidates){
        const title=typeof candidate==="object"&&candidate!==null?(candidate.matched_titles?.[0]||candidate.titles?.[0]||candidate.title||candidate.name||candidate.anime_title):null;
        const id=typeof candidate==="object"&&candidate!==null?(candidate.anidb_id||candidate.id):null;
        const item=traceNode("div","trace-card");
        item.appendChild(traceNode("strong","",title?(title+" · AniDB #"+(id??"unknown")):"AniDB candidate #"+(id??"unknown")+" (title not recorded)"));
        if(typeof candidate==="object"&&candidate!==null){
          const matches=Array.isArray(candidate.matched_titles)?candidate.matched_titles:[];
          const aliases=Array.isArray(candidate.titles)?candidate.titles.filter(t=>!matches.includes(t)):[];
          if(matches.length)item.appendChild(traceNode("p","muted","Matched title"+(matches.length>1?"s":"")+": "+matches.join(" · ")));
          if(aliases.length)item.appendChild(traceNode("small","muted","Other AniDB titles: "+aliases.join(" · ")));
        }
        ani.appendChild(item);
      }
    }
    for(const ref of refs){
      ani.appendChild(traceNode("p","", "TVDB #"+(ref.tvdb_id??"unknown")+" ↔ AniDB IDs "+
        (Array.isArray(ref.matching_anidb_ids)&&ref.matching_anidb_ids.length?ref.matching_anidb_ids.join(", "):"not verified")));
    }
    const chain=traceSection(body,"Episode identity chain");
    const chainGrid=traceNode("div","trace-grid");chain.appendChild(chainGrid);
    const pairs=Array.isArray(ev.matching_pairs)?ev.matching_pairs:[];
    const chosen=pairs.length===1&&pairs[0]&&typeof pairs[0]==="object"?pairs[0]:null;
    const rule=ev.episode_mapping&&typeof ev.episode_mapping==="object"?ev.episode_mapping:null;
    traceCard(chainGrid,"Selected TVDB series",chosen?"TVDB #"+traceCandidateId(chosen.tvdb_id):"Not uniquely verified");
    traceCard(chainGrid,"Selected AniDB anime",chosen?"AniDB #"+traceCandidateId(chosen.anidb_id):"Not uniquely verified");
    traceCard(chainGrid,"TVDB season / episode",rule?
      "S"+String(rule.tvdb_season??"?").padStart(2,"0")+"E"+String(rule.tvdb_episode??"?").padStart(2,"0"):
      "Not verified");
    traceCard(chainGrid,"AniDB episode number",rule?traceNumber(rule.anidb_episode_number):"Not verified");
    traceCard(chainGrid,"AniDB internal EID",traceNumber(ev.verified_anidb_episode_id));
    traceCard(chainGrid,"Episode ID source",traceNumber(ev.verified_anidb_episode_id)!=="Not verified"?
      (ev.episode_id_source||"Not recorded"):"Not verified");
    traceCheck(chain,"Exact episode identity",traceNumber(ev.verified_anidb_episode_id)!=="Not verified"&&
      rule&&chosen?"pass":"unknown",
      rule?"Mapping source: "+(rule.mapping_source||"Not recorded")+
        " · AniDB episode "+traceNumber(rule.anidb_episode_number):
        "No uniquely verified season/episode rule recorded");
    const mappedCandidates=Array.isArray(ev.season_mapping_candidates)?ev.season_mapping_candidates:[];
    const mapped=traceSection(body,"Season-specific Anime-Lists candidates");
    if(!mappedCandidates.length)mapped.appendChild(traceNode("p","muted","No season-specific candidates recorded"));
    for(const item of mappedCandidates.slice(0,20)){
      if(!item||typeof item!=="object")continue;
      const card=traceNode("div","trace-card");
      card.appendChild(traceNode("strong","","AniDB #"+traceCandidateId(item.anidb_id)+
        " → TVDB #"+traceCandidateId(item.tvdb_id)));
      const er=item.episode_rule&&typeof item.episode_rule==="object"?item.episode_rule:{};
      card.appendChild(traceNode("p","", "TVDB season "+(er.tvdb_season??"unknown")+
        " episode "+(er.tvdb_episode??"unknown")+" ↔ AniDB episode "+
        (er.anidb_episode_number??"unknown")));
      const titles=Array.isArray(item.titles)?item.titles.slice(0,6):[];
      card.appendChild(traceNode("small","muted","AniDB titles: "+(titles.length?titles.join(" · "):"Not recorded")+
        " · Catalog present: "+(item.title_index_present===true?"yes":"not verified")+
        " · Title family corroborated: "+(item.title_family_corrob===true?"yes":
        item.title_family_corrob===false?"no":"not recorded")));
      mapped.appendChild(card);
    }
    const steps=traceSection(body,"Identification workflow");
    if(!workflow.length)steps.appendChild(traceNode("p","muted","No workflow steps recorded"));
    for(const step of workflow.slice(0,30)){
      if(!step||typeof step!=="object")continue;
      const label=typeof step.step==="string"?step.step:"Unnamed step";
      const state=step.passed===true?"pass":step.passed===false?"fail":"unknown";
      const facts=Object.entries(step).filter(([key])=>key!=="step")
        .map(([key,value])=>key.replace(/_/g," ")+": "+(typeof value==="object"?
          JSON.stringify(value):String(value))).join(" · ");
      traceCheck(steps,label,state,facts||"No additional evidence recorded");
    }
    const details=traceNode("details","trace-advanced");
    details.appendChild(traceNode("summary","","Advanced diagnostics (raw recorded evidence)"));
    details.appendChild(traceNode("pre","",JSON.stringify({decision:data.decision,attempts:data.attempts,evidence:ev},null,2)));
    body.appendChild(details);
  }catch(error){
    summary.textContent="Notification #"+notificationId;
    body.replaceChildren(traceNode("p","muted","Could not load identification details. Try again later."));
  }
}
async function retryIdentity(notificationId,button,dialog){
  button.disabled=true;
  try{
    const csrf=document.querySelector('input[name="_csrf"]')?.value;
    const response=await fetch("/api/recheck-identity",{method:"POST",credentials:"same-origin",
      headers:{"Content-Type":"application/json","X-CSRF-Token":csrf},
      body:JSON.stringify({notification_id:notificationId})});
    const outcome=await response.json();
    if(!response.ok)throw Error(outcome.error||"Identity retry could not be scheduled");
    dialog.close();
    await refresh();
  }catch(error){
    alert(error.message);
    await refresh();
  }finally{button.disabled=false}
}
async function manageJob(job,action,button){
  const subject=job.release+" (job #"+job.job_id+")";
  if(action==="cancel" && !confirm("Cancel and archive "+subject+
      "? Existing torrent and files will be preserved until cleanup is explicitly verified."))return;
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
document.getElementById("job-status-filter").addEventListener("change",e=>{const p=new URLSearchParams(location.search);p.set("status",e.target.value);p.set("page","1");location.href="/jobs?"+p.toString()});
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
