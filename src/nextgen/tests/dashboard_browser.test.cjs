/* Offline UI behavior with a minimal DOM/Fetch double, not a real-browser test.
 * Authored only: tests and CI remain unexecuted under the project policy.
 */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

class Element {
  constructor(tag = 'div') {
    this.tagName = tag; this.children = []; this.dataset = {}; this.attributes = {};
    this.listeners = {}; this.value = ''; this.hidden = false; this.checked = false;
    this.classList = {toggle() {}, add() {}};
  }
  set innerHTML(value) { throw new Error('Untrusted HTML must never be inserted'); }
  appendChild(child) { this.children.push(child); return child; }
  replaceChildren(...children) { this.children = children; }
  setAttribute(name, value) { this.attributes[name] = value; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  querySelectorAll(selector) {
    const matches = element => {
      if (selector === 'form.integration') return element.tagName === 'form' && element.className === 'integration';
      if (selector === '[data-kind]') return Boolean(element.dataset.kind);
      if (selector === '[data-secret]') return Boolean(element.dataset.secret);
      return false;
    };
    const result = [];
    const walk = element => {
      for (const child of element.children) { if (matches(child)) result.push(child); walk(child); }
    };
    walk(this);
    return result;
  }
  querySelector() { return new Element('button'); }
  showModal() { this.open = true; }
  close() { this.open = false; this.listeners.close?.(); }
}
function response(data, status = 200) {
  return {ok: status < 400, status, json: async () => status < 400 ? {data} : {error: {message: data}}};
}
async function harness() {
  const elements = new Map();
  const ctx = vm.createContext({
    document: {
      getElementById(id) { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); },
      createElement: tag => new Element(tag), createElementNS: (_, tag) => new Element(tag),
      querySelectorAll: selector => elements.get('settings-fields')?.querySelectorAll(selector) || [],
      addEventListener() {}, hidden: false,
    },
    window: {addEventListener() {}}, location: {pathname: '/'},
    URL, AbortController, DOMException, console, confirm: () => true,
    setTimeout: () => 1, clearTimeout() {},
    fetch: async () => response('Authentication is required.', 401),
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../dashboard/static/dashboard.js'), 'utf8'), ctx);
  await new Promise(resolve => setImmediate(resolve));
  vm.runInContext("state.csrf='session-csrf';", ctx);
  return {ctx, elements, run: code => vm.runInContext(code, ctx)};
}
function target() {
  return {job_id: 7, state: 'DONE', status: {message: 'Completed'}, label: {message: 'Reserve episode'},
    cancellation: {operation_id: 3, state: 'ACTIVE'}, acquisition_status: {message: 'Not staged'},
    actions: {keep: {enabled: false, execution_available: false, availability_reason: {message: 'Keeping videos is not available yet.'}},
      cancel: {enabled: true, disabled_reason: null}, cleanup: {enabled: false}},
    release_name: '<img src=x onerror=alert(1)>', is_management_action: false};
}
test('disabled buttons explain the running job before unavailable Keep execution', async () => {
  const h = await harness(); h.ctx.fixture = target();
  h.ctx.fixture.actions.keep.disabled_reason = {message: 'A job is already in progress.'};
  const wrapper = h.run("actionButton(fixture,'keep','Keep')");
  assert.equal(wrapper.children[0].disabled, true);
  assert.equal(wrapper.title, 'A job is already in progress.');
  assert.equal(wrapper.tabIndex, 0);
});
test('double clicks send one CSRF-protected cancellation and reconcile with GET', async () => {
  const h = await harness(); h.ctx.fixture = target();
  let release; const waiting = new Promise(resolve => { release = resolve; });
  const calls = [];
  h.ctx.fetch = async (url, options) => {
    calls.push({url, options});
    if (options.method === 'POST') {
      await waiting;
      return response({notification: {message: 'Job submitted.'}, job_id: 8});
    }
    return response({items: [], next_before_id: null});
  };
  const first = h.run("submitAction(fixture,'cancel')");
  await h.run("submitAction(fixture,'cancel')");
  assert.equal(calls.length, 1);
  assert.equal(calls[0].options.headers['X-CSRF-Token'], 'session-csrf');
  assert.equal(calls[0].options.credentials, 'same-origin');
  assert.deepEqual(JSON.parse(calls[0].options.body), {});
  release(); await first;
  assert.equal(calls.filter(c => c.options.method === 'POST').length, 1);
  assert.ok(calls.some(c => c.url.startsWith('/api/v1/intake?')));
  assert.equal(h.elements.get('notice').textContent, 'Job submitted.');
});
test('uncertain mutation is never automatically replayed', async () => {
  const h = await harness(); h.ctx.fixture = target();
  let posts = 0;
  h.ctx.fetch = async (url, options) => {
    if (options.method === 'POST') { posts += 1; throw new Error('lost response'); }
    return response({items: [], next_before_id: null});
  };
  await h.run("submitAction(fixture,'cancel')");
  assert.equal(posts, 1);
  assert.match(h.elements.get('notice').textContent, /Refresh the job status/);
});
test('release text is rendered as text and Keep never submits while execution is unavailable', async () => {
  const h = await harness(); h.ctx.fixture = target();
  h.run('state.jobs=[fixture]; renderJobs();');
  const text = element => [element.textContent || '', ...element.children.map(text)].join(' ');
  assert.ok(text(h.elements.get('job-rows')).includes(h.ctx.fixture.release_name));
  h.ctx.fetch = async () => { throw new Error('Keep must not send a request'); };
  await h.run("submitAction(fixture,'keep')");
});
test('session expiry clears private rows and in-memory session state', async () => {
  const h = await harness(); h.ctx.fixture = target();
  h.run('state.jobs=[fixture]; renderJobs();');
  h.ctx.fetch = async () => response('Authentication is required.', 401);
  await h.run('loadActivity()');
  assert.equal(h.run('state.csrf'), null);
  assert.equal(h.elements.get('job-rows').children.length, 0);
  assert.equal(h.elements.get('workspace').hidden, true);
  assert.equal(h.elements.get('login-panel').hidden, false);
});

test('dashboard login sends password, never the webhook or old management token field', async () => {
  const h = await harness();
  const requests = [];
  h.ctx.fetch = async (url, options) => {
    requests.push({url, options});
    if (url === '/api/v1/auth/session') return response({csrf_token: 'new-session-csrf', expires_in: 43200}, 201);
    return response({items: [], next_before_id: null});
  };
  h.elements.get('access-key').value = 'correct horse battery staple';
  const form = h.elements.get('login-form');
  await form.listeners.submit({preventDefault() {}, currentTarget: form});
  const login = requests.find(item => item.url === '/api/v1/auth/session');
  assert.ok(login);
  assert.deepEqual(JSON.parse(login.options.body), {password: 'correct horse battery staple'});
  assert.equal(login.options.credentials, 'same-origin');
  assert.equal(h.elements.get('access-key').value, '');
  assert.equal(h.run('state.csrf'), 'new-session-csrf');
});


function descendants(element) {
  return [element, ...element.children.flatMap(descendants)];
}
test('one save button per integration and credential inputs use an embedded eye', async () => {
  const h = await harness();
  const services = ['shoko', 'jellyfin', 'sonarr', 'tvdb', 'qbittorrent', 'access'];
  h.run("state.credentials = {revision: 1}; renderCredentials();");
  const container = h.elements.get('settings-fields');
  assert.deepEqual(container.children.map(panel => panel.dataset.section), services);
  for (const panel of container.children) {
    assert.equal(panel.tagName, 'details');
    const forms = panel.children.filter(child => child.tagName === 'form');
    assert.equal(forms.length, 1);
    const buttons = descendants(forms[0]).filter(el => el.tagName === 'button');
    assert.equal(buttons.filter(el => el.type === 'submit').length, 1);
    assert.equal(forms[0]._saveButton.textContent, 'Save changes');
    assert.equal(forms[0]._saveButton.disabled, true);
    assert.equal(buttons.some(el => el.textContent === 'Show saved credentials'), false);
    assert.equal(buttons.some(el => el.textContent === 'Replace credentials'), false);
  }
  const qb = container.children.find(panel => panel.dataset.section === 'qbittorrent');
  const inputs = descendants(qb).filter(el => el.dataset.secret);
  assert.deepEqual(inputs.map(input => input.name), ['username', 'password']);
  assert.equal(inputs[1].type, 'password');
  const html = fs.readFileSync(path.join(__dirname, '../dashboard/static/index.html'), 'utf8');
  assert.doesNotMatch(html, /id="credential-forms"|<h2>Private credentials<\/h2>/);
});

test('opening an integration populates masked saved values and editing enables saving', async () => {
  const h = await harness();
  h.run('state.credentials = {revision: 1, qbittorrent_configured: true}; renderCredentials();');
  const panel = h.elements.get('settings-fields').children.find(el => el.dataset.section === 'qbittorrent');
  const form = panel.children.find(el => el.tagName === 'form');
  const inputs = descendants(form).filter(el => el.dataset.secret);
  const toggle = descendants(form).find(el => el.className === 'credential-eye secondary');
  const requests = [];
  h.ctx.fetch = async (url, options) => {
    requests.push({url, options});
    if (url.endsWith('/reveal')) return response({username: 'alice', password: 'stored-password'});
    if (url === '/api/v1/credentials/qbittorrent' && options.method === 'PATCH')
      return response({status: {revision: 2, qbittorrent_configured: true}, durability_confirmed: true});
    throw Error('unexpected API request ' + url);
  };
  assert.equal(requests.length, 0, 'credentials must not load before opening panel');
  panel.open = true; panel.listeners.toggle();
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(inputs.map(input => input.value), ['alice', 'stored-password']);
  assert.equal(inputs[1].type, 'password');
  assert.equal(form._saveButton.disabled, true, 'loading values alone is not an edit');
  assert.equal(requests[0].url, '/api/v1/credentials/qbittorrent/reveal');
  assert.equal(requests[0].options.method, 'POST');
  assert.equal(requests[0].options.headers['X-CSRF-Token'], 'session-csrf');
  toggle.listeners.click();
  assert.equal(inputs[1].type, 'text');
  assert.equal(form._saveButton.disabled, true, 'visibility change is not an edit');
  toggle.listeners.click();
  assert.equal(inputs[1].type, 'password');
  inputs[1].value = 'updated-password';
  form.listeners.input();
  assert.equal(form._saveButton.disabled, false);
  await form.listeners.submit({preventDefault() {}});
  const patch = requests.find(call => call.options.method === 'PATCH');
  assert.deepEqual(JSON.parse(patch.options.body), {
    expected_revision: 1, username: 'alice', password: 'updated-password',
  });
  assert.equal(form._saveButton.disabled, true);
  assert.equal(inputs[1].value, 'updated-password');
  assert.equal(inputs[1].type, 'password');
  assert.equal(h.run('state.dirty'), false);
});

test('Matching details stays separate from History and renders recorded season checks as text', async () => {
  const h = await harness();
  const job = target();
  job.kind = 'IDENTIFY_ANIME';
  job.event_id = 1;
  job.state = 'NEEDS_REVIEW';
  job.reason = {message: 'Anime identification is incomplete.'};
  h.ctx.fixture = job;
  h.run('state.jobs = [fixture]; renderJobs();');
  const tr = h.elements.get('job-rows').children[0];
  const buttons = descendants(tr).filter(el => el.tagName === 'button');
  const matching = buttons.find(el => el.textContent === 'Matching details');
  assert.ok(matching);
  assert.ok(buttons.some(el => el.textContent === 'History'));
  const calls = [];
  h.ctx.fetch = async (url, options) => {
    calls.push({url, options});
    return response({
      job_id: 7, requested_job_id: 7, attempts: 1,
      state: 'NEEDS_REVIEW', reason: {message: 'Anime identification is incomplete.'},
      available: true, evidence: {
        version: 1, season: 2, episode: 1,
        queries: ['Higurashi When They Cry'],
        anidb_candidates: [], selected_anidb_id: null, selected_tvdb_id: null,
        tvdb_titles: [], checks: [
          {step: 'release_title', status: 'passed', note: null},
          {step: 'season_scope', status: 'failed', note: 'unverified_sequel'},
        ],
      },
    });
  };
  await matching.listeners.click();
  assert.equal(h.elements.get('matching-dialog').open, true);
  assert.equal(calls[0].url, '/api/v1/jobs/7/matching');
  assert.equal(calls[0].options.credentials, 'same-origin');
  const visible = descendants(h.elements.get('matching-body'))
    .map(item => item.textContent || '').join(' ');
  assert.match(visible, /Season 2/);
  assert.match(visible, /Release season compatibility/);
  assert.match(visible, /cannot safely inherit Season 1/);
  assert.match(visible, /No AniDB candidates recorded/);
  assert.equal(h.elements.get('history-dialog').open, undefined);
  h.elements.get('matching-dialog').close();
  assert.equal(h.elements.get('matching-body').children.length, 0);
});

test('Matching details does not fabricate evidence for older or queued jobs', async () => {
  const h = await harness();
  h.ctx.fetch = async () => response({
    job_id: 11, requested_job_id: 11, attempts: 1,
    state: 'NEEDS_REVIEW', reason: null, available: false, evidence: null,
  });
  await h.run('openMatching(11)');
  const text = descendants(h.elements.get('matching-body'))
    .map(item => item.textContent || '').join(' ');
  assert.match(text, /No detailed evidence was saved/);
});


test('checkpoint Retry posts the same reviewed job snapshot without restarting acquisition', async () => {
  const h = await harness();
  h.ctx.fixture = target();
  h.ctx.fixture.state = 'NEEDS_REVIEW';
  h.ctx.fixture.attempt_count = 4;
  h.ctx.fixture.reason = {code: 'JOB_RETRY_EXHAUSTED', message: 'Retry limit reached.'};
  h.ctx.fixture.actions.retry = {enabled: true, disabled_reason: null};
  h.run('state.jobs=[fixture]; renderJobs();');
  const rows = h.elements.get('job-rows');
  const text = element => [element.textContent || '', ...element.children.map(text)].join(' ');
  assert.ok(text(rows).includes('Retry'));
  const calls = [];
  h.ctx.fetch = async (url, options) => {
    calls.push({url, options});
    return response(url.includes('/retry') ? {notification:{message:'Job submitted.'},job_id:7} :
      {items:[],next_before_id:null});
  };
  await h.run("submitAction(fixture,'retry')");
  const sent = calls.filter(item => item.options.method === 'POST');
  assert.equal(sent.length,1);
  assert.equal(sent[0].url,'/api/v1/jobs/7/retry');
  assert.deepEqual(JSON.parse(sent[0].options.body),
    {expected_attempt:4,expected_reason:'JOB_RETRY_EXHAUSTED'});
  assert.equal(sent[0].options.headers['X-CSRF-Token'],'session-csrf');
});

test('Retry does not submit if the API capability disables the reviewed step', async () => {
  const h=await harness(); h.ctx.fixture=target();
  h.ctx.fixture.state='NEEDS_REVIEW';
  h.ctx.fixture.actions.retry={enabled:false,disabled_reason:{message:'This action is not available.'}};
  const button=h.run("actionButton(fixture,'retry','Retry')");
  assert.equal(button.children[0].disabled,true);
  assert.equal(button.title,'This action is not available.');
  h.ctx.fetch=async () => {throw Error('disabled Retry must not POST');};
  await h.run("submitAction(fixture,'retry')");
});

test('bulk UI uses individual endpoints for five jobs and queues a worker for six', async () => {
  for (const count of [5, 6]) {
    const h = await harness();
    h.run("state.page='jobs'; state.selected=new Set([" +
      Array.from({length: count}, (_, i) => i + 1).join(',') + "]);");
    h.elements.get('bulk-action').value = 'cancel';
    h.elements.get('show-completed').checked = false;
    h.elements.get('show-canceled').checked = false;
    const calls = [];
    h.ctx.fetch = async (url, options) => {
      calls.push({url, options});
      if (options.method === 'POST') {
        return response({job_id: 81, notification: {message: 'Job submitted.'}});
      }
      return response({items: [], next_before_id: null});
    };
    await h.run('submitSelected()');
    const posts = calls.filter(call => call.options.method === 'POST');
    assert.equal(posts.length, count <= 5 ? count : 1);
    if (count <= 5) {
      assert.deepEqual(posts.map(call => call.url), Array.from({length: count},
        (_, i) => '/api/v1/jobs/' + (i + 1) + '/cancel'));
      assert.ok(posts.every(call => call.options.headers['X-CSRF-Token'] === 'session-csrf'));
    } else {
      assert.equal(posts[0].url, '/api/v1/jobs/bulk');
      assert.deepEqual(JSON.parse(posts[0].options.body),
        {action: 'cancel', job_ids: [1,2,3,4,5,6]});
      assert.match(h.elements.get('notice').textContent, /Bulk job #81/);
    }
    assert.ok(calls.some(call => call.url.includes('show_completed=0&show_canceled=0')));
  }
});
test('selected jobs remain selected across filtered pages until explicitly cleared', async () => {
  const h = await harness();
  h.run("state.page='jobs'; state.selected=new Set([1,2]);");
  h.ctx.fixture = target();
  h.ctx.fixture.job_id = 7;
  h.ctx.fixture.state = 'PENDING';
  h.run("state.jobs=[fixture]; renderJobs();");
  assert.equal(h.elements.get('selection-count').textContent, '2 selected (max 100)');
  h.elements.get('select-page').checked = true;
  h.elements.get('select-page').listeners.change();
  assert.equal(h.run('state.selected.size'), 3);
  h.ctx.fetch = async () => response({items: [], next_before_id: null});
  h.elements.get('show-canceled').checked = true;
  await h.run('resetJobsPage()');
  assert.equal(h.run('state.selected.size'), 3);
  h.elements.get('bulk-clear').listeners.click();
  assert.equal(h.run('state.selected.size'), 0);
});
