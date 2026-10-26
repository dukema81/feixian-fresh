# -*- coding: utf-8 -*-
"""飞系电商 API 集成测试：真实起服务，全链路断言。"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
PORT = 8290
BASE = "http://127.0.0.1:%d" % PORT
TOKEN = {"t": ""}


def wait_port(timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection(("127.0.0.1", PORT), timeout=1):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def call(method, path, body=None):
    req = urllib.request.Request(BASE + "/api" + path, method=method)
    req.add_header("Content-Type", "application/json")
    if TOKEN["t"]:
        req.add_header("Authorization", "Bearer " + TOKEN["t"])
    data = json.dumps(body).encode("utf-8") if body is not None else None
    with urllib.request.urlopen(req, data) as resp:
        return json.loads(resp.read().decode("utf-8"))


def setup_module(module):
    import tempfile
    dbp = os.path.join(tempfile.mkdtemp(), "test.db")
    env = dict(os.environ, FEI_DB=dbp, FEI_PORT=str(PORT))
    module.proc = subprocess.Popen(
        [sys.executable, os.path.join(BACKEND, "server.py")], env=env
    )
    assert wait_port(), "server did not start"


def teardown_module(module):
    module.proc.terminate()
    module.proc.wait(timeout=5)


def test_spec_and_stats():
    spec = call("GET", "/spec")
    assert spec["brand"]["name"].startswith("飞")
    assert len(spec["tables"]) >= 3
    stats = call("GET", "/stats")
    assert any(v > 0 for v in stats.values())


def test_login_required():
    try:
        call("POST", "/products", {"title": "x"})
        assert False, "should be 401"
    except urllib.error.HTTPError as e:
        assert e.code == 401


def test_health_and_dashboard():
    with urllib.request.urlopen(BASE + "/api/health") as resp:
        h = json.loads(resp.read().decode("utf-8"))
    assert h["status"] == "ok" and h["service"].startswith("飞")
    TOKEN["t"] = call("POST", "/login", {"username": "admin", "password": "admin123"})["token"]
    d = call("GET", "/dashboard")
    assert "counts" in d and d["role"] == "admin"
    assert any(v > 0 for v in d["counts"].values())


def test_role_permissions():
    tname = _domain_table()
    # viewer：登录可读，写一律 403
    v = call("POST", "/login", {"username": "view01", "password": "view123456"})
    assert v["role"] == "viewer"
    TOKEN["t"] = v["token"]
    rows = call("GET", "/" + tname)["rows"]
    assert isinstance(rows, list)
    try:
        call("POST", "/" + tname, {"title": "x"})
        assert False, "viewer write should be 403"
    except urllib.error.HTTPError as e:
        assert e.code == 403
    # ops：可增改，不可删
    o = call("POST", "/login", {"username": "ops01", "password": "ops123456"})
    assert o["role"] == "ops"
    TOKEN["t"] = o["token"]
    row = call("POST", "/" + tname, {"title": "ops巡检", "price": 5, "stock": 5, "qty": 1,
                                     "status": "测试", "category": "测试", "condition": "全新", "desc": "x"})
    assert row["id"]
    try:
        call("DELETE", "/%s/%d" % (tname, row["id"]))
        assert False, "ops delete should be 403"
    except urllib.error.HTTPError as e:
        assert e.code == 403
    # admin 收尾清理
    TOKEN["t"] = call("POST", "/login", {"username": "admin", "password": "admin123"})["token"]
    call("DELETE", "/%s/%d" % (tname, row["id"]))


def _table_names():
    return {t["name"] for t in call("GET", "/spec")["tables"]}


def _domain_table():
    """返回可用于 CRUD 测试的业务表：优先 products，其次 items，再次任意非系统表。"""
    names = _table_names()
    for cand in ("products", "items"):
        if cand in names:
            return cand
    return next(n for n in sorted(names) if n not in ("users", "cart", "orders"))


def test_login_and_crud():
    r = call("POST", "/login", {"username": "admin", "password": "admin123"})
    assert r["token"]
    TOKEN["t"] = r["token"]
    tname = _domain_table()
    row = call("POST", "/" + tname, {"title": "测试商品", "price": 9.9, "stock": 100})
    assert row["id"]
    got = call("GET", "/%s/%d" % (tname, row["id"]))
    assert got["title"] == "测试商品"
    upd = call("PUT", "/%s/%d" % (tname, row["id"]), {"price": 19.9})
    assert upd["price"] == 19.9
    call("DELETE", "/%s/%d" % (tname, row["id"]))
    try:
        call("GET", "/%s/%d" % (tname, row["id"]))
        assert False
    except urllib.error.HTTPError as e:
        assert e.code == 404


def test_shop_flow():
    TOKEN["t"] = call("POST", "/login", {"username": "admin", "password": "admin123"})["token"]
    names = _table_names()
    if {"products", "cart", "orders"} <= names:
        p = call("POST", "/products", {"title": "流程商品", "price": 50, "stock": 10, "category": "测试"})
        cart = call("POST", "/cart", {"product_id": p["id"], "qty": 2})
        assert cart["qty"] == 2
        rows = call("GET", "/cart")["rows"]
        assert len(rows) >= 1
        order = call("POST", "/checkout", {"items": [{"product_id": p["id"], "qty": 2}], "address": "深圳市南山区"})
        assert order["status"] == "待支付"
        assert abs(order["total"] - 100) < 0.01
        paid = call("POST", "/orders/%d/pay" % order["id"])
        assert paid["status"] == "已支付"
        after = call("GET", "/products/%d" % p["id"])
        assert after["stock"] == 8
        mine = call("GET", "/orders")["rows"]
        assert any(o["order_no"] == order["order_no"] for o in mine)
        call("DELETE", "/products/%d" % p["id"])
    elif "trade_orders" in names:
        # 二手担保交易流：建闲置 → 建担保单 → 更新状态 → 我的核验
        item = call("POST", "/items", {"title": "测试闲置", "price": 100, "condition": "9成新"})
        assert item["id"]
        trade = call("POST", "/trade_orders", {"trade_no": "TDTEST001", "item_id": item["id"], "buyer": "admin", "status": "已托管", "amount": 100})
        assert trade["trade_no"] == "TDTEST001"
        upd = call("PUT", "/trade_orders/%d" % trade["id"], {"status": "已放款"})
        assert upd["status"] == "已放款"
        call("DELETE", "/items/%d" % item["id"])
        call("DELETE", "/trade_orders/%d" % trade["id"])
    else:
        # 兜底：业务表存在即可查询
        tname = _domain_table()
        rows = call("GET", "/" + tname)["rows"]
        assert isinstance(rows, list)
