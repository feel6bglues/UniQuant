"""沪深300百只股票（跨四个上市时代）QFQ 前复权契约与数学正确性冒烟守卫测试。

覆盖标的:
- 100 只沪深300成分股样本 (Era 1: 34只, Era 2: 30只, Era 3: 33只, Era 4: 3只)

契约守卫:
1. 湖优先与 DataFetcher 端到端执行正常，返回 10 列合同 (GET_PRICE_ADJUSTED_COLUMNS)
2. 成交量严格守恒: np.array_equal(qfq['volume'], raw['volume'])，绝不稀释
3. 价格与因子锚点: 最新日 close 保持不变，最新日 adj_factor 恒等于 1.0
4. 因子严格正定与有限: adj_factor > 0 且 np.isfinite
5. 零分红事件股票 (688981.SH 中芯国际) 因子全 1.0，优雅退化
6. 跨 4 时代的 8 个典型除权除息事件理论数学手算对账，与交易所理论除权价误差 < 1e-4
"""

import numpy as np
import pandas as pd
import pytest

from uniquant.data.corporate_action import get_corporate_action_adjuster
from uniquant.data.data_fetcher import DataFetcher, GET_PRICE_ADJUSTED_COLUMNS

# 本文件为真实数据冒烟守卫: 行情来自本地数据湖 (data/lake/, gitignored),
# 前复权事件来自 GBBQ 基线 (data/fq/gbbq.parquet, gitignored)。两者缺失时
# 声明式跳过 (CI), 而非以空表静默"通过"。
pytestmark = [pytest.mark.requires_lake, pytest.mark.requires_gbbq]

