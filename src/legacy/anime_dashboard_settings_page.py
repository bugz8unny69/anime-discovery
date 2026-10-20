"""Schema-driven configuration dashboard: scalar settings render automatically.

The shared settings schema owns defaults, labels, visibility, UI input types,
and per-section credential/test integration. All writes still go through the
existing atomic, validated /api/settings endpoint.
"""
import html
from anime_shared_settings import snapshot
from anime_settings_schema import dashboard_sections

def esc(value):
    return html.escape(str(value),quote=True)


def render_field(field_name, spec, value):
    """Render an allowlisted schema field; never render arbitrary config keys."""
    if not spec["visible"]:
        return ""
    kind=spec["type"]
    if kind not in ("boolean","integer","string"):
        raise ValueError("Complex setting must have a custom editor")
    label=spec["label"] or field_name.replace("_"," ").title()
    field=esc(field_name)
    out='<label class="setting-field"><span>'+esc(label)+'</span>'
    choices=spec.get("choices")
    if choices is not None:
        out+='<select name="'+field+'">'
        for choice in choices:
            out+='<option value="'+esc(choice)+'"'+(" selected" if value==choice else "")+'>'+esc(choice)+'</option>'
        out+='</select>'
    elif kind=="boolean":
        out+='<input type="checkbox" name="'+field+'"'+(" checked" if value else "")+'>'
    else:
        typ="number" if kind=="integer" else "text"
        attrs=(' step="1"' if kind=="integer" else "")
        if spec["min"] is not None:
            attrs+=' min="'+esc(spec["min"])+'"'
        if spec["max"] is not None:
            attrs+=' max="'+esc(spec["max"])+'"'
        out+='<input type="'+typ+'" name="'+field+'" value="'+esc(value)+'"'+attrs+(' required' if kind=="integer" else '')+'>'
    if spec.get("help"):
        out+='<small class="muted">'+esc(spec["help"])+'</small>'
    return out+'</label>'


def settings_page(directory):
    from anime_dashboard_pages import shell,tail
    data=snapshot(directory)
    settings=data["settings"]
    out=shell("Settings","Settings")
    out+='''<style>
.integration{display:flex;flex-direction:column;gap:17px;margin-top:20px;max-width:780px}
.integration .setting-field{display:grid;grid-template-columns:minmax(130px,180px) minmax(0,1fr);align-items:center;gap:16px}
.integration .setting-field input:not([type=checkbox]),.integration .setting-field select{width:100%;min-width:0}
.integration .setting-field small{grid-column:2}
.integration .key-control{display:flex;align-items:stretch;min-width:0}
.integration .key-control input{border-radius:8px 0 0 8px;flex:1}
.integration .key-control button{border-radius:0 8px 8px 0;min-width:48px;padding:8px;white-space:nowrap}
.integration .actions{position:static;box-shadow:none;padding:0;background:transparent;border:0;margin-top:8px;justify-content:flex-start}
.integration .actions button{min-width:130px}
.integration .form-status{color:#a8bad1;min-height:1.5em}
@media(max-width:620px){.integration .setting-field{grid-template-columns:1fr;gap:6px}.integration .setting-field small{grid-column:1}}
</style><h1>Settings</h1><p class="muted">Settings are generated from the configuration schema. Save &amp; Apply reports when a restart is required.</p>'''
    sections=dashboard_sections()
    # Autobrr owns an incoming webhook token, not a settings.json section.
    panels=list(sections.items())+[("autobrr",{
        "title":"Autobrr","credential":"web_token",
        "credential_label":"Webhook Token","test_connection":True,
        "fields":{},"description":"Incoming webhooks use this token; send a test event from Autobrr."
    })]
    for name,cfg in panels:
        secret_key=cfg.get("credential")
        present=bool(data["credential_status"].get(secret_key)) if secret_key else False
        title=cfg.get("title",name.title())
        out+='<details class="panel"><summary><strong>'+esc(title)+'</strong></summary>'
        form_id=(' id="anidb-public"' if name=="anidb" else
                 ' id="identity-score-form"' if name=="identity" else "")
        out+='<form class="integration"'+form_id+' data-name="'+esc(name)+'"'
        if secret_key:
            out+=' data-key="'+esc(secret_key)+'" data-stored="'+("true" if present else "false")+'"'
        out+='>'
        if cfg.get("description"):
            out+='<p class="muted">'+esc(cfg["description"])+'</p>'
        for key,spec in cfg["fields"].items():
            if spec["visible"]:
                out+=render_field(key,spec,settings[name][key])
        if secret_key:
            term=cfg.get("credential_label","API Key")
            out+='<label class="setting-field"><span>'+esc(term)+'</span><span class="key-control">'
            out+='<input type="password" name="credential" autocomplete="new-password" spellcheck="false" placeholder="'+("Saved "+esc(term)+" ••••••••" if present else "Enter "+esc(term))+'" aria-label="'+esc(term)+'">'
            out+='<button type="button" class="toggle-secret" aria-label="Show or hide '+esc(term)+'" title="Show or hide '+esc(term)+'">👁</button></span></label>'
        out+='<div class="actions"><button type="submit">Save &amp; Apply</button>'
        if cfg.get("test_connection"):
            out+='<button type="button" class="test-connection">'+("Test Notification" if name=="ntfy" else "Test Connection")+'</button>'
        out+='</div><p class="form-status" role="status" aria-live="polite"></p></form></details>'
    out+='<section class="panel"><h2>System</h2><button id="refresh" type="button">Refresh</button><p class="muted">Refresh discards unsaved edits. Complex and internal settings stay in their specialized editors or CLI.</p></section>'
    out+="""<script>
let dirty=false;
const csrf=document.querySelector('input[name="_csrf"]')?.value;
const forms=document.querySelectorAll('form.integration');
function fieldsOf(form){
  const fields={};
  for(const input of form.querySelectorAll('input:not([name=credential]):not([name=_csrf]),select')){
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
  let changedSecret=false;
  const key=form.dataset.key;
  const service=form.dataset.name;
  form.addEventListener('input',event=>{
    if(secret&&event.target===secret)changedSecret=true;
    dirty=true;
  });
  form.addEventListener('change',()=>{dirty=true});
  form.querySelector('.toggle-secret')?.addEventListener('click',async()=>{
    if(secret.type==='text'){secret.type='password';return;}
    if(!secret.value&&form.dataset.stored==='true'){
      try{
        const payload=await post('/api/credential-reveal',{key});
        secret.value=payload.value;
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
      // Viewing a saved secret must not result in a credential update.
      if(secret&&changedSecret&&secret.value){
        await post('/api/credentials',{key,value:secret.value,clear:false});
        form.dataset.stored='true';
        changedSecret=false;
      }
      const result=Object.keys(draft).length
        ?await post('/api/settings',{settings:{[service]:draft}})
        :{restart_required:false};
      if(secret){secret.value='';secret.type='password';}
      dirty=false;
      setStatus(result.restart_required?'Saved. Service restart required.':'Saved.');
    }catch(error){setStatus(error.message);}
  });
  form.querySelector('.test-connection')?.addEventListener('click',async()=>{
    setStatus('Testing…');
    try{
      const result=await post('/api/test-connection',{
        service,settings:fieldsOf(form),credential:secret?.value||null
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
