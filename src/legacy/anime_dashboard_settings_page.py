"""Integration settings page. Controls only for persisted, supported fields."""
import html
import json
from anime_shared_settings import snapshot

FIELDS={
 "jellyfin":["enabled","base_url"],
 "sonarr":["enabled","base_url","root_folder","quality_profile_name","quality_profile_id"],
 "shoko":["enabled","base_url","import_folder_id","poll_seconds","auto_link_verified"],
 "autobrr":[],
 "tvdb":["enabled","base_url"],
 "ntfy":["enabled","server","topic","dashboard_url","reminder_hours"],
}
SECRETS={"jellyfin":"jellyfin_api_key","sonarr":"sonarr_api_key",
         "shoko":"shoko_api_key","autobrr":"web_token","ntfy":"ntfy_token",
         "tvdb":"tvdb_api_key"}
def esc(value):
    return html.escape(str(value),quote=True)

def settings_page(directory):
    from anime_dashboard_pages import shell,tail
    data=snapshot(directory)
    settings=data["settings"]
    out=shell("Settings","Settings")
    out+='''<style>
.integration{display:flex;flex-direction:column;gap:17px;margin-top:20px;max-width:780px}
.integration .setting-field{display:grid;grid-template-columns:minmax(130px,180px) minmax(0,1fr);align-items:center;gap:16px}
.integration .setting-field input:not([type=checkbox]){width:100%;min-width:0}
.integration .key-control{display:flex;align-items:stretch;min-width:0}
.integration .key-control input{border-radius:8px 0 0 8px;flex:1}
.integration .key-control button{border-radius:0 8px 8px 0;min-width:48px;padding:8px;white-space:nowrap}
.integration .actions{position:static;box-shadow:none;padding:0;background:transparent;border:0;margin-top:8px;justify-content:flex-start}
.integration .actions button{min-width:130px}
.integration .form-status{color:#a8bad1;min-height:1.5em}
@media(max-width:620px){.integration .setting-field{grid-template-columns:1fr;gap:6px}}
</style><h1>Settings</h1><p class="muted">Edit connection details, test them before saving, then apply when ready.</p>'''
    for name,fields in FIELDS.items():
        title=name.title() if name!="ntfy" else "NTFY"
        key=SECRETS[name]
        term=("Access Token" if name=="ntfy" else "Webhook Token" if name=="autobrr" else "API Key")
        present=bool(data["credential_status"].get(key))
        out+='<details class="panel"><summary><strong>'+esc(title)+'</strong></summary>'
        out+='<form class="integration" data-name="'+esc(name)+'" data-key="'+esc(key)+'" data-stored="'+("true" if present else "false")+'">'
        for field in fields:
            value=settings[name][field]
            kind=("checkbox" if type(value) is bool else "number" if type(value) is int else "text")
            out+='<label class="setting-field"><span>'+esc(field.replace("_"," ").title())+'</span>'
            if kind=="checkbox":
                out+='<input type="checkbox" name="'+field+'"'+(" checked" if value else "")+'>'
            else:
                out+='<input type="'+kind+'" name="'+field+'" value="'+esc(value)+'">'
            out+='</label>'
        out+='<label class="setting-field"><span>'+term+'</span><span class="key-control">'
        out+='<input type="password" name="credential" autocomplete="new-password" spellcheck="false" placeholder="'+("Saved "+term+" ••••••••" if present else "Enter "+term)+'" aria-label="'+term+'">'
        out+='<button type="button" class="toggle-secret" aria-label="Show or hide '+term+'" title="Show or hide '+term+'">👁</button></span></label>'
        out+='<div class="actions"><button type="submit">Save &amp; Apply</button>'
        out+='<button type="button" class="test-connection">'+("Test Notification" if name=="ntfy" else "Test Connection")+'</button></div>'
        out+='<p class="form-status" role="status" aria-live="polite"></p></form></details>'
    out+='<section class="panel"><h2>AniDB</h2><p class="muted">AniDB is currently used through public title and Anime-Lists identity data. This installation has no AniDB API key or independent enable/disable setting. Identity lookups are not yet connected to the unified intake worker.</p></section>'
    out+='<section class="panel"><h2>System</h2><button id="refresh" type="button">Refresh</button><p class="muted">Save &amp; Apply reports when a restart is required. Refresh discards unsaved edits.</p></section>'
    out+="""<script>
let dirty=false;
const csrf=document.querySelector('input[name="_csrf"]')?.value;
const forms=document.querySelectorAll('form.integration');
function fieldsOf(form){
  const fields={};
  for(const input of form.querySelectorAll('input:not([name=credential]):not([name=_csrf])')){
    fields[input.name]=input.type==='checkbox'?input.checked:
      input.type==='number'?Number(input.value):input.value;
  }
  return fields;
}
async function post(path,payload){
  const res=await fetch(path,{method:'POST',credentials:'same-origin',cache:'no-store',
    headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},
    body:JSON.stringify(payload)});
  const data=await res.json();
  if(!res.ok)throw new Error(data.error||'Request failed');
  return data;
}
for(const form of forms){
  const secret=form.querySelector('input[name=credential]');
  const status=form.querySelector('.form-status');
  const setStatus=(message)=>{status.textContent=message};
  let loadedSaved=false;
  let changedSecret=false;
  const key=form.dataset.key;
  const service=form.dataset.name;
  form.addEventListener('input',event=>{
    if(event.target===secret)changedSecret=true;
    dirty=true;
  });
  form.addEventListener('change',()=>{dirty=true});
  form.querySelector('.toggle-secret').addEventListener('click',async()=>{
    if(secret.type==='text'){
      secret.type='password';
      return;
    }
    if(!secret.value&&form.dataset.stored==='true'){
      try{
        const payload=await post('/api/credential-reveal',{key});
        secret.value=payload.value;
        loadedSaved=true;
        changedSecret=false;
      }catch(error){setStatus(error.message);return;}
    }
    secret.type='text';
  });
  form.addEventListener('submit',async event=>{
    event.preventDefault();
    setStatus('Saving…');
    try{
      const draft=fieldsOf(form);
      // No secret written when merely revealing the existing stored value.
      if(changedSecret&&secret.value){
        await post('/api/credentials',{key,value:secret.value,clear:false});
        form.dataset.stored='true';
        changedSecret=false;
        loadedSaved=false;
      }
      const result=Object.keys(draft).length
        ?await post('/api/settings',{settings:{[service]:draft}})
        :{restart_required:false};
      secret.value='';
      secret.type='password';
      dirty=false;
      setStatus(result.restart_required?'Saved. Service restart required.':'Saved.');
    }catch(error){setStatus(error.message);}
  });
  form.querySelector('.test-connection').addEventListener('click',async()=>{
    setStatus('Testing…');
    try{
      const result=await post('/api/test-connection',{
        service,settings:fieldsOf(form),credential:secret.value||null
      });
      setStatus(result.message||'Test completed');
    }catch(error){setStatus(error.message);}
  });
}
window.addEventListener('beforeunload',event=>{
  if(dirty){event.preventDefault();event.returnValue='';}
});
document.getElementById('refresh').addEventListener('click',()=>{
  if(dirty&&!confirm('Discard unsaved changes?'))return;
  dirty=false;location.reload();
});
</script>"""
    return out+tail()
