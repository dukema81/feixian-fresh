# -*- coding: utf-8 -*-
"""飞系电商通用引擎：规格驱动的零依赖 REST 后端（Python 标准库 + SQLite）。
由 generate.py 按 spec.json 装配到各项目 backend/ 目录。"""
import json
import os
import sqlite3
import threading
import time
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

BASE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.environ.get("FEI_SPEC", os.path.join(BASE, "spec.json"))
DB_PATH = os.environ.get("FEI_DB", os.path.join(BASE, "data.db"))
FRONTEND_DIR = os.path.abspath(os.path.join(BASE, "..", "frontend"))

with open(SPEC_PATH, "r", encoding="utf-8") as f:
    SPEC = json.load(f)

TABLES = {t["name"]: t for t in SPEC["tables"]}
TYPES = {"text": "TEXT", "number": "REAL", "int": "INTEGER", "bool": "INTEGER"}
_lock = threading.Lock()
TOKENS = {}

TABLE_NAMES = {t["name"] for t in SPEC["tables"]}
HAS_PRODUCTS = "products" in TABLE_NAMES
HAS_ORDERS = "orders" in TABLE_NAMES
HAS_CART = "cart" in TABLE_NAMES


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _lock:
        conn = db()
        for name, t in TABLES.items():
            cols = ",".join(
                '"%s" %s' % (f["name"], TYPES.get(f.get("type", "text"), "TEXT"))
                for f in t["fields"]
            )
            conn.execute(
                'CREATE TABLE IF NOT EXISTS "%s" (id INTEGER PRIMARY KEY AUTOINCREMENT, %s)'
                % (name, cols)
            )
        for name, t in TABLES.items():
            if t.get("seed") and conn.execute(
                'SELECT COUNT(*) c FROM "%s"' % name
            ).fetchone()["c"] == 0:
                fields = [f["name"] for f in t["fields"]]
                ph = ",".join("?" * len(fields))
                for row in t["seed"]:
                    conn.execute(
                        'INSERT INTO "%s" (%s) VALUES (%s)'
                        % (name, ",".join(fields), ph),
                        row,
                    )
        # 家族规范：users 表密码一律哈希落库（含旧库明文迁移）
        if "users" in TABLES:
            for r in conn.execute("SELECT id, password FROM users").fetchall():
                if "$" not in (r["password"] or ""):
                    conn.execute(
                        "UPDATE users SET password=? WHERE id=?",
                        (_hash_pwd(r["password"]), r["id"]),
                    )
        conn.commit()
        conn.close()


def order_no():
    return time.strftime("SO%Y%m%d%H%M%S", time.localtime()) + str(int(time.time() * 1000) % 1000)


def _hash_pwd(pwd, salt=None):
    """飞系家族规范：密码以 salt$sha256hex(salt+pwd) 存储，绝不落明文。"""
    salt = salt or hashlib.md5(os.urandom(16)).hexdigest()[:12]
    digest = hashlib.sha256((salt + pwd).encode("utf-8")).hexdigest()
    return "%s$%s" % (salt, digest)


def _rank(user):
    """权限档位：admin=3 全权；ops/业务角色=2 读写不删；viewer=1 只读。"""
    return {"admin": 3, "ops": 2, "viewer": 1}.get(user.get("role", ""), 2)