TEST_STOCKS = [
    # Era 1 (Pre-2006, 34只)
    ("000001.SZ", "平安银行", "Era 1"),
    ("000002.SZ", "万科A", "Era 1"),
    ("600660.SH", "福耀玻璃", "Era 1"),
    ("600600.SH", "青岛啤酒", "Era 1"),
    ("600674.SH", "川投能源", "Era 1"),
    ("600690.SH", "海尔智家", "Era 1"),
    ("000538.SZ", "云南白药", "Era 1"),
    ("600803.SH", "新奥股份", "Era 1"),
    ("600809.SH", "山西汾酒", "Era 1"),
    ("600845.SH", "宝信软件", "Era 1"),
    ("601607.SH", "上海医药", "Era 1"),
    ("000568.SZ", "泸州老窖", "Era 1"),
    ("600875.SH", "东方电气", "Era 1"),
    ("600886.SH", "国投电力", "Era 1"),
    ("600887.SH", "伊利股份", "Era 1"),
    ("600893.SH", "航发动力", "Era 1"),
    ("000408.SZ", "藏格矿业", "Era 1"),
    ("600741.SH", "华域汽车", "Era 1"),
    ("000425.SZ", "徐工机械", "Era 1"),
    ("000596.SZ", "古井贡酒", "Era 1"),
    ("600760.SH", "中航沈飞", "Era 1"),
    ("000617.SZ", "中油资本", "Era 1"),
    ("000651.SZ", "格力电器", "Era 1"),
    ("000630.SZ", "铜陵有色", "Era 1"),
    ("000657.SZ", "中钨高新", "Era 1"),
    ("600795.SH", "国电电力", "Era 1"),
    ("000708.SZ", "中信特钢", "Era 1"),
    ("600066.SH", "宇通客车", "Era 1"),
    ("600061.SH", "国投资本", "Era 1"),
    ("000625.SZ", "长安汽车", "Era 1"),
    ("000776.SZ", "广发证券", "Era 1"),
    ("600089.SH", "特变电工", "Era 1"),
    ("600085.SH", "同仁堂", "Era 1"),
    ("000768.SZ", "中航西飞", "Era 1"),
    # Era 2 (2012-2015, 30只)
    ("601360.SH", "三六零", "Era 2"),
    ("000807.SZ", "云铝股份", "Era 2"),
    ("601800.SH", "中国交建", "Era 2"),
    ("601238.SH", "广汽集团", "Era 2"),
    ("300308.SZ", "中际旭创", "Era 2"),
    ("601012.SH", "隆基绿能", "Era 2"),
    ("300316.SZ", "晶盛机电", "Era 2"),
    ("603993.SH", "洛阳钼业", "Era 2"),
    ("000333.SZ", "美的集团", "Era 2"),
    ("000858.SZ", "五粮液", "Era 2"),
    ("600023.SH", "浙能电力", "Era 2"),
    ("000975.SZ", "山金国际", "Era 2"),
    ("002709.SZ", "天赐材料", "Era 2"),
    ("002714.SZ", "牧原股份", "Era 2"),
    ("601225.SH", "陕西煤业", "Era 2"),
    ("603288.SH", "海天味业", "Era 2"),
    ("603369.SH", "今世缘", "Era 2"),
    ("603019.SH", "中科曙光", "Era 2"),
    ("300408.SZ", "三环集团", "Era 2"),
    ("002736.SZ", "国信证券", "Era 2"),
    ("300418.SZ", "昆仑万维", "Era 2"),
    ("300413.SZ", "芒果超媒", "Era 2"),
    ("601021.SH", "春秋航空", "Era 2"),
    ("000166.SZ", "申万宏源", "Era 2"),
    ("603799.SH", "华友钴业", "Era 2"),
    ("300394.SZ", "天孚通信", "Era 2"),
    ("300433.SZ", "蓝思科技", "Era 2"),
    ("601689.SH", "拓普集团", "Era 2"),
    ("600958.SH", "东方证券", "Era 2"),
    ("300442.SZ", "润泽科技", "Era 2"),
    # Era 3 (2016-2023, 33只)
    ("300502.SZ", "新易盛", "Era 3"),
    ("601127.SH", "赛力斯", "Era 3"),
    ("600919.SH", "江苏银行", "Era 3"),
    ("603986.SH", "兆易创新", "Era 3"),
    ("600926.SH", "杭州银行", "Era 3"),
    ("601229.SH", "上海银行", "Era 3"),
    ("002837.SZ", "英维克", "Era 3"),
    ("601881.SH", "中国银河", "Era 3"),
    ("300628.SZ", "亿联网络", "Era 3"),
    ("603501.SH", "豪威集团", "Era 3"),
    ("300661.SZ", "圣邦股份", "Era 3"),
    ("601878.SH", "浙商证券", "Era 3"),
    ("603260.SH", "合盛硅业", "Era 3"),
    ("002916.SZ", "深南电路", "Era 3"),
    ("600025.SH", "华能水电", "Era 3"),
    ("001965.SZ", "招商公路", "Era 3"),
    ("002920.SZ", "德赛西威", "Era 3"),
    ("601838.SH", "成都银行", "Era 3"),
    ("603259.SH", "药明康德", "Era 3"),
    ("601138.SH", "工业富联", "Era 3"),
    ("300750.SZ", "宁德时代", "Era 3"),
    ("601066.SH", "中信建投", "Era 3"),
    ("002938.SZ", "鹏鼎控股", "Era 3"),
    ("300760.SZ", "迈瑞医疗", "Era 3"),
    ("601319.SH", "中国人保", "Era 3"),
    ("600989.SH", "宝丰能源", "Era 3"),
    ("601698.SH", "中国卫通", "Era 3"),
    ("688012.SH", "中微公司", "Era 3"),
    ("688008.SH", "澜起科技", "Era 3"),
    ("688009.SH", "中国通号", "Era 3"),
    ("003816.SZ", "中国广核", "Era 3"),
    ("688036.SH", "传音控股", "Era 3"),
    ("688981.SH", "中芯国际", "Era 3"),
    # Era 4 (Post-2024, 3只)
    ("001391.SZ", "国货航", "Era 4"),
    ("600930.SH", "华电新能", "Era 4"),
    ("001280.SZ", "中国铀业", "Era 4"),
]


@pytest.fixture(scope="module")
def fetcher():
    return DataFetcher(data_dir="data")


@pytest.fixture(scope="module")
def adjuster():
    return get_corporate_action_adjuster()


