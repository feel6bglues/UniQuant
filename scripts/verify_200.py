#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""兼容入口: 随机抽样 200 只股票验证。"""

from verify_tdx_import import main


if __name__ == "__main__":
    main(["--mode", "random-sample", "--sample-size", "200"])
