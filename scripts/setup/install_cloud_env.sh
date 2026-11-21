#!/usr/bin/env bash
# ==============================================================================
# UniQuant 云主机环境自动化安装脚本 (Idempotent Cloud Host Setup)
# 适用环境: Linux (Ubuntu 22.04+ / Debian 12+), x86_64
# 部署形态: 云主机 + pip 直装 + systemd/cron (免 Docker 裁决定稿)
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

echo "=== [1/5] 检查系统环境与基础依赖 ==="
if command -v apt-get >/dev/null 2>&1; then
    echo "检测到 apt-get 包管理器，安装系统级 C 库与中文字体支持..."
    sudo apt-get update -y
    sudo apt-get install -y \
        build-essential \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libpangocairo-1.0-0 \
        libgdk-pixbuf-2.0-0 \
        libxml2-dev \
        libxslt1-dev \
        fonts-wqy-zenhei \
        fonts-wqy-microhei
else
    echo "提示: 未检测到 apt-get，请确保系统已安装 pango, cairo, gdk-pixbuf 与中文字体。"
fi

echo "=== [2/5] 确保目录与用户配置完整性 ==="
mkdir -p "${HOME}/.mootdx/caches" "${HOME}/.mootdx/xdxr"
mkdir -p "${REPO_ROOT}/data/lake" \
         "${REPO_ROOT}/data/cache" \
         "${REPO_ROOT}/data/state" \
         "${REPO_ROOT}/logs" \
         "${REPO_ROOT}/results"

echo "=== [3/5] 安装 Python 核心包及开发依赖 (pip -e) ==="
cd "${REPO_ROOT}"
python3 -m pip install --upgrade pip setuptools wheel
python3 -m pip install -e ".[all,dev]"

echo "=== [4/5] 依赖一致性与导入冒烟核验 ==="
python3 -m pip check

python3 -c "
import polars as pl
import tdxdata
import mootdx
import numpy as np
import pandas as pd
print('基础量化运行时库导入成功: polars', pl.__version__, '| pandas', pd.__version__)
"

echo "=== [5/5] 云环境安装完成！==="
echo "可在项目根目录运行: pytest tests/ -q"