@pytest.mark.parametrize("symbol,name,era", TEST_STOCKS)
def test_csi300_qfq_invariants(fetcher, symbol, name, era):
    """测试各时代标的 QFQ 基本不变量契约。"""
    raw_df = fetcher.get_price(symbol, adjust="")
    qfq_df = fetcher.get_price(symbol, adjust="qfq")

    assert not raw_df.empty, f"{symbol} 原始行情为空"
    assert not qfq_df.empty, f"{symbol} 复权行情为空"
    assert len(raw_df) == len(qfq_df), f"{symbol} 复权后行数不一致"

    # 1. 列契约
    assert list(qfq_df.columns) == GET_PRICE_ADJUSTED_COLUMNS

    # 2. Volume 严格守恒
    assert np.array_equal(qfq_df["volume"].to_numpy(), raw_df["volume"].to_numpy()), (
        f"{symbol} 发生 volume 污染稀释 (旧轨副作用)"
    )

    # 3. 价格锚点守恒 (最新日复权收盘价等于原始收盘价)
    assert abs(qfq_df["close"].iloc[-1] - raw_df["close"].iloc[-1]) < 1e-5

    # 4. 因子锚点守恒 (最新日复权因子为 1.0)
    assert abs(qfq_df["adj_factor"].iloc[-1] - 1.0) < 1e-6

    # 5. 因子严格正定与有限
    factors = qfq_df["adj_factor"].to_numpy()
    assert (factors > 0).all()
    assert np.isfinite(factors).all()


def test_zero_event_stock_degradation(fetcher, adjuster):
    """测试无分红送转事件标的 (688981.SH 中芯国际) 优雅退化为恒 1.0。"""
    symbol = "688981.SH"
    events = adjuster.get_stock_events(symbol)
    assert events.empty, f"{symbol} 应无有效除权除息事件"

    raw_df = fetcher.get_price(symbol, adjust="")
    qfq_df = fetcher.get_price(symbol, adjust="qfq")

    assert np.allclose(qfq_df["adj_factor"].to_numpy(), 1.0)
    assert np.allclose(qfq_df["close"].to_numpy(), raw_df["close"].to_numpy())


@pytest.mark.parametrize(
    "symbol,ex_date_str",
    [
        # Era 1
        ("600519.SH", "2024-06-19"),   # 茅台 10派308.76元
        ("000001.SZ", "2016-06-16"),   # 平安 10送转2派1.53元
        ("600036.SH", "2024-07-11"),   # 招行 10派19.72元
        # Era 2
        ("002714.SZ", "2020-06-04"),   # 牧原 10转7派5.5元
        ("601985.SH", "2024-07-16"),   # 核电 10派1.95元
        # Era 3
        ("300750.SZ", "2023-04-26"),   # 宁德 10转8派25.20元
        ("600941.SH", "2024-09-02"),   # 移动 10派23.789元
        # Era 4
        ("001280.SZ", "2026-07-06"),   # 铀业 10派2.60元
    ],
)
def test_theoretical_ex_rights_spot_check(fetcher, adjuster, symbol, ex_date_str):
    """跨 4 时代的 8 个典型除权除息事件理论数学手算核验。"""
    raw_df = fetcher.get_price(symbol, adjust="")
    qfq_df = fetcher.get_price(symbol, adjust="qfq")

    ex_date = pd.Timestamp(ex_date_str)
    raw_df["date"] = pd.to_datetime(raw_df["date"])
    qfq_df["date"] = pd.to_datetime(qfq_df["date"])

    idx = raw_df["date"].searchsorted(ex_date)
    pre_close = float(raw_df.loc[idx - 1, "close"])

    events = adjuster.get_stock_events(symbol)
    ev = events[events["date"] == ex_date].iloc[0]
    cash = float(ev["cash"])
    split = float(ev["split"])
    rights = float(ev["rights"])
    r_price = float(ev["r_price"])

    # 理论除权价
    theory_ex_price = round((pre_close - cash + (rights * r_price)) / (1.0 + split + rights), 2)
    step_factor = pre_close / theory_ex_price

    # 引擎因子步长比
    engine_step_ratio = float(qfq_df.loc[idx, "adj_factor"]) / float(qfq_df.loc[idx - 1, "adj_factor"])

    assert abs(engine_step_ratio - step_factor) < 1e-4
