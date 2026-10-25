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
    this.listeners = {}; this.value = ''; this.hidden = false;
    this.classList = {toggle() {}, add() {}};
  }
  set innerHTML(value) { throw new Error('Untrusted HTML must never be inserted'); }
  appendChild(child) { this.children.push(child); return child; }
  replaceChildren(...children) { this.children = children; }
  setAttribute(name, value) { this.attributes[name] = value; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  querySelectorAll() { return []; }
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
      createElement: tag => new Element(tag), querySelectorAll: () => [], addEventListener() {}, hidden: false,
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


test('credential editors live in their integration panels, not a separate page section', async () => {
  const h = await harness();
  const services = ['shoko', 'jellyfin', 'sonarr', 'tvdb', 'qbittorrent', 'access'];
  h.run(`state.credentials = {
    revision: 1, shoko_configured: false, jellyfin_configured: true,
    sonarr_configured: true, tvdb_api_key_configured: false,
    qbittorrent_configured: true, webhook_configured: false
  }; renderCredentials();`);
  const container = h.elements.get('settings-fields');
  assert.deepEqual(container.children.map(panel => panel.dataset.section), services);
  for (const panel of container.children) {
    assert.equal(panel.tagName, 'details');
    assert.equal(panel.children[1].tagName, 'form');
  }
  const qb = container.children.find(panel => panel.dataset.section === 'qbittorrent');
  const qbForm = qb.children[1];
  assert.ok(qbForm.children.some(child => child.children.some(field => field.name === 'username')));
  assert.ok(qbForm.children.some(child => child.children.some(field => field.name === 'password')));
  const html = fs.readFileSync(path.join(__dirname, '../dashboard/static/index.html'), 'utf8');
  assert.doesNotMatch(html, /id="credential-forms"|<h2>Private credentials<\/h2>/);
});