def _fix_kw(kw):
    """兼容裸 UTF-8 查询串（curl 直连场景）；浏览器百分号编码由 parse_qs 正常解码。"""
    kw = (kw or "").strip()
    try:
        kw = kw.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    return kw


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return {}

    def _user(self):
        tok = (self.headers.get("Authorization") or "").replace("Bearer ", "")
        return TOKENS.get(tok)

    # ---------- static ----------
    def _static(self, path):
        if path in ("/", "/index.html"):
            fp = os.path.join(FRONTEND_DIR, "index.html")
            ctype = "text/html; charset=utf-8"
        elif path == "/app.js":
            fp = os.path.join(FRONTEND_DIR, "app.js")
            ctype = "application/javascript; charset=utf-8"
        elif path == "/icon.svg":
            fp = os.path.join(FRONTEND_DIR, "icon.svg")
            ctype = "image/svg+xml"
        else:
            self._json(404, {"error": "not found"})
            return
        with open(fp, "rb") as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ---------- GET ----------
    def do_GET(self):
        u = urlparse(self.path)
        parts = [p for p in u.path.split("/") if p]
        qs = parse_qs(u.query)
        try:
            if not parts or parts[0] != "api":
                return self._static(u.path)

            if len(parts) == 2 and parts[1] == "health":
                return self._json(200, {
                    "status": "ok",
                    "service": SPEC["brand"]["full"],
                    "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "db": os.path.exists(DB_PATH),
                })

            if len(parts) == 2 and parts[1] == "dashboard":
                user = self._user()
                if not user:
                    return self._json(401, {"error": "请先登录"})
                with _lock:
                    conn = db()
                    counts = {
                        t["label"]: conn.execute(
                            'SELECT COUNT(*) c FROM "%s"' % name
                        ).fetchone()["c"]
                        for name, t in TABLES.items()
                    }
                    dash = {"service": SPEC["brand"]["full"], "counts": counts, "role": user.get("role", "")}
                    today_prefix = "SO" + time.strftime("%Y%m%d")
                    if "orders" in TABLES:
                        row = conn.execute(
                            "SELECT COUNT(*) c, IFNULL(SUM(total),0) gmv FROM orders WHERE order_no LIKE ?",
                            (today_prefix + "%",),
                        ).fetchone()
                        dash["today_orders"] = row["c"]
                        dash["today_gmv"] = round(row["gmv"], 2)
                    if "products" in TABLES:
                        dash["low_stock"] = conn.execute(
                            "SELECT COUNT(*) c FROM products WHERE stock < 50"
                        ).fetchone()["c"]
                    conn.close()
                return self._json(200, dash)

            if len(parts) == 2 and parts[1] == "spec":
                return self._json(200, {"brand": SPEC["brand"], "tables": SPEC["tables"]})

            if len(parts) == 2 and parts[1] == "stats":
                with _lock:
                    conn = db()
                    counts = {}
                    for name, t in TABLES.items():
                        counts[t["label"]] = conn.execute(
                            'SELECT COUNT(*) c FROM "%s"' % name
                        ).fetchone()["c"]
                    conn.close()
                return self._json(200, counts)

            if len(parts) == 3 and parts[1] == "products" and parts[2] == "search":
                kw = _fix_kw(qs.get("q", [""])[0])
                with _lock:
                    conn = db()
                    rows = [
                        dict(r)
                        for r in conn.execute(
                            'SELECT * FROM products WHERE title LIKE ? OR category LIKE ? ORDER BY id DESC',
                            ("%" + kw + "%", "%" + kw + "%"),
                        )
                    ]
                    conn.close()
                return self._json(200, {"rows": rows, "total": len(rows)})

            if len(parts) == 1 and parts[0] == "orders":
                user = self._user()
                if not user:
                    return self._json(401, {"error": "请先登录"})
                with _lock:
                    conn = db()
                    rows = [
                        dict(r)
                        for r in conn.execute(
                            'SELECT * FROM orders WHERE user=? ORDER BY id DESC', (user["name"],)
                        )
                    ]
                    conn.close()
                return self._json(200, {"rows": rows, "total": len(rows)})

            if len(parts) == 2 and parts[1] == "cart":
                user = self._user()
                if not user:
                    return self._json(401, {"error": "请先登录"})
                with _lock:
                    conn = db()
                    rows = [
                        dict(r)
                        for r in conn.execute(
                            'SELECT * FROM cart WHERE user=? ORDER BY id DESC', (user["name"],)
                        )
                    ]
                    conn.close()
                return self._json(200, {"rows": rows, "total": len(rows)})

            tname = parts[1]
            if tname not in TABLES:
                return self._json(404, {"error": "unknown table %s" % tname})
            t = TABLES[tname]
            with _lock:
                conn = db()
                if len(parts) == 3:
                    row = conn.execute(
                        'SELECT * FROM "%s" WHERE id=?' % tname, (parts[2],)
                    ).fetchone()
                    conn.close()
                    if not row:
                        return self._json(404, {"error": "not found"})
                    return self._json(200, dict(row))
                kw = _fix_kw(qs.get("q", [""])[0])
                sql = 'SELECT * FROM "%s"' % tname
                args = []
                if kw:
                    texts = [
                        f["name"]
                        for f in t["fields"]
                        if f.get("type", "text") == "text"
                    ]
                    if texts:
                        sql += " WHERE " + " OR ".join(
                            '"%s" LIKE ?' % c for c in texts
                        )
                        args = ["%" + kw + "%"] * len(texts)
                sql += " ORDER BY id DESC LIMIT 500"
                rows = [dict(r) for r in conn.execute(sql, args)]
                conn.close()
            return self._json(200, {"rows": rows, "total": len(rows)})
        except Exception as e:
            return self._json(500, {"error": str(e)})

    # ---------- POST ----------
    def do_POST(self):
        u = urlparse(self.path)
        parts = [p for p in u.path.split("/") if p]
        body = self._body()
        try:
            if parts[:2] == ["api", "login"]:
                username = body.get("username", "")
                password = body.get("password", "")
                with _lock:
                    conn = db()
                    row = conn.execute(
                        "SELECT * FROM users WHERE username=?", (username,)
                    ).fetchone()
                    conn.close()
                if not row or "$" not in (row["password"] or ""):
                    return self._json(401, {"error": "账号或密码错误"})
                salt, digest = row["password"].split("$", 1)
                calc = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
                if calc != digest:
                    return self._json(401, {"error": "账号或密码错误"})
                tok = hashlib.md5(
                    ("%s:%s" % (username, time.time())).encode()
                ).hexdigest()
                TOKENS[tok] = {"name": username, "role": row["role"]}
                return self._json(200, {"token": tok, "user": username, "role": row["role"]})

            user = self._user()
            if not user:
                return self._json(401, {"error": "请先登录"})
            rank = _rank(user)

            if parts[:2] == ["api", "cart"]:
                if rank < 2:
                    return self._json(403, {"error": "viewer 只读，不可加购"})
                if not HAS_CART or not HAS_PRODUCTS:
                    return self._json(404, {"error": "no cart"})
                with _lock:
                    conn = db()
                    pid = body.get("product_id")
                    qty = int(body.get("qty") or 1)
                    prod = conn.execute(
                        "SELECT * FROM products WHERE id=?", (pid,)
                    ).fetchone()
                    if not prod:
                        conn.close()
                        return self._json(404, {"error": "商品不存在"})
                    old = conn.execute(
                        "SELECT * FROM cart WHERE user=? AND product_id=?",
                        (user["name"], pid),
                    ).fetchone()
                    if old:
                        conn.execute(
                            "UPDATE cart SET qty=qty+? WHERE id=?",
                            (qty, old["id"]),
                        )
                        cid = old["id"]
                    else:
                        cur = conn.execute(
                            "INSERT INTO cart (user, product_id, qty) VALUES (?,?,?)",
                            (user["name"], pid, qty),
                        )
                        cid = cur.lastrowid
                    conn.commit()
                    row = dict(conn.execute("SELECT * FROM cart WHERE id=?", (cid,)).fetchone())
                    conn.close()
                return self._json(200, row)

            if parts[:2] == ["api", "checkout"]:
                if rank < 2:
                    return self._json(403, {"error": "viewer 只读，不可下单"})
                if not (HAS_ORDERS and HAS_PRODUCTS):
                    return self._json(404, {"error": "no order flow"})
                items = body.get("items") or []
                address = body.get("address", "")
                if not items:
                    return self._json(400, {"error": "购物车为空"})
                with _lock:
                    conn = db()
                    total, lines = 0.0, []
                    for it in items:
                        pid = it.get("product_id")
                        qty = int(it.get("qty") or 1)
                        prod = conn.execute(
                            "SELECT * FROM products WHERE id=?", (pid,)
                        ).fetchone()
                        if not prod:
                            conn.close()
                            return self._json(404, {"error": "商品 %s 不存在" % pid})
                        price = prod["price"] if "price" in prod.keys() else 0
                        total += float(price) * qty
                        lines.append(
                            "%s x%d" % (prod["title"] if "title" in prod.keys() else pid, qty)
                        )
                        if "stock" in prod.keys():
                            conn.execute(
                                "UPDATE products SET stock=stock-? WHERE id=?", (qty, pid)
                            )
                    no = order_no()
                    conn.execute(
                        'INSERT INTO orders (order_no, user, items, total, address, status) '
                        'VALUES (?,?,?,?,?,?)',
                        (no, user["name"], ";".join(lines), round(total, 2), address, "待支付"),
                    )
                    if HAS_CART:
                        conn.execute("DELETE FROM cart WHERE user=?", (user["name"],))
                    conn.commit()
                    row = dict(
                        conn.execute(
                            "SELECT * FROM orders WHERE order_no=?", (no,)
                        ).fetchone()
                    )
                    conn.close()
                return self._json(200, row)

            if len(parts) == 4 and parts[1] == "orders" and parts[3] == "pay":
                if rank < 2:
                    return self._json(403, {"error": "viewer 只读，不可支付"})
                with _lock:
                    conn = db()
                    cur = conn.execute(
                        "UPDATE orders SET status='已支付' WHERE id=? AND status='待支付'",
                        (parts[2],),
                    )
                    conn.commit()
                    row = conn.execute(
                        "SELECT * FROM orders WHERE id=?", (parts[2],)
                    ).fetchone()
                    conn.close()
                if not cur.rowcount or not row:
                    return self._json(400, {"error": "订单不可支付"})
                return self._json(200, dict(row))

            tname = parts[1] if len(parts) > 1 else ""
            if tname not in TABLES:
                return self._json(404, {"error": "unknown table %s" % tname})
            t = TABLES[tname]
            names = [f["name"] for f in t["fields"]]
            vals = [body.get(n) for n in names]
            if rank < 2:
                return self._json(403, {"error": "viewer 只读，不可新增"})
            with _lock:
                conn = db()
                cur = conn.execute(
                    'INSERT INTO "%s" (%s) VALUES (%s)'
                    % (tname, ",".join(names), ",".join("?" * len(names))),
                    vals,
                )
                conn.commit()
                row = dict(
                    conn.execute(
                        'SELECT * FROM "%s" WHERE id=?' % tname, (cur.lastrowid,)
                    ).fetchone()
                )
                conn.close()
            return self._json(200, row)
        except Exception as e:
            return self._json(500, {"error": str(e)})

    # ---------- PUT ----------
    def do_PUT(self):
        u = urlparse(self.path)
        parts = [p for p in u.path.split("/") if p]
        body = self._body()
        if not self._user():
            return self._json(401, {"error": "请先登录"})
        if _rank(self._user()) < 2:
            return self._json(403, {"error": "viewer 只读，不可修改"})
        try:
            tname = parts[1] if len(parts) > 1 else ""
            if tname not in TABLES or len(parts) != 3:
                return self._json(404, {"error": "not found"})
            t = TABLES[tname]
            sets = [
                '"%s"=?' % n
                for n in [f["name"] for f in t["fields"]]
                if n in body
            ]
            vals = [body[n] for n in [f["name"] for f in t["fields"]] if n in body]
            if not sets:
                return self._json(400, {"error": "no fields"})
            with _lock:
                conn = db()
                conn.execute(
                    'UPDATE "%s" SET %s WHERE id=?' % (tname, ",".join(sets)),
                    vals + [parts[2]],
                )
                conn.commit()
                row = conn.execute(
                    'SELECT * FROM "%s" WHERE id=?' % tname, (parts[2],)
                ).fetchone()
                conn.close()
            if not row:
                return self._json(404, {"error": "not found"})
            return self._json(200, dict(row))
        except Exception as e:
            return self._json(500, {"error": str(e)})

    # ---------- DELETE ----------
    def do_DELETE(self):
        u = urlparse(self.path)
        parts = [p for p in u.path.split("/") if p]
        if not self._user():
            return self._json(401, {"error": "请先登录"})
        if _rank(self._user()) < 3:
            return self._json(403, {"error": "仅 admin 可删除"})
        try:
            tname = parts[1] if len(parts) > 1 else ""
            if tname not in TABLES or len(parts) != 3:
                return self._json(404, {"error": "not found"})
            with _lock:
                conn = db()
                conn.execute('DELETE FROM "%s" WHERE id=?' % tname, (parts[2],))
                conn.commit()
                conn.close()
            return self._json(200, {"ok": True})
        except Exception as e:
            return self._json(500, {"error": str(e)})


def run():
    init_db()
    port = int(os.environ.get("FEI_PORT") or SPEC["brand"].get("port") or 8101)
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print("%s 后端已启动: http://127.0.0.1:%d/  (三角色: admin/admin123, ops01/ops123456, view01/view123456)"
          % (SPEC["brand"]["full"], port))
    srv.serve_forever()
