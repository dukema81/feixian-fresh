/* 飞系电商规格驱动 SPA：门店（逛店/购物车/下单）+ 后台（规格表 CRUD/统计） */
let SPEC = null, token = localStorage.getItem("fei_token") || "", user = localStorage.getItem("fei_user") || "";
let view = "store", currentTable = null, cart = [];

const $ = (s) => document.querySelector(s);
const api = async (path, opts = {}) => {
  const res = await fetch("api" + path, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: "Bearer " + token } : {}),
      ...(opts.headers || {}),
    },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || res.status);
  return data;
};
const toast = (msg) => {
  const d = document.createElement("div");
  d.className = "toast"; d.textContent = msg;
  document.body.appendChild(d);
  setTimeout(() => d.remove(), 1800);
};

async function boot() {
  SPEC = await api("/spec");
  $("#logo").src = "icon.svg";
  $("#brandName").textContent = SPEC.brand.name;
  $("#brandTag").textContent = SPEC.brand.tagline;
  document.title = SPEC.brand.full;
  if (user) { $("#whoami").textContent = user; $("#btnLogin").textContent = "退出"; }
  renderTabs(); render();
}

function renderTabs() {
  const tabs = $("#tabs");
  tabs.innerHTML = "";
  const mk = (label, fn, on) => {
    const b = document.createElement("button");
    b.textContent = label; b.onclick = fn;
    if (on) b.className = "on";
    tabs.appendChild(b);
  };
  if (SPEC.tables.some((t) => t.name === "products"))
    mk("门店", () => { view = "store"; currentTable = null; renderTabs(); render(); }, view === "store");
  mk("统计", () => { view = "stats"; currentTable = null; renderTabs(); render(); }, view === "stats");
  for (const t of SPEC.tables)
    mk(t.label, () => { view = "table"; currentTable = t.name; renderTabs(); render(); }, view === "table" && currentTable === t.name);
}

function render() {
  const m = $("#main");
  m.innerHTML = "";
  if (view === "store") return renderStore(m);
  if (view === "stats") return renderStats(m);
  if (view === "table") return renderTable(m, currentTable);
}

/* ---------- 门店 ---------- */
async function renderStore(m) {
  const bar = document.createElement("div");
  bar.className = "toolbar";
  bar.innerHTML = '<input id="kw" placeholder="搜索商品…" style="width:280px"> <button class="primary" id="go">搜索</button>';
  m.appendChild(bar);
  const grid = document.createElement("div");
  grid.className = "grid"; m.appendChild(grid);
  const load = async (kw) => {
    const data = kw
      ? await api("/products/search?q=" + encodeURIComponent(kw))
      : await api("/products");
    grid.innerHTML = "";
    for (const p of data.rows) {
      const c = document.createElement("div");
      c.className = "card";
      c.innerHTML = `<h4>${p.title}</h4><div class="price">¥${p.price}</div>
        <div class="meta">${p.category || ""}${p.stock != null ? " · 库存 " + p.stock : ""}</div>`;
      const btn = document.createElement("button");
      btn.className = "primary"; btn.textContent = "加入购物车";
      btn.onclick = () => addToCart(p);
      c.appendChild(btn);
      grid.appendChild(c);
    }
  };
  bar.querySelector("#go").onclick = () => load(bar.querySelector("#kw").value.trim());
  bar.querySelector("#kw").onkeydown = (e) => { if (e.key === "Enter") load(e.target.value.trim()); };
  await load("");
}

async function addToCart(p) {
  if (!user) return openLogin();
  const r = await api("/cart", { method: "POST", body: { product_id: p.id, qty: 1 } });
  const line = cart.find((x) => x.product_id === p.id);
  if (line) line.qty += 1; else cart.push({ product_id: p.id, title: p.title, price: p.price, qty: 1 });
  toast("已加入购物车（购物车记录 #" + r.id + "）");
}

function openCart() {
  if (!user) return openLogin();
  const data = api("/cart");
  data.then(async (res) => {
    const rows = res.rows;
    const prods = await api("/products");
    const pmap = {};
    prods.rows.forEach((p) => (pmap[p.id] = p));
    let html = "<h3>购物车</h3>";
    let total = 0;
    for (const r of rows) {
      const p = pmap[r.product_id] || {};
      const line = (p.price || 0) * r.qty;
      total += line;
      html += `<div class="cart-line"><span>${p.title || "#" + r.product_id} × ${r.qty}</span><span>¥${line.toFixed(2)}</span></div>`;
    }
    html += `<div class="cart-line"><b>合计</b><b>¥${total.toFixed(2)}</b></div>
      <div class="form-row" style="margin-top:12px"><label>收货地址</label><input id="addr" placeholder="省市区 + 详细地址"></div>`;
    html += '<button class="primary" id="ck" style="width:100%">提交订单</button>';
    openModal(html);
    $("#ck").onclick = async () => {
      const address = $("#addr").value.trim();
      if (!address) return toast("请填收货地址");
      const r = await api("/checkout", {
        method: "POST",
        body: { items: rows.map((x) => ({ product_id: x.product_id, qty: x.qty })), address },
      });
      closeModal(); cart = []; toast("下单成功，订单号 " + r.order_no);
      render();
    };
  });
}

