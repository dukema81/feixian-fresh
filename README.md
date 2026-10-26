# 飞鲜生鲜电商

> 产地直发 · 明日鲜达

零依赖（Python 标准库 + SQLite）的 飞鲜，飞系电商系列成员。

## 运行

```bash
cd backend
python server.py
# 访问 http://127.0.0.1:8109/ ，三角色: admin/admin123 · ops01/ops123456 · view01/view123456
```

## 测试

```bash
python -m pytest tests/ -q
```

## 目录

- backend/  通用引擎 engine.py + 规格 spec.json + 服务入口 server.py
- frontend/ 原生 JS SPA（门店 + 统计 + 规格驱动后台）
- tools/    专属 Logo（icon.svg）+ UI 巡检（ui_check.py，零依赖探活+截图）
- docs/     建设方案
- tests/    API 集成测试（真实起服务全链路断言）
