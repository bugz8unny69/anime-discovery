/* Reuses the legacy jobs-table DOM rendering and schema-driven settings pattern.
 * Private data and actions travel only through /api/v1/. No legacy endpoints.
 */
'use strict';
const API = '/api/v1';
const MAX_CURSOR = '9223372036854775807';
const COPY = Object.freeze({
  'dashboard.connection': 'The dashboard could not connect. Refresh to try again.',
  'dashboard.expired': 'Please sign in to continue.',
  'dashboard.request_failed': 'The request could not be completed.',
  'dashboard.uncertain': 'The response could not be confirmed. Refresh the job status before trying again.',
  'dashboard.submitting': 'Submitting the job.',
  'dashboard.confirm_cancel': 'Cancel this unfinished acquisition and clean up its owned download files?',
  'dashboard.confirm_reject': 'Reject this anime, stop future automatic acquisition for this AniDB anime, and remove this staged video and its episode NFO?',
  'dashboard.confirm_cleanup': 'Continue cleanup for this canceled acquisition?',
  'dashboard.not_available': 'This action is not available.',
  'dashboard.settings_saved': 'Settings saved. New operations will use these values.',
  'dashboard.restart': 'Settings saved. A service restart is required for some changes.',
  'dashboard.saved_unconfirmed': 'Changes were saved, but storage durability needs review.',
  'dashboard.credentials_saved': 'Credentials saved.',
  'dashboard.invalid_value': 'Check the setting value before saving.',
  'dashboard.no_history': 'No history has been recorded yet.',
  'dashboard.not_staged': 'Staging is unfinished. A completed job does not mean the anime is ready to watch.',
  'dashboard.staged': 'Staged for viewing. Choose Keep when it is available.',
  'dashboard.scope': 'Intake shows each acquisition separately. Several releases may belong to the same anime.',
  'dashboard.page_filter': 'The status filter applies to this page.',
  'dashboard.discard': 'Discard unsaved changes and refresh settings?',
});
const $ = id => document.getElementById(id);
const node = (tag, text, cls) => {
  const el = document.createElement(tag);
  if (text !== undefined && text !== null) el.textContent = String(text);
  if (cls) el.className = cls;
  return el;
};
const state = {
  csrf: null, generation: 0, requests: new Set(), jobs: [], pending: new Set(),
  page: location.pathname === '/settings' ? 'settings' : location.pathname === '/jobs' ? 'jobs' : 'intake',
  cursor: MAX_CURSOR, previous: [], next: null, loading: null, timer: null,
  settings: null, credentials: null, dirty: false,
  historyJob: null, historyCursor: 0, historyNext: null, historyVersion: 0,
};
function notice(message = '', error = false) {
  $('notice').textContent = message;
  $('notice').classList.toggle('error', error);
}
function clearPrivate(message = '') {
  state.generation += 1;
  state.csrf = null;
  for (const controller of state.requests) controller.abort();
  state.requests.clear();
  clearTimeout(state.timer);
  state.jobs = []; state.pending.clear(); state.settings = null; state.credentials = null;
  state.previous = []; state.cursor = MAX_CURSOR; state.next = null; state.dirty = false;
  state.historyJob = null; state.historyVersion += 1;
  $('job-rows').replaceChildren(); $('settings-fields').replaceChildren();
  $('credential-forms').replaceChildren(); $('history-rows').replaceChildren();
  $('access-key').value = '';
  if ($('history-dialog').open) $('history-dialog').close();
  $('workspace').hidden = true; $('sign-out').hidden = true; $('login-panel').hidden = false;
  notice(message);
}
async function request(path, {method = 'GET', body} = {}) {
  // Never accept API-supplied URLs or arbitrary destinations for mutations.
  if (!path.startsWith(API + '/')) throw new Error(COPY['dashboard.request_failed']);
  const generation = state.generation;
  const controller = new AbortController(); state.requests.add(controller);
  const timeout = setTimeout(() => controller.abort(), 15000);
  try {
    const headers = {'Accept': 'application/json'};
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (method !== 'GET' && state.csrf) headers['X-CSRF-Token'] = state.csrf;
    const response = await fetch(path, {method, headers, credentials: 'same-origin', cache: 'no-store',
      redirect: 'error', signal: controller.signal, body: body === undefined ? undefined : JSON.stringify(body)});
    const result = await response.json();
    if (generation !== state.generation) throw new DOMException('Stale response', 'AbortError');
    if (!response.ok) {
      const message = result.error?.message || COPY['dashboard.request_failed'];
      if (response.status === 401 && state.csrf) clearPrivate(COPY['dashboard.expired']);
      const error = new Error(message); error.status = response.status; throw error;
    }
    return result.data;
  } catch (error) {
    if (generation !== state.generation) throw new DOMException('Stale response', 'AbortError');
    if (error.status) throw error;
    throw new Error(method === 'GET' ? COPY['dashboard.connection'] : COPY['dashboard.uncertain']);
  } finally {
    clearTimeout(timeout); state.requests.delete(controller);
  }
}
function displayError(error) {
  if (error.name !== 'AbortError') notice(error.message || COPY['dashboard.request_failed'], true);
}
function date(value) { return value ? new Date(value).toLocaleString() : '—'; }
function statusBadge(job) {
  const classes = {DONE: 'completed', RUNNING: 'running', RETRY_WAIT: 'waiting', ON_HOLD: 'waiting', NEEDS_REVIEW: 'blocked', BLOCKED: 'blocked', CANCELED: 'blocked'};
  return node('span', job.status?.message || 'Unknown status', 'status ' + (classes[job.state] || ''));
}
function actionButton(job, action, label) {
  const capability = job.actions?.[action];
  const submitting = state.pending.has(job.cancellation.operation_id);
  const enabled = Boolean(capability?.enabled && capability.execution_available !== false && !submitting);
  const explanation = submitting ? COPY['dashboard.submitting'] :
    capability?.disabled_reason?.message || capability?.availability_reason?.message;
  const wrapper = node('span', null, 'action-tooltip');
  const button = node('button', label, action === 'cancel' ? 'danger' : 'secondary');
  button.type = 'button'; button.disabled = !enabled;
  if (!enabled) {
    wrapper.tabIndex = 0; wrapper.dataset.disabled = 'true';
    wrapper.title = explanation || COPY['dashboard.not_available'];
    wrapper.setAttribute('aria-label', label + ': ' + wrapper.title);
    button.title = wrapper.title;
  }
  button.addEventListener('click', () => submitAction(job, action));
  wrapper.appendChild(button); return wrapper;
}
async function submitAction(job, action) {
  if (state.pending.has(job.cancellation.operation_id)) return;
  const capability = job.actions?.[action];
  if (!capability?.enabled || capability.execution_available === false) return;
  if (action === 'cancel' && !confirm(COPY['dashboard.confirm_cancel'])) return;
  if (action === 'reject' && !confirm(COPY['dashboard.confirm_reject'])) return;
  if (action === 'cleanup' && !confirm(COPY['dashboard.confirm_cleanup'])) return;
  state.pending.add(job.cancellation.operation_id); renderJobs();
  try {
    const receipt = await request(`${API}/jobs/${job.job_id}/${action}`, {method: 'POST', body: {}});
    notice(receipt.notification?.message || COPY['dashboard.request_failed']);
  } catch (error) { displayError(error); }
  finally {
    // Drain a poll that began before the action, then obtain a fresh snapshot.
    if (state.loading) await state.loading;
    state.pending.delete(job.cancellation.operation_id);
  }
  // A lost response is reconciled by reading status, never by replaying a POST.
  if (state.csrf) await loadActivity();
}
function renderJobs() {
  const tbody = $('job-rows'); tbody.replaceChildren();
  const filter = $('status-filter').value;
  const jobs = state.jobs.filter(job => !filter || job.state === filter);
  $('no-jobs').hidden = jobs.length !== 0;
  for (const job of jobs) {
    const tr = node('tr');
    const td = value => { const cell = node('td', value); tr.appendChild(cell); return cell; };
    td(date(job.received_at_ms || job.created_at_ms));
    const title = td();
    title.appendChild(node('span', job.release_name || job.anime_title || 'Management job', 'job-release'));
    if (job.anime_title && job.anime_title !== job.release_name) title.appendChild(node('small', job.anime_title, 'muted job-note'));
    td().appendChild(node('span', `#${job.job_id} · ${job.label?.message || 'Job'}`));
    const status = td(); status.appendChild(statusBadge(job));
    if (state.page === 'intake') status.appendChild(node('small', job.acquisition_status.message, 'muted job-note'));
    const details = td();
    if (job.reason) {
      details.appendChild(node('p', job.reason.message));
      if (job.reason.action) details.appendChild(node('small', job.reason.action, 'muted'));
    } else if (!job.is_management_action && job.state === 'DONE' && job.cancellation.state === 'ACTIVE') {
      details.appendChild(node('p', COPY['dashboard.not_staged']));
    } else if (job.cancellation.state === 'STAGED') details.appendChild(node('p', COPY['dashboard.staged']));
    const activeAction = ['cleanup', 'keep', 'reject'].map(name => job.actions?.[name]?.job).find(Boolean);
    if (activeAction) {
      details.appendChild(node('p', `Job #${activeAction.job_id}: ${activeAction.status.message}`));
      if (activeAction.reason) details.appendChild(node('small', activeAction.reason.message, 'muted'));
      const controlHistory = node('button', 'Action job history', 'secondary');
      controlHistory.addEventListener('click', () => openHistory(activeAction.job_id)); details.appendChild(controlHistory);
    }
    const actions = td();
    if (job.actions?.keep && 'execution_available' in job.actions.keep) {
      actions.appendChild(actionButton(job, 'keep', 'Keep'));
      if (job.actions?.reject) actions.appendChild(actionButton(job, 'reject', 'Reject'));
      if (job.cancellation.state !== 'STAGED') actions.appendChild(actionButton(job, 'cancel', 'Cancel'));
      if (job.cancellation.state === 'CANCELED' || job.cancellation.state === 'CANCEL_REQUESTED') actions.appendChild(actionButton(job, 'cleanup', 'Cleanup'));
    }
    const history = node('button', 'History', 'secondary');
    history.addEventListener('click', () => openHistory(job.job_id)); actions.appendChild(history);
    tbody.appendChild(tr);
  }
  $('previous-page').disabled = state.previous.length === 0;
  $('next-page').disabled = state.next === null;
}
async function loadActivity() {
  if (state.loading) return state.loading;
  const generation = state.generation;
  state.loading = (async () => {
    try {
      const data = await request(`${API}/${state.page === 'intake' ? 'intake' : 'jobs'}?before_id=${state.cursor}&limit=30`);
      if (generation !== state.generation || !state.csrf) return;
      state.jobs = data.items; state.next = data.next_before_id ?? null; renderJobs();
      $('live-indicator').textContent = '● Live'; $('live-indicator').className = 'status running';
    } catch (error) {
      if (generation === state.generation) {
        $('live-indicator').textContent = 'Updates paused'; $('live-indicator').className = 'status waiting';
        displayError(error);
      }
    }
  })();
  try { await state.loading; } finally { state.loading = null; }
}
async function tick() {
  if (state.csrf && state.page !== 'settings' && !document.hidden) await loadActivity();
  if (state.csrf) state.timer = setTimeout(tick, 5000);
}
async function openHistory(jobId) {
  state.historyJob = jobId; state.historyCursor = 0; state.historyNext = null; state.historyVersion += 1;
  $('history-title').textContent = `Job #${jobId} history`; $('history-rows').replaceChildren();
  if (!$('history-dialog').open) $('history-dialog').showModal();
  await loadHistory();
}
async function loadHistory() {
  const version = state.historyVersion; const job = state.historyJob;
  if (!job) return;
  $('history-more').disabled = true;
  try {
    const data = await request(`${API}/jobs/${job}/history?after_id=${state.historyCursor}&limit=50`);
    if (version !== state.historyVersion || !state.csrf) return;
    for (const entry of data.items) {
      const article = node('article', null, 'history-entry');
      article.appendChild(node('small', date(entry.occurred_at_ms), 'muted'));
      article.appendChild(node('p', entry.event.message));
      if (entry.handler) article.appendChild(node('small', entry.handler.message, 'muted'));
      if (entry.reason) { article.appendChild(node('p', entry.reason.message)); article.appendChild(node('small', entry.reason.action, 'muted')); }
      $('history-rows').appendChild(article);
    }
    if (!data.items.length && !state.historyCursor) $('history-rows').appendChild(node('p', COPY['dashboard.no_history']));
    state.historyNext = data.next_after_id;
    $('history-more').hidden = state.historyNext === null;
  } catch (error) { displayError(error); }
  finally { if (version === state.historyVersion) $('history-more').disabled = false; }
}
function settingInput(path, definition, value) {
  const label = node('label', null, 'setting-field'); label.appendChild(node('span', definition.label));
  const input = node(definition.type === 'levels' ? 'textarea' : 'input');
  input.name = path; input.dataset.kind = definition.type;
  if (definition.type === 'levels') input.value = JSON.stringify(value, null, 2);
  else {
    input.type = definition.type === 'integer' ? 'number' : 'text'; input.value = String(value);
    if (definition.minimum !== null) input.min = String(definition.minimum);
    if (definition.maximum !== null) input.max = String(definition.maximum);
    if (definition.type === 'integer') { input.step = '1'; input.required = true; }
  }
  input.dataset.original = input.value;
  label.appendChild(input);
  label.appendChild(node('small', definition.help + (definition.apply_mode === 'restart' ? ' Requires a restart.' : ''), 'muted'));
  return label;
}
async function loadSettings() {
  try {
    const [settings, credentials] = await Promise.all([request(`${API}/settings`), request(`${API}/credentials`)]);
    if (!state.csrf) return;
    state.settings = settings; state.credentials = credentials; state.dirty = false;
    $('restart-notice').textContent = settings.pending_restart_fields.length ? COPY['dashboard.restart'] : '';
    const panels = $('settings-fields'); panels.replaceChildren();
    for (const section of Object.keys(settings.desired.settings)) {
      const panel = node('details', null, 'panel'); panel.appendChild(node('summary', section === 'trial' ? 'Intake selection' : section));
      const form = node('form', null, 'integration');
      for (const [path, definition] of Object.entries(settings.fields)) {
        if (!path.startsWith(section + '.')) continue;
        form.appendChild(settingInput(path, definition, settings.desired.settings[section][path.split('.')[1]]));
      }
      const save = node('button', 'Save settings'); save.type = 'submit'; form.appendChild(save);
      const result = node('p', '', 'form-status'); result.setAttribute('role', 'status'); form.appendChild(result);
      form.addEventListener('input', () => { state.dirty = true; });
      form.addEventListener('submit', async event => {
        event.preventDefault(); save.disabled = true; result.textContent = '';
        const inputs = [...form.querySelectorAll('[data-kind]')];
        for (const input of inputs) input.disabled = true;
        try {
          const fields = {};
          for (const input of form.querySelectorAll('[data-kind]')) {
            if (input.value === input.dataset.original) continue;
            let value;
            try { value = input.dataset.kind === 'levels' ? JSON.parse(input.value) : input.dataset.kind === 'integer' ? Number(input.value) : input.value; }
            catch { throw new Error(COPY['dashboard.invalid_value']); }
            fields[input.name.split('.')[1]] = value;
          }
          if (!Object.keys(fields).length) return;
          const saved = await request(`${API}/settings`, {method: 'PATCH', body: {expected_revision: state.settings.desired.revision, settings: {[section]: fields}}});
          state.settings.desired = saved.configuration;
          for (const input of form.querySelectorAll('[data-kind]')) input.dataset.original = input.value;
          result.textContent = !saved.durability_confirmed ? COPY['dashboard.saved_unconfirmed'] : saved.restart_fields.length ? COPY['dashboard.restart'] : COPY['dashboard.settings_saved'];
          state.dirty = [...document.querySelectorAll('[data-kind]')].some(input => input.value !== input.dataset.original);
        } catch (error) { result.textContent = error.message; }
        finally { save.disabled = false; for (const input of inputs) input.disabled = false; }
      });
      panel.appendChild(form); panels.appendChild(panel);
    }
    renderCredentials();
  } catch (error) { displayError(error); }
}
function renderCredentials() {
  const container = $('credential-forms'); container.replaceChildren();
  const specs = [
    ['tvdb', 'TVDB', 'tvdb_api_key_configured', [['api_key', 'API key']]],
    ['sonarr', 'Sonarr', 'sonarr_configured', [['api_key', 'API key']]],
    ['qbittorrent', 'qBittorrent', 'qbittorrent_configured', [['username', 'Username'], ['password', 'Password']]],
  ];
  for (const [service, title, presence, fields] of specs) {
    const form = node('form', null, 'integration'); form.autocomplete = 'off';
    form.appendChild(node('h2', title));
    const status = node('p', state.credentials[presence] ? 'Credentials saved' : 'Not configured', 'muted'); form.appendChild(status);
    for (const [name, label] of fields) {
      const wrapper = node('label', null, 'setting-field'); wrapper.appendChild(node('span', label));
      const input = node('input'); input.name = name; input.type = name === 'username' ? 'text' : 'password';
      input.autocomplete = 'new-password'; input.required = true; input.maxLength = 4096;
      wrapper.appendChild(input); form.appendChild(wrapper);
    }
    const save = node('button', 'Replace credentials'); save.type = 'submit'; form.appendChild(save);
    const result = node('p', '', 'form-status'); result.setAttribute('role', 'status'); form.appendChild(result);
    form.addEventListener('input', () => { state.dirty = true; });
    form.addEventListener('submit', async event => {
      event.preventDefault(); save.disabled = true;
      const inputs = [...form.querySelectorAll('input')];
      for (const input of inputs) input.disabled = true;
      try {
        const payload = {expected_revision: state.credentials.revision};
        for (const [name] of fields) payload[name] = form.elements.namedItem(name).value;
        const saved = await request(`${API}/credentials/${service}`, {method: 'PATCH', body: payload});
        state.credentials = saved.status; form.reset();
        status.textContent = saved.status[presence] ? 'Credentials saved' : 'Not configured';
        result.textContent = saved.durability_confirmed ? COPY['dashboard.credentials_saved'] : COPY['dashboard.saved_unconfirmed'];
        state.dirty = [...document.querySelectorAll('[data-kind]')].some(input => input.value !== input.dataset.original) ||
          [...container.querySelectorAll('input')].some(input => input.value);
      } catch (error) { result.textContent = error.message; }
      finally { save.disabled = false; for (const input of inputs) input.disabled = false; }
    });
    container.appendChild(form);
  }
  container.appendChild(node('p', 'Saved credentials are never revealed. Webhook and management access use separate keys.', 'muted'));
  container.appendChild(node('p', `Webhook access: ${state.credentials.webhook_configured ? 'configured' : 'not configured'} · Management access: ${state.credentials.management_configured ? 'configured' : 'not configured'}`, 'muted'));
}
async function showWorkspace() {
  $('login-panel').hidden = true; $('workspace').hidden = false; $('sign-out').hidden = false;
  $('activity-panel').hidden = state.page === 'settings'; $('settings-panel').hidden = state.page !== 'settings';
  for (const link of document.querySelectorAll('nav a')) link.classList.toggle('selected', new URL(link.href).pathname === location.pathname);
  if (state.page === 'settings') { await loadSettings(); return; }
  $('page-title').textContent = state.page === 'intake' ? 'Intake' : 'Jobs';
  $('activity-title').textContent = state.page === 'intake' ? 'Incoming anime' : 'Job activity';
  $('page-description').textContent = state.page === 'intake' ? 'Follow incoming anime through processing and staging.' : 'Track jobs and their recorded history. Status updates every five seconds.';
  $('page-note').textContent = (state.page === 'intake' ? COPY['dashboard.scope'] + ' ' : '') + COPY['dashboard.page_filter'];
  await loadActivity(); clearTimeout(state.timer); if (state.csrf) state.timer = setTimeout(tick, 5000);
}
$('login-form').addEventListener('submit', async event => {
  event.preventDefault(); const button = event.currentTarget.querySelector('button'); button.disabled = true;
  try {
    const result = await request(`${API}/auth/session`, {method: 'POST', body: {token: $('access-key').value}});
    $('access-key').value = ''; state.csrf = result.csrf_token; notice(); await showWorkspace();
  } catch (error) { $('access-key').value = ''; displayError(error); }
  finally { button.disabled = false; }
});
$('sign-out').addEventListener('click', async () => {
  try { await request(`${API}/auth/session`, {method: 'DELETE', body: {}}); clearPrivate(); }
  catch (error) { displayError(error); }
});
$('refresh').addEventListener('click', () => loadActivity());
$('reload-settings').addEventListener('click', async () => {
  if (state.dirty && !confirm(COPY['dashboard.discard'])) return;
  await loadSettings();
});
$('status-filter').addEventListener('change', renderJobs);
$('next-page').addEventListener('click', async () => {
  if (state.next === null || state.loading) return;
  state.previous.push(state.cursor); state.cursor = String(state.next); await loadActivity();
});
$('previous-page').addEventListener('click', async () => {
  if (!state.previous.length || state.loading) return;
  state.cursor = state.previous.pop(); await loadActivity();
});
$('history-close').addEventListener('click', () => $('history-dialog').close());
$('history-dialog').addEventListener('close', () => { state.historyJob = null; state.historyVersion += 1; });
$('history-more').addEventListener('click', async () => {
  if (state.historyNext === null) return; state.historyCursor = state.historyNext; await loadHistory();
});
window.addEventListener('beforeunload', event => { if (state.dirty) { event.preventDefault(); event.returnValue = ''; } });
document.addEventListener('visibilitychange', () => { if (!document.hidden && state.csrf && state.page !== 'settings') loadActivity(); });
(async () => {
  try { const session = await request(`${API}/auth/session`); state.csrf = session.csrf_token; await showWorkspace(); }
  catch (error) { clearPrivate(error.status === 401 ? '' : error.message); }
})();
