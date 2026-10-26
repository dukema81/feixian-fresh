# -*- coding: utf-8 -*-
"""飞系电商服务入口：FEIWEI_<KEY>_PORT 环境变量或 spec.json 中的 port 决定端口。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import engine

if __name__ == "__main__":
    engine.run()
