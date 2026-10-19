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
                out+='<label>'+esc(field)+' <input type="checkbox" name="'+field+'"'+
                     (' checked' if value else '')+'></label>'
            else:
                out+='<label>'+esc(field)+' <input type="'+kind+'" name="'+field+
                     '" value="'+esc(value)+'"></label>'
        key=SECRETS[name]
        label="Set" if data["credential_status"].get(key) else "Not set"
        out+='<p>Credential: '+esc(label)+' (never shown in browser)</p>'
        out+='<button type="submit">Save &amp; Apply</button></form>'
        out+='</details>'
    out+='<section class="panel"><h2>System</h2><button id="refresh" type="button">Refresh</button>'
    out+='<p>Settings requiring restart are not hot-reloaded.</p><p id="settings-result" role="status"></p></section>'
    out+="""<script>
for(const form of document.querySelectorAll('form.integration')){
  form.addEventListener('submit',async ev=>{
    ev.preventDefault();
    const target=document.getElementById('settings-result');
    const section=form.dataset.name, fields={};
    for(const input of form.querySelectorAll('input')){
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
      target.textContent=data.restart_required?'Saved. Restart required.':'No changes.';
    }catch(e){target.textContent=e.message}
  });
}
document.getElementById('refresh').addEventListener('click',()=>location.reload());
</script>"""
    return out+tail()
