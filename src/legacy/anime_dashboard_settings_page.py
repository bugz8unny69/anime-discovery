"""Integration settings page. Controls only for persisted, supported fields."""
import html
import json
from anime_shared_settings import snapshot

FIELDS={
 "jellyfin":["enabled","base_url"],
 "sonarr":["enabled","base_url","root_folder","quality_profile_name","quality_profile_id"],
 "shoko":["enabled","base_url","import_folder_id","poll_seconds","auto_link_verified"],
 "autobrr":[],
 "ntfy":["enabled","server","topic","dashboard_url","reminder_hours"],
}
SECRETS={"jellyfin":"jellyfin_api_key","sonarr":"sonarr_api_key",
         "shoko":"shoko_api_key","autobrr":"web_token","ntfy":"ntfy_token"}
def esc(value):
    return html.escape(str(value),quote=True)

def settings_page(directory):
    from anime_dashboard_pages import shell,tail
    data=snapshot(directory)
    settings=data["settings"]
    out=shell("Settings","Settings")
    out+='<h1>Settings</h1><p class="muted">Saved values. Changes requiring a service restart will be labeled.</p>'
    for name,fields in FIELDS.items():
        title=name.title() if name!="ntfy" else "NTFY"
        out+='<details class="panel"><summary><strong>'+title+'</strong></summary>'
        out+='<form class="integration" data-name="'+name+'">'
        for field in fields:
            value=settings[name][field]
            kind=("checkbox" if type(value) is bool else
                  "number" if type(value) is int else "text")
            if kind=="checkbox":
                out+=('<label>'+esc(field)+' <input type="checkbox" name="'+field+'"'+
                      (' checked' if value else '')+'></label>')
            else:
                out+=('<label>'+esc(field)+' <input type="'+kind+'" name="'+field+
                      '" value="'+esc(value)+'"></label>')
        key=SECRETS[name]
        label="Set" if data["credential_status"].get(key) else "Not set"
        term=("Access Token" if name=="ntfy" else "Webhook Token" if name=="autobrr" else "API Key")
        out+='<p>'+term+': '+esc(label)+'</p>'
        out+='<label>New '+term+' <input type="password" name="credential" autocomplete="new-password" spellcheck="false"></label>'
        out+='<button type="button" class="toggle-token">Show new value</button>'
        out+='<button type="button" class="save-credential" data-key="'+key+'">Update '+term+'</button>'
        out+='<button type="button" class="clear-credential" data-key="'+key+'">Clear '+term+'</button>'
        out+='<div class="reveal-panel"><label>Confirm admin password to view saved '+term
        out+='<input type="password" name="reveal_password" autocomplete="current-password"></label>'
        out+='<button type="button" class="reveal-stored" data-key="'+key+'">View saved '+term+'</button>'
        out+='<input type="password" name="stored_value" readonly autocomplete="off" aria-label="Saved '+term+'">'
        out+='<button type="button" class="toggle-stored">Show/Hide saved value</button></div>'
        out+='<button type="submit">Save &amp; Apply</button>'
        out+='<button type="button" class="test-connection" data-service="'+name+'">'+('Test Notification' if name=="ntfy" else "Test Connection")+'</button></form>'
        out+='</details>'
    out+='<section class="panel"><h2>System</h2><button id="refresh" type="button">Refresh</button>'
    out+='<p>Settings requiring restart are not hot-reloaded.</p><p id="settings-result" role="status"></p></section>'
    out+="""<script>
for(const form of document.querySelectorAll('form.integration')){
  form.addEventListener('submit',async ev=>{
    ev.preventDefault();
    const target=document.getElementById('settings-result');
    const section=form.dataset.name, fields={};
    for(const input of form.querySelectorAll('input:not([type=password])')){
      fields[input.name]=input.type==='checkbox'?input.checked:
        input.type==='number'?Number(input.value):input.value;
    }
    const token=document.querySelector('input[name="_csrf"]')?.value;
    if(!token){target.textContent='Missing session CSRF token';return}
    try{
      const response=await fetch('/api/settings',{method:'POST',
        credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':token},
        body:JSON.stringify({settings:{[section]:fields}})});
      const data=await response.json();
      if(!response.ok)throw new Error(data.error||'Save failed');
      dirty=false;
      target.textContent=data.restart_required?'Saved. Restart required.':'No changes.';
    }catch(e){target.textContent=e.message}
  });
}
for(const button of document.querySelectorAll('.save-credential,.clear-credential')){
  button.addEventListener('click',async()=>{
    const clear=button.classList.contains('clear-credential');
    const input=button.closest('form').querySelector('input[name=credential]');
    if(clear&&!confirm('Clear this credential? Existing integration may stop working.'))return;
    if(!clear&&!input.value)return;
    const token=document.querySelector('input[name="_csrf"]')?.value;
    const target=document.getElementById('settings-result');
    try{
      const res=await fetch('/api/credentials',{method:'POST',credentials:'same-origin',
        headers:{'Content-Type':'application/json','X-CSRF-Token':token},
        body:JSON.stringify({key:button.dataset.key,clear,value:clear?null:input.value})});
      const body=await res.json();
      if(!res.ok)throw new Error(body.error||'Credential update failed');
      input.value='';
      target.textContent=clear?'Token cleared. Restart may be required.':
        'Token updated. Restart may be required.';
    }catch(error){target.textContent=error.message}
  });
}
let dirty=false;
for(const field of document.querySelectorAll('form.integration input')){
  field.addEventListener('change',()=>{dirty=true});
}
window.addEventListener('beforeunload',event=>{
  if(dirty){event.preventDefault();event.returnValue='';}
});
for(const button of document.querySelectorAll('.test-connection')){
  button.addEventListener('click',async()=>{
    const token=document.querySelector('input[name="_csrf"]')?.value;
    const target=document.getElementById('settings-result');
    try{
      const res=await fetch('/api/test-connection',{method:'POST',credentials:'same-origin',
        headers:{'Content-Type':'application/json','X-CSRF-Token':token},
        body:JSON.stringify({service:button.dataset.service})});
      const data=await res.json();
      if(!res.ok)throw new Error(data.error||'Test failed');
      target.textContent=data.message;
    }catch(error){target.textContent=error.message}
  });
}
for(const button of document.querySelectorAll('.reveal-stored')){
  button.addEventListener('click',async()=>{
    const panel=button.closest('.reveal-panel');
    const password=panel.querySelector('input[name=reveal_password]');
    const stored=panel.querySelector('input[name=stored_value]');
    const target=document.getElementById('settings-result');
    const csrf=document.querySelector('input[name="_csrf"]')?.value;
    stored.value='';
    try{
      const response=await fetch('/api/credential-reveal',{method:'POST',
        credentials:'same-origin',cache:'no-store',
        headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},
        body:JSON.stringify({key:button.dataset.key,password:password.value})});
      password.value='';
      const payload=await response.json();
      if(!response.ok)throw new Error(payload.error||'Unable to reveal saved value');
      stored.value=payload.value;
      stored.type='password';
      target.textContent='Saved value retrieved for this session. Close or refresh to hide it.';
    }catch(error){password.value='';target.textContent=error.message}
  });
}
for(const button of document.querySelectorAll('.toggle-stored')){
  button.addEventListener('click',()=>{
    const input=button.closest('.reveal-panel').querySelector('input[name=stored_value]');
    input.type=input.type==='password'?'text':'password';
  });
}
for(const button of document.querySelectorAll('.toggle-token')){
  button.addEventListener('click',()=>{
    const input=button.closest('form').querySelector('input[name=credential]');
    input.type=input.type==='password'?'text':'password';
    button.textContent=input.type==='password'?'Show new value':'Hide new value';
  });
}
document.getElementById('refresh').addEventListener('click',()=>{dirty=false;location.reload()});
</script>"""
    return out+tail()
