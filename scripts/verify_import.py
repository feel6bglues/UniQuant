#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""兼容入口: 深度抽样校验。"""

from verify_tdx_import import main


if __name__ == "__main__":
    main(["--mode", "deep", "--sample-size", "500"])
