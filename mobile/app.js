window.TABLE_ICONS = {"products": "🛍️", "goods": "🛍️", "live_rooms": "📺", "rooms": "📺", "live_comments": "💬", "comments": "💬", "cart": "🛒", "orders": "🧾", "users": "👥", "group_buys": "🔥", "coupons": "🎟️", "stores": "🏪", "suppliers": "🏭", "members": "💳", "skus": "📦", "posts": "📝", "deliveries": "🚚", "warehouses": "🏬", "brands": "🏷️", "customs": "🛃", "riders": "🛵", "categories": "🗂️", "reviews": "⭐"};
var CFG = window.APP_CONFIG;
var TOKEN_KEY = CFG.key + '_m_token';
var CUR = 'dash', ROWS = [];
var $ = function (s) { return document.querySelector(s); };

function api(path, opt) {
  opt = opt || {};
  opt.headers = { 'Content-Type': 'application/json' };
  var t = localStorage.getItem(TOKEN_KEY);
  if (t) opt.headers['Authorization'] = 'Bearer ' + t;
  if (opt.body) opt.body = JSON.stringify(opt.body);
  return fetch(CFG.base + 'api/' + path, opt)
    .then(function (r) { return r.json().then(function (j) { return { status: r.status, j: j }; }); })
    .then(function (o) {
      if (o.status >= 400) throw (o.j && (o.j.error || o.j.message)) || ('HTTP ' + o.status);
      return o.j;
    });
}

function icon(k) { return (window.TABLE_ICONS || {})[k] || '📋'; }

function renderTabs() {
  var tabs = [{ k: 'dash', icon: '📊', label: '工作台' }].concat(
    CFG.entities.map(function (e) { return { k: e.name, icon: icon(e.name), label: e.label }; }),
    [{ k: 'me', icon: '👤', label: '我的' }]);
  $('#tabs').innerHTML = tabs.map(function (t) {
    return '<a data-k="' + t.k + '" class="' + (t.k === CUR ? 'on' : '') + '"><i>' + t.icon + '</i>' + t.label + '</a>';
  }).join('');
  $('#tabs').onclick = function (ev) {
    var a = ev.target.closest('a'); if (!a) return;
    CUR = a.dataset.k; renderTabs();
    if (CUR === 'dash') dashView();
    else if (CUR === 'me') meView();
    else listView();
  };
}

function dashView() {
  $('#pg').textContent = '工作台';
  $('#view').innerHTML = '<div class="kpis">加载中…</div>';
  api('dashboard').then(function (d) {
    var kpis = [];
    Object.keys(d.counts || {}).forEach(function (k) { kpis.push({ value: d.counts[k], label: k }); });
    if (d.today_orders !== undefined) kpis.push({ value: d.today_orders, label: '今日订单' });
    if (d.today_gmv !== undefined) kpis.push({ value: '¥' + d.today_gmv, label: '今日GMV' });
    if (d.low_stock !== undefined) kpis.push({ value: d.low_stock, label: '低库存' });
    $('#view').innerHTML = '<div class="kpis">' + kpis.map(function (k) {
      return '<div class="kpi"><b>' + k.value + '</b><span>' + k.label + '</span></div>';
    }).join('') + '</div><div class="intro"><b>' + CFG.name + '</b><br>' + CFG.intro + '</div>';
  }).catch(function (m) { $('#view').innerHTML = '<div class="empty">' + m + '</div>'; });
}

function ent() { return CFG.entities.find(function (e) { return e.name === CUR; }); }

function listView() {
  var e = ent();
  $('#pg').textContent = icon(e.name) + ' ' + e.label;
  $('#view').innerHTML = '<input class="search" id="q" placeholder="搜索' + e.label + '…"><div id="rows" class="empty">加载中…</div>';
  loadRows('');
  $('#q').oninput = function () { loadRows(this.value.trim()); };
}

function loadRows(q) {
  var e = ent();
  api(e.name + (q ? '?q=' + encodeURIComponent(q) : '')).then(function (d) {
    ROWS = d.rows || d.items || [];
    if (!ROWS.length) { $('#rows').className = 'empty'; $('#rows').textContent = '暂无数据'; return; }
    $('#rows').className = '';
    $('#rows').innerHTML = ROWS.map(function (r) {
      return '<div class="card"><h3>#' + r.id + '</h3>' + e.fields.map(function (f) {
        var v = r[f.name]; if (v === null || v === undefined || v === '') return '';
        return '<div class="line"><i>' + f.label + '</i><b>' + v + '</b></div>';
      }).join('') + '</div>';
    }).join('');
  }).catch(function (m) { $('#rows').textContent = m; $('#rows').className = 'empty'; });
}

function meView() {
  var u = localStorage.getItem(TOKEN_KEY + '_u') || 'admin';
  $('#pg').textContent = '我的';
  $('#view').innerHTML = '<div class="me-card"><img src="icon.svg" width="72" height="72"><h2>' + u + '</h2>' +
    '<p>' + CFG.name + '<br>' + CFG.base + '</p><button id="out">退出登录</button></div>';
  $('#out').onclick = function () { localStorage.removeItem(TOKEN_KEY); localStorage.removeItem(TOKEN_KEY + '_u'); location.reload(); };
}

$('#lgf').onsubmit = function (e) {
  e.preventDefault();
  api('login', { method: 'POST', body: { username: $('#lg-u').value, password: $('#lg-p').value } })
    .then(function (d) {
      localStorage.setItem(TOKEN_KEY, d.token);
      localStorage.setItem(TOKEN_KEY + '_u', d.user || $('#lg-u').value);
      enter();
    })
    .catch(function (m) { $('#lg-err').textContent = m; });
};

function enter() {
  api('spec').then(function (s) {
    CFG.entities = (s.tables || []).filter(function (t) { return t.name !== 'users'; });
    CFG.name = s.brand.name; CFG.intro = s.brand.tagline || '';
    $('#lg').hidden = true; $('#main').hidden = false;
    renderTabs(); dashView();
  }).catch(function (m) { $('#lg-err').textContent = m; localStorage.removeItem(TOKEN_KEY); });
}

if (localStorage.getItem(TOKEN_KEY)) enter();
