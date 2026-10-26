#!/usr/bin/env bash
# ==============================================================================
# UniQuant 生产运维与实盘交易日健康度一键巡检 SOP 脚本 (ops_health_check.sh)
#
# 使用方式:
#   bash scripts/monitoring/ops_health_check.sh
# 退出码:
#   0 - 全部质量门禁与运行时检查均通过 (GREEN / S+)
#   1 - 发现门禁不达标或运行时异常 (RED / 阻断上线)
# ==============================================================================

set -eo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${REPO_ROOT}"

echo "=============================================================================="
echo "【UniQuant 生产级系统全景穿透检测】时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo "=============================================================================="

echo ">>> [1/5] 执行 Ruff 静态代码规范检查..."
ruff check src/ tests/ scripts/
echo "    ✓ Ruff 检查全部通过 (All checks passed!)"

echo ">>> [2/5] 验证证据清单存证与 SSOT 主数据安全..."
python3 scripts/maintenance/evidence_manifest.py verify
if git status -s data/all_stock_codes.csv | grep -q .; then
    echo "    ✗ 严重错误: SSOT data/all_stock_codes.csv 被污染!"
    exit 1
fi
echo "    ✓ 证据清单无漂移，主数据干净无损"

echo ">>> [3/5] 执行分层架构门禁与死代码剪除守卫 (Round 8 / 9 / 17)..."
pytest tests/test_uniquant_production_architecture_gates.py \
       tests/test_no_dev_absolute_paths.py \
       tests/test_round8_pruned_modules_absent.py \
       tests/test_round9_pruned_modules_absent.py \
       tests/test_round17_pruned_modules_absent.py -q
echo "    ✓ 架构与三轮死代码剪除守卫全部绿灯"

echo ">>> [4/5] 验证全市场 Dynamic PIT 跨截面因果引擎计算性能..."
PIT_LOG=$(mktemp)
python3 scripts/backtest/run_full_market_dynamic_pit.py --start-year 2024 --end-year 2024 --top-n 40 > "${PIT_LOG}"
if grep -q "step_latency_ms" "${PIT_LOG}"; then
    LATENCY=$(grep -E "^ +2024" "${PIT_LOG}" | awk '{print $NF}')
    echo "    ✓ Dynamic PIT 截面因果计算成功，单截面时延: ${LATENCY} ms"
else
    echo "    ✗ Dynamic PIT 回测运行异常!"
    cat "${PIT_LOG}"
    rm -f "${PIT_LOG}"
    exit 1
fi
rm -f "${PIT_LOG}"

echo ">>> [5/5] 验证核心模型权重与领域组件完整性..."
python3 -c '
from pathlib import Path
from uniquant.brain.wyckoff import AShareConstraints, VShapedReversalDetector
from uniquant.risk.portfolio_optimizer import DEFAULT_RISK_FREE_RATE
from uniquant.services.service_container import ServiceContainer

assert DEFAULT_RISK_FREE_RATE == 0.025, "Rate baseline error"
assert AShareConstraints.get_limit_pct("600001.SH") == 0.10, "Constraint error"
assert Path("scripts/wyckoff_multitf/output_v4/wss_lookup_v2.json").exists(), "Model weight missing"
container = ServiceContainer()
container.register("health_probe", True)
assert container.get("health_probe") is True, "Service container error"
print("    ✓ 核心模型权重存在，领域组件与容器服务健康度 100%")
'

echo "=============================================================================="
echo "✓ 恭喜！UniQuant 系统全部门禁绿灯通过，评级: 极优 (GRADE: S+ EXCELLENT)"
echo "=============================================================================="