/* ---------- 统计 ---------- */
async function renderStats(m) {
  const s = await api("/stats");
  const row = document.createElement("div");
  row.className = "stat-row";
  for (const [k, v] of Object.entries(s)) {
    row.innerHTML += `<div class="stat"><b>${v}</b><span>${k}</span></div>`;
  }
  m.appendChild(row);
}

/* ---------- 规格表 CRUD ---------- */
async function renderTable(m, tname) {
  const t = SPEC.tables.find((x) => x.name === tname);
  const bar = document.createElement("div");
  bar.className = "toolbar";
  bar.innerHTML = `<input id="q" placeholder="搜索…" style="width:240px"> <button class="primary" id="add">+ 新增${t.label}</button>`;
  m.appendChild(bar);
  const wrap = document.createElement("div");
  m.appendChild(wrap);
  const load = async (kw) => {
    const data = await api("/" + tname + (kw ? "?q=" + encodeURIComponent(kw) : ""));
    const cols = t.fields.map((f) => f.label);
    let html = "<table><tr><th>ID</th>" + cols.map((c) => "<th>" + c + "</th>").join("") + "<th>操作</th></tr>";
    for (const r of data.rows) {
      html += `<tr><td>${r.id}</td>` + t.fields.map((f) => `<td>${r[f.name] ?? ""}</td>`).join("")
        + `<td><button data-e="${r.id}">编辑</button> <button class="danger" data-d="${r.id}">删除</button></td></tr>`;
    }
    html += "</table>";
    wrap.innerHTML = html;
    wrap.querySelectorAll("[data-d]").forEach((b) => (b.onclick = async () => {
      await api("/" + tname + "/" + b.dataset.d, { method: "DELETE" });
      toast("已删除"); load($("#q").value.trim());
    }));
    wrap.querySelectorAll("[data-e]").forEach((b) => (b.onclick = () => {
      const r = data.rows.find((x) => x.id == b.dataset.e);
      openForm(t, r, () => load($("#q").value.trim()));
    }));
  };
  bar.querySelector("#add").onclick = () => openForm(t, null, () => load(""));
  bar.querySelector("#q").onkeydown = (e) => { if (e.key === "Enter") load(e.target.value.trim()); };
  await load("");
}

function openForm(t, row, done) {
  let html = `<h3>${row ? "编辑" : "新增"}${t.label}</h3>`;
  for (const f of t.fields) {
    const v = row ? row[f.name] ?? "" : "";
    if (f.type === "options" && f.options)
      html += `<div class="form-row"><label>${f.label}</label><select data-f="${f.name}">`
        + f.options.map((o) => `<option ${o === v ? "selected" : ""}>${o}</option>`).join("") + "</select></div>";
    else if (f.type === "text" && (f.name === "desc" || f.name === "items"))
      html += `<div class="form-row"><label>${f.label}</label><textarea data-f="${f.name}" rows="2">${v}</textarea></div>`;
    else
      html += `<div class="form-row"><label>${f.label}</label><input data-f="${f.name}" type="${f.type === "number" || f.type === "int" ? "number" : "text"}" value="${v}"></div>`;
  }
  html += '<button class="primary" id="save" style="width:100%">保存</button>';
  openModal(html);
  $("#save").onclick = async () => {
    const body = {};
    t.fields.forEach((f) => {
      const el = document.querySelector(`[data-f="${f.name}"]`);
      if (el) body[f.name] = f.type === "number" || f.type === "int" ? Number(el.value) : el.value;
    });
    if (row) await api("/" + t.name + "/" + row.id, { method: "PUT", body });
    else await api("/" + t.name, { method: "POST", body });
    closeModal(); toast("已保存"); done();
  };
}

/* ---------- 登录 / 弹窗 ---------- */
function openLogin() {
  openModal(`<h3>登录</h3>
    <div class="form-row"><label>用户名</label><input id="lu" value="admin"></div>
    <div class="form-row"><label>密码</label><input id="lp" type="password" value="admin123"></div>
    <p style="margin:4px 0 10px;font-size:12px;color:var(--muted,#6b7280)">三角色：admin/admin123（全权）· ops01/ops123456（读写）· view01/view123456（只读）</p>
    <button class="primary" id="doLogin" style="width:100%">登录</button>`);
  $("#doLogin").onclick = async () => {
    const r = await api("/login", { method: "POST", body: { username: $("#lu").value, password: $("#lp").value } });
    token = r.token; user = r.user;
    localStorage.setItem("fei_token", token);
    localStorage.setItem("fei_user", user);
    localStorage.setItem("fei_role", r.role || "");
    $("#whoami").textContent = user + (r.role ? "（" + r.role + "）" : "");
    $("#btnLogin").textContent = "退出";
    closeModal(); toast("欢迎，" + user);
  };
}

function openModal(html) {
  $("#modalRoot").innerHTML = `<div class="modal" id="mask"><div class="box">${html}</div></div>`;
  $("#mask").onclick = (e) => { if (e.target.id === "mask") closeModal(); };
}
function closeModal() { $("#modalRoot").innerHTML = ""; }

$("#btnLogin").onclick = () => {
  if (user) {
    token = ""; user = "";
    localStorage.removeItem("fei_token"); localStorage.removeItem("fei_user");
    $("#whoami").textContent = ""; $("#btnLogin").textContent = "登录";
  } else openLogin();
};
$("#btnCart").onclick = openCart;

boot().catch((e) => { $("#main").innerHTML = "<p>加载失败：" + e.message + "</p>"; });
