import pytest
from pathlib import Path

from uniquant.shared.kill_switch import SharedKillSwitch, KillSwitchError
from uniquant.shared.state_store import DiskStateStore


class TestPersistentKillSwitch:
    """测试 KillSwitch 状态持久化与跨进程/重启崩溃恢复 (T9a)"""

    def test_kill_persists_and_restores_on_new_instance(self, tmp_path: Path):
        store = DiskStateStore(root_dir=tmp_path)

        # 实例 1: 触发停机
        SharedKillSwitch._instance = None
        ks1 = SharedKillSwitch(state_store=store)
        ks1.reset()
        assert ks1.is_killed is False

        ks1.kill("RISK_LIMIT_BREACH_CRITICAL")
        assert ks1.is_killed is True
        assert ks1.reason == "RISK_LIMIT_BREACH_CRITICAL"

        # 模拟进程重启: 清空内存单例并创建实例 2
        SharedKillSwitch._instance = None
        ks2 = SharedKillSwitch(state_store=store)

        # 断言重启后 Fail-Closed 恢复停机状态
        assert ks2.is_killed is True
        assert ks2.reason == "RISK_LIMIT_BREACH_CRITICAL"
        with pytest.raises(KillSwitchError, match="RISK_LIMIT_BREACH_CRITICAL"):
            ks2.check()

        # 显式 reset 恢复交易
        ks2.reset()
        assert ks2.is_killed is False
        assert ks2.reason == ""

        # 模拟再次重启: 停机状态已清除，正常启动
        SharedKillSwitch._instance = None
        ks3 = SharedKillSwitch(state_store=store)
        assert ks3.is_killed is False
        assert ks3.reason == ""
        # check 不抛出异常
        ks3.check()

    def test_reset_clears_underlying_store(self, tmp_path: Path):
        store = DiskStateStore(root_dir=tmp_path)
        SharedKillSwitch._instance = None
        ks = SharedKillSwitch(state_store=store)

        ks.kill("MANUAL_STOP")
        assert store.exists("kill_switch") is True

        ks.reset()
        assert store.exists("kill_switch") is False
