# 常量参考

本文档为 UniQuant 系统中所有常量类的完整参考，源自 `src/uniquant/shared/constants/` 子包（7 个模块，通过 `__init__.py` 统一导出）。

---

## 常量类索引

| 类名 | 说明 |
|------|------|
| `DateConstants` | 日期格式与默认日期常量 |
| `AnalysisServiceConstants` | 分析服务配置（缓存、重试、采样、信号等） |
| `TimeConstants` | 时间跨度常量（年、月、季度） |
| `MarketConstants` | 市场类型、交易所、指数代码、板块前缀、涨跌停比例 |
| `MarketCapThresholds` | 市值分级阈值（大/中/小/微盘股） |
| `TimeWindows` | 分析时间窗口（短/中/长/超长期及计算窗口） |
| `IndicatorThresholds` | 技术指标阈值（RSI、MACD、布林带、FSM等） |
| `RiskThresholds` | 风险控制阈值（VaR、回撤、仓位、波动率） |
| `RiskCalculationConstants` | 风险计算常量（VaR/CVaR/波动率阈值、压力测试场景） |
| `DataValidationConstants` | 数据验证常量（价格/成交量限制、数据完整性） |
| `PrecisionConstants` | 精度和误差控制常量 |
| `PerformanceConstants` | 性能优化常量（缓存、批量处理、超时） |
| `NetworkConstants` | 网络常量（超时、重试、请求配置、HTTP状态码） |
| `CacheConstants` | 缓存常量（TTL、类型、策略） |
| `PathConstants` | 路径常量（数据目录、文件后缀、配置文件） |
| `DataSourceConstants` | 数据源常量（列名映射、单位转换、请求控制） |
| `THSConstants` | 同花顺数据源常量 |
| `DataLakeConstants` | 数据湖常量（目录、缓存、批量处理） |
| `UIConstants` | UI 显示常量（端口、主题、颜色） |
| `TestConstants` | 测试相关常量（各类测试参数） |
| `ToolConstants` | 工具常量（代码质量阈值、架构检查） |
| `DataServiceConstants` | 数据服务常量（缓存TTL、质量评分、时效性） |
| `NTFConstants` | NTF 引擎常量（偏离度、成交量脉冲、置信度） |
| `LPPLConstants` | LPPL 泡沫检测常量（优化器、参数边界、置信度） |
| `RegimeConstants` | 市场状态检测常量（熵值、成交量Z-Score） |
| `UATConstants` | UAT 测试常量 |
| `ResultsConstants` | 计算结果管理常量（目录、文件格式、清理策略） |
| `BacktestConstants` | 回测引擎常量（初始资金、交易成本、风险控制） |
| `MarketHours` | A 股市场交易时间常量及方法 |
| `WindowConfig` | LPPL 窗口配置数据类 |
| 模块级常量 | 模块级别的路径、LPPL、Wyckoff 常量 |

---

## DateConstants

日期格式与默认起始日期。

| 字段名 | 类型 | 值 | 说明 |
|--------|------|------|------|
| `DEFAULT_START_DATE` | str | `"2000-01-01"` | 默认起始日期（横线分隔格式） |
| `DEFAULT_START_DATE_COMPACT` | str | `"20000101"` | 默认起始日期（紧凑格式） |
| `FORMAT_DASH` | str | `"%Y-%m-%d"` | 日期格式：横线分隔 |
| `FORMAT_COMPACT` | str | `"%Y%m%d"` | 日期格式：紧凑 |
| `FORMAT_DATETIME` | str | `"%Y-%m-%d %H:%M:%S"` | 日期时间格式 |

---

## AnalysisServiceConstants

分析服务相关配置，包括缓存、重试、采样、移动平均线窗口、信号阈值等。

| 字段名 | 类型 | 值 | 说明 |
|--------|------|------|------|
| `MEMORY_CACHE_MAX_SIZE` | int | `1000` | 内存缓存最大条目数 |
| `DEFAULT_VAR_95` | float | `0.05` | 默认 95% VaR |
| `DEFAULT_VAR_99` | float | `0.08` | 默认 99% VaR |
| `DEFAULT_CVAR_95` | float | `0.07` | 默认 95% CVaR |
| `DEFAULT_CVAR_99` | float | `0.10` | 默认 99% CVaR |
| `DEFAULT_MAX_DRAWDOWN` | float | `0.15` | 默认最大回撤 |
| `RANDOM_DATA_STD` | float | `0.02` | 随机数据标准差 |
| `RANDOM_DATA_LENGTH` | int | `252` | 随机数据长度（1年交易日） |
| `CACHE_TTL_1HOUR` | int | `3600` | 缓存有效期 1 小时 |
| `CACHE_TTL_2HOURS` | int | `7200` | 缓存有效期 2 小时 |
| `MAX_RETRIES` | int | `3` | 最大重试次数 |
| `RETRY_DELAY` | float | `1.0` | 重试延迟（秒） |
| `MAX_WAIT_TIME` | float | `10.0` | 最大等待时间（秒） |
| `DEFAULT_ETF_LIST` | list | `["510300.SH"]` | 默认 ETF 列表 |
| `SAMPLE_MAX_ROWS_DEFAULT` | int | `5000` | 默认最大采样行数 |
| `MIN_SAMPLE_INTERVAL_RATIO` | float | `0.01` | 最小采样间隔比例 |
| `CHUNK_SIZE` | int | `1000` | 分块处理大小 |
| `SAMPLE_MAX_ROWS_LPPL` | int | `1000` | LPPL 分析最大采样行数 |
| `SAMPLE_MAX_ROWS_CZSC` | int | `2000` | 缠论分析最大采样行数 |
| `RECENT_HIGH_LOW_WINDOW` | int | `20` | 近期高低点窗口 |
| `MA_WINDOW_SHORT` | int | `5` | 短期移动平均线窗口 |
| `MA_WINDOW_MEDIUM` | int | `20` | 中期移动平均线窗口 |
| `MA_WINDOW_LONG` | int | `60` | 长期移动平均线窗口 |
| `TREND_STRONG_UP_THRESHOLD` | float | `1.05` | 强势上涨趋势阈值 |
| `TREND_STRONG_DOWN_THRESHOLD` | float | `0.95` | 强势下跌趋势阈值 |
| `SAMPLE_MAX_ROWS_FSM` | int | `1000` | FSM 分析最大采样行数 |
| `STOP_LOSS_RATIO` | float | `0.95` | 止损比例 |
| `TAKE_PROFIT_RATIO` | float | `1.10` | 止盈比例 |
| `SIGNAL_STRENGTH_SCALE` | float | `100.0` | 信号强度缩放因子 |
| `SIGNAL_BUY` | str | `"buy"` | 买入信号标识 |
| `SIGNAL_SELL` | str | `"sell"` | 卖出信号标识 |
| `RECOMMENDATION_MAP` | dict | `{"buy": "买入", "sell": "卖出"}` | 信号推荐中英文映射 |

---

## TimeConstants

时间跨度常量，用于数据窗口计算。

| 字段名 | 类型 | 值 | 说明 |
|--------|------|------|------|
| `DAYS_1_YEAR` | int | `365` | 一年天数 |
| `DAYS_MONTH` | int | `30` | 一个月天数 |
| `DAYS_QUARTER` | int | `90` | 一个季度天数 |
| `DATA_WINDOW_30DAYS` | int | `30` | 30 天数据窗口 |
| `DATA_WINDOW_365DAYS` | int | `365` | 365 天数据窗口 |

---

## MarketConstants

市场类型、交易所、指数代码、板块前缀及涨跌停比例。

| 字段名 | 类型 | 值 | 说明 |
|--------|------|------|------|
| `MARKET_CN` | str | `"cn"` | 中国市场 |
| `MARKET_HK` | str | `"hk"` | 香港市场 |
| `MARKET_US` | str | `"us"` | 美国市场 |
| `EXCHANGE_SSE` | str | `"SSE"` | 上海证券交易所 |
| `EXCHANGE_SZSE` | str | `"SZSE"` | 深圳证券交易所 |
| `EXCHANGE_BSE` | str | `"BSE"` | 北京证券交易所 |
| `INDEX_HS300` | str | `"000300.SH"` | 沪深300指数 |
| `INDEX_SZ50` | str | `"000016.SH"` | 上证50指数 |
| `INDEX_ZZ500` | str | `"000905.SH"` | 中证500指数 |
| `INDEX_SZ` | str | `"000001.SH"` | 上证综合指数 |
| `INDEX_SZSE` | str | `"399001.SZ"` | 深证成指 |
| `INDEX_GEM` | str | `"399006.SZ"` | 创业板指 |
| `INDEX_ZZ1000` | str | `"000852.SH"` | 中证1000指数 |
| `INDEX_ZZ2000` | str | `"932000.SH"` | 中证2000指数 |
| `MAJOR_INDEXES` | dict | 见下方 | 主要指数代码到名称的映射字典 |
| `MARKET_STATUS_OPEN` | str | `"open"` | 市场状态：开盘 |
| `MARKET_STATUS_CLOSED` | str | `"closed"` | 市场状态：收盘 |
| `MARKET_STATUS_HALT` | str | `"halt"` | 市场状态：停牌 |
| `BOARD_PREFIX` | dict | 见下方 | 板块前缀分类 |
| `LIMIT_RATIO` | dict | 见下方 | 涨跌停比例（价格比例格式） |
| `PRICE_TOLERANCE` | float | `0.001` | 价格比较容差 0.1% |

**MAJOR_INDEXES 字典内容：**

| 代码 | 名称 |
|------|------|
| `000001.SH` | 上证综指 |
| `399001.SZ` | 深证成指 |
| `399006.SZ` | 创业板指 |
| `000016.SH` | 上证50 |
| `000300.SH` | 沪深300 |
| `000905.SH` | 中证500 |
| `000852.SH` | 中证1000 |
| `932000.SH` | 中证2000 |

**BOARD_PREFIX 字典内容：**

| 板块 | 前缀列表 | 说明 |
|------|----------|------|
| `st` | `["ST", "*ST"]` | ST 股 |
| `sci_tech` | `["688"]` | 科创板 |
| `gem` | `["300", "301"]` | 创业板 |
| `beijing` | `["8", "4"]` | 北交所/新三板 |
| `main` | `["600", "601", "603", "605", "000", "001", "002"]` | 主板 |

**LIMIT_RATIO 字典内容（涨停价/前收盘价, 跌停价/前收盘价）：**

| 板块 | 涨停比例 | 跌停比例 | 说明 |
|------|----------|----------|------|
| `st` | 1.05 | 0.95 | ST 股 +-5% |
| `sci_tech` | 1.20 | 0.80 | 科创板 +-20% |
| `gem` | 1.20 | 0.80 | 创业板 +-20% |
| `beijing` | 1.30 | 0.70 | 北交所 +-30% |
| `main` | 1.10 | 0.90 | 主板 +-10% |

---

## MarketCapThresholds

市值分级阈值，单位为亿元。

| 字段名 | 类型 | 值 | 说明 |
|--------|------|------|------|
| `LARGE_CAP` | int | `1000` | 大盘股阈值 (>=1000亿) |
| `MID_CAP` | int | `300` | 中盘股阈值 (>=300亿) |
| `SMALL_CAP` | int | `50` | 小盘股阈值 (>=50亿) |
| `MICRO_CAP` | int | `10` | 微盘股阈值 (>=10亿) |

---

## TimeWindows

分析时间窗口常量，单位为交易日。

| 字段名 | 类型 | 值 | 说明 |
|--------|------|------|------|
| `SHORT_TERM` | int | `20` | 短期窗口（约1个月） |
| `MEDIUM_TERM` | int | `60` | 中期窗口（约3个月） |
| `LONG_TERM` | int | `120` | 长期窗口（约6个月） |
| `VERY_LONG_TERM` | int | `252` | 超长期窗口（约1年） |
| `VOLATILITY_WINDOW` | int | `20` | 波动率计算窗口 |
| `TREND_WINDOW` | int | `60` | 趋势计算窗口 |
| `REGIME_WINDOW` | int | `120` | 市场状态计算窗口 |
| `MACRO_WINDOW` | int | `252` | 宏观收益计算窗口 |

---

## IndicatorThresholds

技术指标阈值，涵盖 RSI、MACD、布林带、移动平均线、FSM 状态机等。

| 字段名 | 类型 | 值 | 说明 |
|--------|------|------|------|
| `RSI_OVERBOUGHT` | int | `70` | RSI 超买阈值 |
| `RSI_OVERSOLD` | int | `30` | RSI 超卖阈值 |
| `RSI_MID` | int | `50` | RSI 中间值 |
| `MACD_SIGNAL_THRESHOLD` | float | `0.0` | MACD 信号线阈值 |
| `BOLLINGER_UPPER` | float | `2.0` | 布林带上轨标准差倍数 |
| `BOLLINGER_LOWER` | float | `-2.0` | 布林带下轨标准差倍数 |
| `MA_SHORT` | int | `5` | 短期移动平均线周期 |
| `MA_MEDIUM` | int | `20` | 中期移动平均线周期 |
| `MA_LONG` | int | `60` | 长期移动平均线周期 |
| `ATR_PERIOD` | int | `14` | ATR 周期 |
| `DEFAULT_ATR_PERIOD` | int | `14` | 默认 ATR 周期 |
| `RSI_PERIOD` | int | `14` | RSI 周期 |
| `MACD_FAST` | int | `12` | MACD 快线周期 |
| `MACD_SLOW` | int | `26` | MACD 慢线周期 |
| `MACD_SIGNAL` | int | `9` | MACD 信号线周期 |
| `BBANDS_PERIOD` | int | `20` | 布林带周期 |
| `BBANDS_STDDEV` | float | `2.0` | 布林带标准差倍数 |
| `BOLLINGER_PERIOD` | int | `20` | 布林带周期（兼容旧代码） |
| `ROLLING_MIN_PERIODS_RATIO` | float | `0.5` | 滚动计算最小周期比例 |
| `ROLLING_MIN_PERIODS_MIN` | int | `5` | 滚动计算最小周期最小值 |
| `ENTROPY_WINDOW` | int | `60` | 熵值计算窗口 |
| `TURNOVER_Z_PERIOD` | int | `20` | 成交量 Z-Score 计算周期 |
| `VOLUME_MA_PERIOD` | int | `20` | 成交量 MA 周期 |
| `FSM_MA_SHORT` | int | `5` | FSM 短期 MA 周期 |
| `FSM_MA_LONG` | int | `20` | FSM 长期 MA 周期 |
| `FSM_PULLBACK_UPPER` | float | `1.05` | FSM 回调上限 |
| `FSM_PULLBACK_LOWER` | float | `0.95` | FSM 回调下限 |
| `FSM_SCORE_CZSC` | int | `20` | FSM 缠论信号分数 |
| `FSM_SCORE_TREND` | int | `15` | FSM 趋势分数 |
| `FSM_SCORE_ALPHA` | int | `10` | FSM Alpha 分数 |
| `FSM_SCORE_NTF` | int | `10` | FSM NTF 分数 |
| `FSM_ALPHA_THRESHOLD` | float | `0.6` | FSM Alpha 阈值 |
| `FSM_SCORE_THRESHOLD_IDLE_TO_SIGNAL` | int | `30` | FSM IDLE 到 SIGNAL 状态阈值 |
| `FSM_SCORE_THRESHOLD_SIGNAL_TO_MONITOR` | int | `50` | FSM SIGNAL 到 MONITOR 状态阈值 |
| `FSM_SCORE_THRESHOLD_TO_EXIT` | int | `20` | FSM 退出阈值 |
| `FSM_SCORE_THRESHOLD_TO_PYRAMID` | int | `70` | FSM 加仓阈值 |
| `FSM_SCORE_THRESHOLD_EXIT` | int | `10` | FSM 退出阈值 |
| `FSM_RISK_SCALER_CRITICAL` | float | `2.0` | FSM 风险缩放因子 |

---

## RiskThresholds

风险控制阈值。

| 字段名 | 类型 | 值 | 说明 |
|--------|------|------|------|
| `VAR_DAILY_LIMIT` | float | `0.02` | 日 VaR 限制 2% |
| `VAR_CONFIDENCE` | float | `0.95` | VaR 置信度 |
| `MAX_DRAWDOWN_LIMIT` | float | `0.15` | 最大回撤限制 15% |
| `MAX_POSITION_PCT` | float | `0.95` | 最大仓位比例 95% |
| `MIN_POSITION_PCT` | float | `0.0` | 最小仓位比例 0% |
| `VOLATILITY_LIMIT` | float | `0.3` | 波动率限制 30% |

---

## RiskCalculationConstants

风险计算相关常量，包括阈值分级和压力测试场景。

| 字段名 | 类型 | 值 | 说明 |
|--------|------|------|------|
| `VAR_THRESHOLD_HIGH` | float | `0.05` | 高 VaR 阈值 5% |
| `VAR_THRESHOLD_MEDIUM` | float | `0.03` | 中 VaR 阈值 3% |
| `VAR_THRESHOLD_LOW` | float | `0.01` | 低 VaR 阈值 1% |
| `CVAR_THRESHOLD_HIGH` | float | `0.06` | 高 CVaR 阈值 6% |
| `CVAR_THRESHOLD_MEDIUM` | float | `0.04` | 中 CVaR 阈值 4% |
| `CVAR_THRESHOLD_LOW` | float | `0.02` | 低 CVaR 阈值 2% |
| `VOLATILITY_HIGH` | float | `0.3` | 高波动率 30% |
| `VOLATILITY_MEDIUM` | float | `0.2` | 中波动率 20% |
| `VOLATILITY_LOW` | float | `0.1` | 低波动率 10% |
| `SHARPE_RATIO_BULL` | float | `1.0` | 牛市夏普比率 |
| `SHARPE_RATIO_BEAR` | float | `0.0` | 熊市夏普比率 |
| `MAX_DRAWDOWN_THRESHOLD` | float | `0.2` | 最大回撤阈值 20% |
| `CRASH_SCENARIOS` | dict | 见下方 | 市场崩溃压力测试场景 |
| `RATE_HIKE_SCENARIOS` | dict | 见下方 | 加息压力测试场景 |
| `RECESSION_SCENARIOS` | dict | 见下方 | 经济衰退压力测试场景 |

**CRASH_SCENARIOS 字典内容：**

| 场景 | 跌幅 | 说明 |
|------|------|------|
| `market_crash_2008` | -0.5 | 2008年市场崩溃 |
| `market_crash_2015` | -0.4 | 2015年市场崩溃 |
| `flash_crash_2010` | -0.1 | 2010年闪崩 |
| `circuit_breaker_2020` | -0.07 | 2020年熔断 |
| `financial_crisis_2008` | -0.5 | 2008年金融危机 |

**RATE_HIKE_SCENARIOS 字典内容：**

| 场景 | 跌幅 | 说明 |
|------|------|------|
| `rate_hike_25bp` | -0.02 | 加息25个基点 |
| `rate_hike_50bp` | -0.05 | 加息50个基点 |
| `rate_hike_100bp` | -0.1 | 加息100个基点 |

**RECESSION_SCENARIOS 字典内容：**

| 场景 | 跌幅 | 说明 |
|------|------|------|
| `mild_recession` | -0.15 | 轻度衰退 |
| `moderate_recession` | -0.25 | 中度衰退 |
| `severe_recession` | -0.4 | 重度衰退 |

---

## DataValidationConstants

数据验证相关常量。

| 字段名 | 类型 | 值 | 说明 |
|--------|------|------|------|
| `MIN_PRICE` | float | `0.01` | 最小合法价格 |
| `MAX_PRICE` | float | `10000.0` | 最大合法价格 |
| `MIN_VOLUME` | int | `0` | 最小成交量 |
| `MAX_VOLUME` | float | `1e12` | 最大成交量 |
| `MAX_DAILY_CHANGE` | float | `0.2` | 最大日涨跌幅 20%（科创板/创业板） |
| `MAX_DAILY_CHANGE_ST` | float | `0.05` | ST 股最大日涨跌幅 5% |
| `MIN_DATA_POINTS` | int | `30` | 最小数据点数 |
| `MAX_MISSING_RATIO` | float | `0.1` | 最大缺失值比例 10% |

---

## PrecisionConstants

精度和误差控制常量。

| 字段名 | 类型 | 值 | 说明 |
|--------|------|------|------|
| `PRICE_DECIMALS` | int | `2` | 价格保留 2 位小数 |
| `RATE_DECIMALS` | int | `4` | 收益率保留 4 位小数 |
| `PCT_DECIMALS` | int | `4` | 百分比保留 4 位小数 |
| `VOLUME_DECIMALS` | int | `0` | 成交量保留整数 |
| `AMOUNT_DECIMALS` | int | `2` | 成交额保留 2 位小数 |
| `WEIGHT_DECIMALS` | int | `4` | 权重保留 4 位小数 |
| `FLOAT_TOLERANCE` | float | `1e-6` | 浮点数比较容差 |

---

## PerformanceConstants

性能优化相关常量。

| 字段名 | 类型 | 值 | 说明 |
|--------|------|------|------|
| `DEFAULT_CACHE_TTL` | int | `300` | 默认缓存时间 5 分钟 |
| `CACHE_TTL_SECONDS` | int | `3600` | 缓存过期时间 1 小时 |
| `MAX_CACHE_SIZE` | int | `1000` | 最大缓存条目数 |
| `CACHE_MAX_SIZE` | int | `5000` | 缓存最大大小（兼容旧代码） |
| `BATCH_SIZE` | int | `100` | 批量处理大小 |
| `MAX_WORKERS` | int | `4` | 最大工作线程数 |
| `DEFAULT_TIMEOUT` | int | `30` | 默认超时 30 秒 |
| `MAX_TIMEOUT` | int | `300` | 最大超时 5 分钟 |

---

## NetworkConstants

网络请求相关常量。

| 字段名 | 类型 | 值 | 说明 |
|--------|------|------|------|
| `DEFAULT_TIMEOUT` | int | `30` | 默认超时 30 秒 |
| `CONNECT_TIMEOUT` | int | `10` | 连接超时 10 秒 |
| `READ_TIMEOUT` | int | `30` | 读取超时 30 秒 |
| `SHORT_TIMEOUT` | int | `10` | 短超时 10 秒 |
| `MEDIUM_TIMEOUT` | int | `15` | 中超时 15 秒 |
| `LONG_TIMEOUT` | int | `60` | 长超时 60 秒 |
| `SOCKET_TIMEOUT` | int | `10` | Socket 超时 10 秒 |
| `MAX_RETRIES` | int | `3` | 最大重试次数 |
| `RETRY_DELAY` | float | `1.0` | 重试延迟（秒） |
| `RETRY_BACKOFF` | float | `2.0` | 重试退避因子 |
| `RETRY_DELAY_BASE` | float | `2.0` | 重试基础延迟 |
| `RETRY_JITTER_MIN` | float | `0.5` | 最小随机抖动因子 |
| `RETRY_JITTER_MAX` | float | `1.5` | 最大随机抖动因子 |
| `MAX_REDIRECTS` | int | `5` | 最大重定向次数 |
| `MAX_KEEPALIVE_CONNECTIONS` | int | `20` | 最大保持连接数 |
| `USER_AGENT` | str | `"Mozilla/5.0 ..."` | 请求 User-Agent |
| `SINA_API_CONFIG` | dict | 见下方 | 新浪 API 配置 |
| `HTTP_OK` | int | `200` | HTTP 200 成功 |
| `HTTP_NOT_FOUND` | int | `404` | HTTP 404 未找到 |
| `HTTP_RATE_LIMIT` | int | `429` | HTTP 429 限流 |
| `HTTP_SERVER_ERROR` | int | `500` | HTTP 500 服务器错误 |

**SINA_API_CONFIG 字典内容：**

| 键 | 值 | 说明 |
|------|------|------|
| `kline_url` | `"http://money.finance.sina.com.cn/..."` | K 线数据 URL |
| `headers` | `{"Referer": "http://finance.sina.com.cn"}` | 请求头 |
| `random_sleep_min` | `1.5` | 随机休眠最小值（秒） |
| `random_sleep_max` | `3.0` | 随机休眠最大值（秒） |
| `timeout` | `15` | 请求超时时间（秒） |

---

## CacheConstants

缓存相关常量。

| 字段名 | 类型 | 值 | 说明 |
|--------|------|------|------|
| `DEFAULT_TTL` | int | `300` | 默认缓存时间 5 分钟 |
| `DEFAULT_MAX_SIZE` | int | `1000` | 默认最大缓存条目数 |
| `DEFAULT_MAX_CACHE_SIZE` | int | `1000` | 默认最大缓存条目数 |
| `MAX_CACHE_AGE` | int | `604800` | 最大缓存寿命 7 天 |
| `CACHE_TYPE_MEMORY` | str | `"memory"` | 缓存类型：内存 |
| `CACHE_TYPE_DISK` | str | `"disk"` | 缓存类型：磁盘 |
| `CACHE_TYPE_REDIS` | str | `"redis"` | 缓存类型：Redis |
| `POLICY_LRU` | str | `"lru"` | LRU 淘汰策略 |
| `POLICY_LFU` | str | `"lfu"` | LFU 淘汰策略 |
| `POLICY_FIFO` | str | `"fifo"` | FIFO 淘汰策略 |
| `TTL_NO_EXPIRE` | int | `0` | 永不过期 |
| `TTL_FOREVER` | int | `-1` | 永久缓存 |
| `CACHE_TTL_STOCK` | int | `3600` | 股票数据 TTL 1 小时 |
| `CACHE_TTL_INDEX` | int | `7200` | 指数数据 TTL 2 小时 |
| `CACHE_TTL_ETF` | int | `3600` | ETF 数据 TTL 1 小时 |
| `CACHE_TTL_REALTIME` | int | `300` | 实时数据 TTL 5 分钟 |
| `CACHE_TTL_INDUSTRY` | int | `86400` | 行业数据 TTL 1 天 |
| `CACHE_TTL_CONCEPT` | int | `86400` | 概念数据 TTL 1 天 |
| `CACHE_TTL_GENERAL` | int | `3600` | 通用数据 TTL 1 小时 |
| `CACHE_TTL_DAILY` | int | `86400` | 日线数据 TTL 1 天 |
| `CACHE_TTL_MINUTE` | int | `300` | 分钟线数据 TTL 5 分钟 |
| `CACHE_TTL_WEEKLY` | int | `604800` | 周线数据 TTL 1 周 |
| `CACHE_TTL_MONTHLY` | int | `2592000` | 月线数据 TTL 30 天 |

---

## PathConstants

路径相关常量。所有路径以 `PROJECT_ROOT`（即 `shared/constants/path.py` 中定义的项目根目录）为基准。

| 字段名 | 类型 | 值 | 说明 |
|--------|------|------|------|
| `DATA_DIR` | Path | `PROJECT_ROOT / "data"` | 数据根目录 |
| `RAW_DIR` | Path | `PROJECT_ROOT / "data" / "raw"` | 原始数据目录 |
| `CLEAN_DIR` | Path | `PROJECT_ROOT / "data" / "clean"` | 清洗数据目录 |
| `LAKE_DIR` | Path | `PROJECT_ROOT / "data" / "lake"` | 数据湖目录 |
| `REPORT_DIR` | Path | `PROJECT_ROOT / "data" / "reports"` | 报告目录 |
| `LOG_DIR` | Path | `PROJECT_ROOT / "logs"` | 日志目录 |
| `FILE_SUFFIX_CSV` | str | `".csv"` | CSV 文件后缀 |
| `FILE_SUFFIX_PARQUET` | str | `".parquet"` | Parquet 文件后缀 |
| `FILE_SUFFIX_JSON` | str | `".json"` | JSON 文件后缀 |
| `FILE_SUFFIX_LOG` | str | `".log"` | 日志文件后缀 |
| `CONFIG_FILE` | str | `"config.yaml"` | 配置文件名 |
| `STOCK_LIST_FILE` | Path | `PROJECT_ROOT / "data" / "stock_list.json"` | 股票列表文件 |
| `CSV_SUFFIX` | str | `".csv"` | CSV 后缀（兼容别名） |
| `PARQUET_SUFFIX` | str | `".parquet"` | Parquet 后缀（兼容别名） |
| `JSON_SUFFIX` | str | `".json"` | JSON 后缀（兼容别名） |
| `LOG_SUFFIX` | str | `".log"` | 日志后缀（兼容别名） |

---

## 模块级路径常量

定义在 `PathConstants` 类之外的模块级路径常量。

| 变量名 | 类型 | 值 | 说明 |
|--------|------|------|------|
| `PROJECT_ROOT` | Path | `Path(__file__).parent.parent.parent` | 项目根目录 |
| `TDX_DIR` | Path | `PROJECT_ROOT / "tdx"` | 通达信数据目录 |
| `DATA_DIR` | Path | `PROJECT_ROOT / "data"` | 数据根目录 |
| `LAKE_QUOTES_DIR` | Path | `PROJECT_ROOT / "data" / "lake" / "quotes"` | 数据湖行情目录 |
| `LAKE_FINANCIAL_DIR` | Path | `PROJECT_ROOT / "data" / "lake" / "financial"` | 数据湖财务目录 |
| `LAKE_INDEX_DIR` | Path | `PROJECT_ROOT / "data" / "lake" / "index"` | 数据湖指数目录 |
| `STOCK_LIST_FILE` | Path | `PROJECT_ROOT / "data" / "all_stock_codes.csv"` | 全部股票代码文件 |
| `PARQUET_COMPRESSION` | str | `"snappy"` | Parquet 压缩算法 |

---

## DataSourceConstants

数据源相关常量，包括重试配置、列名映射、单位转换及请求控制。

| 字段名 | 类型 | 值 | 说明 |
|--------|------|------|------|
| `MAX_RETRIES` | int | `3` | 最大重试次数 |
| `RETRY_DELAY` | float | `1.0` | 重试延迟（秒） |
| `RETRY_BACKOFF` | float | `2.0` | 重试退避因子 |
| `MIN_REQUEST_INTERVAL` | int | `3` | 最小请求间隔（秒） |
| `MIN_DATA_POINTS` | int | `30` | 最小数据点数 |
| `MAX_MISSING_RATIO` | float | `0.1` | 最大缺失值比例 |
| `DATE_COLS` | list | `["日期", "date", "trade_date", "交易日期", "时间", "time", "dividOperateDate"]` | 日期字段别名 |
| `OPEN_COLS` | list | `["开盘", "open", "开盘价"]` | 开盘价字段别名 |
| `CLOSE_COLS` | list | `["收盘", "close", "收盘价", "price"]` | 收盘价字段别名 |
| `HIGH_COLS` | list | `["最高", "high", "最高价"]` | 最高价字段别名 |
| `LOW_COLS` | list | `["最低", "low", "最低价"]` | 最低价字段别名 |
| `VOLUME_COLS` | list | `["成交量", "volume", "vol", "trading_volume"]` | 成交量字段别名 |
| `AMOUNT_COLS` | list | `["成交额", "amount", "turnover", "trading_amount"]` | 成交额字段别名 |
| `CHANGE_RATE_COLS` | list | `["pct_change", "pctChg", "涨跌幅", "change_rate", "change_pct"]` | 涨跌幅字段别名 |
| `CHANGE_AMOUNT_COLS` | list | `["涨跌额", "price_change", "change_amount"]` | 涨跌额字段别名 |
| `PRECLOSE_COLS` | list | `["preclose", "pre_close", "prev_close", "前收盘", "昨收"]` | 前收盘价字段别名 |
| `QFQ_FACTOR_COLS` | list | `["qfq_factor", "foreAdjustFactor", "前复权因子"]` | 前复权因子字段别名 |
| `HFQ_FACTOR_COLS` | list | `["hfq_factor", "backAdjustFactor", "后复权因子"]` | 后复权因子字段别名 |
| `ADJ_FACTOR_COLS` | list | `["adj_factor", "adjustFactor", "复权因子"]` | 复权因子字段别名 |
| `SECTOR_COLS` | list | `["sector", "板块", "industry"]` | 板块字段别名 |
| `IPO_DATE_COLS` | list | `["ipoDate", "ipo_date", "上市日期"]` | 上市日期字段别名 |
| `DELIST_DATE_COLS` | list | `["outDate", "delist_date", "退市日期"]` | 退市日期字段别名 |
| `STOCK_TYPE_COLS` | list | `["type", "stock_type", "证券类型"]` | 证券类型字段别名 |
| `STOCK_STATUS_COLS` | list | `["status", "stock_status", "上市状态"]` | 上市状态字段别名 |
| `VOL_UNIT_COLS` | list | `["volunit", "vol_unit", "交易单位"]` | 交易单位字段别名 |
| `DECIMAL_POINT_COLS` | list | `["decimal_point", "小数位", "price_decimals"]` | 小数位字段别名 |
| `NAME_COLS` | list | `["name", "code_name", "股票名称", "名称"]` | 股票名称字段别名 |
| `VOLUME_UNITS` | dict | 见下方 | 成交量单位转换 |
| `AMOUNT_UNITS` | dict | 见下方 | 成交额单位转换 |
| `INDEX_PREFIXES` | list | `["000", "399", "880"]` | 指数代码前缀 |
| `SH_PREFIXES` | list | `["6", "5"]` | 上海股票代码前缀 |
| `SZ_PREFIXES` | list | `["0", "3"]` | 深圳股票代码前缀 |
| `SINA_MIN_REQUEST_INTERVAL` | int | `2` | 新浪数据源最小请求间隔（秒） |
| `SINA_MAX_RETRIES` | int | `5` | 新浪数据源最大重试次数 |

**VOLUME_UNITS 字典内容（数据源 -> 转换为股的系数）：**

| 数据源 | 系数 | 说明 |
|--------|------|------|
| `eastmoney` | 100 | 手 -> 股 |
| `tencent` | 1 | 股 -> 股 |
| `sina` | 1 | 股 -> 股 |
| `ths` | 1 | 股 -> 股 |
| `baostock` | 1 | 股 -> 股 |
| `stock` | 10000 | 万股 -> 股 |

**AMOUNT_UNITS 字典内容（数据源 -> 转换为元的系数）：**

| 数据源 | 系数 | 说明 |
|--------|------|------|
| `eastmoney` | 1 | 元 -> 元 |
| `tencent` | 1 | 元 -> 元 |
| `sina` | 1 | 元 -> 元 |
| `ths` | 1 | 元 -> 元 |
| `baostock` | 1 | 元 -> 元 |
| `stock` | 10000 | 万元 -> 元 |

---

## THSConstants

同花顺数据源常量。

| 字段名 | 类型 | 值 | 说明 |
|--------|------|------|------|
| `TIMEOUT` | int | `60` | 请求超时（引用 `NetworkConstants.LONG_TIMEOUT`） |
| `HISTORICAL_URL` | str | `"https://stockpage.10jqka.com.cn/{symbol}/"` | 历史数据页面 URL 模板 |
| `REALTIME_API_URLS` | list | 见下方 | 实时数据 API URL 列表 |

**REALTIME_API_URLS 列表内容：**

| 索引 | URL |
|------|-----|
| 0 | `https://stockpage.10jqka.com.cn/{symbol}/` |
| 1 | `https://basic.10jqka.com.cn/{symbol}/` |

---

## DataLakeConstants

数据湖相关常量。

| 字段名 | 类型 | 值 | 说明 |
|--------|------|------|------|
| `DEFAULT_ROOT_PATH` | str | `"data/lake"` | 默认根目录路径 |
| `QUARANTINE_PATH` | str | `"data/quarantine"` | 隔离区目录路径 |
| `DEFAULT_CACHE_SIZE` | int | `100` | 默认缓存大小 |
| `DEFAULT_MARKET` | str | `"cn"` | 默认市场 |
| `DEFAULT_DATA_TYPE` | str | `"stock"` | 默认数据类型 |
| `MAX_WORKERS` | int | `4` | 最大工作线程数 |

---

## UIConstants

UI 显示相关常量。

| 字段名 | 类型 | 值 | 说明 |
|--------|------|------|------|
| `DASHBOARD_PORT` | int | `8504` | 仪表盘端口 |
| `DEFAULT_THEME` | str | `"dark"` | 默认主题 |
| `REFRESH_INTERVAL_MS` | int | `10000` | 刷新间隔 10 秒 |
| `MAX_DISPLAY_ROWS` | int | `50` | 最大显示行数 |
| `CHART_HEIGHT` | int | `600` | 图表高度（像素） |
| `SIDEBAR_WIDTH` | int | `300` | 侧边栏宽度（像素） |
| `SUCCESS_COLOR` | str | `"#00C781"` | 成功状态颜色（绿色） |
| `WARNING_COLOR` | str | `"#FF9D00"` | 警告状态颜色（橙色） |
| `DANGER_COLOR` | str | `"#FF4B4B"` | 危险状态颜色（红色） |
| `INFO_COLOR` | str | `"#00A2FF"` | 信息状态颜色（蓝色） |

---

## TestConstants

测试相关常量，涵盖各类测试场景的参数配置。

| 字段名 | 类型 | 值 | 说明 |
|--------|------|------|------|
| `DEFAULT_TEST_DAYS` | int | `365` | 默认测试天数 |
| `DEFAULT_TEST_COUNT` | int | `3` | 默认测试次数 |
| `DEFAULT_TEST_THRESHOLD` | float | `0.85` | 默认测试阈值 |
| `DEFAULT_TEST_LOWER_THRESHOLD` | float | `0.75` | 默认测试下限阈值 |
| `RISK_TEST_CONFIDENCE` | float | `0.95` | 风险测试置信水平 |
| `RISK_TEST_PCT` | float | `0.05` | 风险测试百分比 |
| `RISK_TEST_VALUE` | float | `100000.0` | 风险测试基础值 |
| `RISK_TEST_PERCENTILE` | float | `95.0` | 风险测试百分位 |
| `SERVICE_TEST_DAYS` | int | `120` | 服务测试天数 |
| `SERVICE_TEST_START` | int | `101` | 服务测试起始值 |
| `SERVICE_TEST_END` | int | `121` | 服务测试结束值 |
| `SERVICE_TEST_INTERVAL` | int | `30` | 服务测试间隔 |
| `ANALYSIS_TEST_THRESHOLD` | float | `0.3` | 分析测试阈值 |
| `ANALYSIS_TEST_BASE` | int | `1000000` | 分析测试基础值 |
| `ANALYSIS_TEST_PCT` | float | `0.02` | 分析测试百分比 |
| `RETRY_TEST_COUNT` | int | `3` | 重试测试次数 |
| `RETRY_TEST_DELAY` | float | `0.1` | 重试测试延迟（秒） |
| `RETRY_TEST_BACKOFF` | float | `0.2` | 重试测试退避因子 |
| `ERROR_TEST_THRESHOLD` | float | `0.1` | 误差测试阈值 |
| `ERROR_TEST_COUNT` | int | `4` | 误差测试计数 |
| `MARKET_TEST_THRESHOLD` | float | `0.5` | 市场测试阈值 |
| `MARKET_TEST_DAYS` | int | `6` | 市场测试天数 |
| `TEST_ANALYSIS_THRESHOLD` | float | `0.3` | 测试分析阈值 |
| `TEST_ANALYSIS_BASE` | int | `1000000` | 测试分析基础值 |
| `TEST_ANALYSIS_PCT` | float | `0.02` | 测试分析百分比 |
| `TEST_RISK_PCT` | float | `0.05` | 测试风险百分比 |
| `TEST_RISK_VALUE` | float | `100000.0` | 测试风险值 |
| `TEST_RISK_CONFIDENCE` | float | `0.95` | 测试风险置信水平 |
| `TEST_RISK_PERCENTILE` | float | `95.0` | 测试风险百分位 |
| `TEST_SERVICE_DAYS` | int | `120` | 测试服务天数 |
| `TEST_SERVICE_START` | int | `101` | 测试服务起始值 |
| `TEST_SERVICE_END` | int | `121` | 测试服务结束值 |
| `TEST_SERVICE_INTERVAL` | int | `30` | 测试服务间隔 |
| `TEST_RETRY_COUNT` | int | `3` | 测试重试次数 |
| `TEST_RETRY_DELAY` | float | `0.1` | 测试重试延迟（秒） |
| `TEST_RETRY_BACKOFF` | float | `0.2` | 测试重试退避因子 |
| `TEST_ERROR_THRESHOLD` | float | `0.1` | 测试误差阈值 |
| `TEST_ERROR_COUNT` | int | `4` | 测试误差计数 |
| `TEST_MARKET_THRESHOLD` | float | `0.5` | 测试市场阈值 |
| `TEST_MARKET_DAYS` | int | `6` | 测试市场天数 |
| `TEST_CACHE_TTL` | int | `3600` | 测试缓存过期时间（秒） |
| `TEST_DATA_COUNT` | int | `5` | 测试数据计数 |
| `TEST_DATA_THRESHOLD` | float | `0.85` | 测试数据阈值 |
| `TEST_DATA_LOWER_THRESHOLD` | float | `0.75` | 测试数据下限阈值 |
| `TEST_EXECUTION_TIMEOUT` | int | `300` | 测试执行超时时间（秒） |
| `TEST_EXECUTION_INTERVAL` | int | `5` | 测试执行间隔（秒） |
| `TEST_RESULT_PASS_THRESHOLD` | float | `0.8` | 测试结果通过阈值 |
| `TEST_RESULT_WARNING_THRESHOLD` | float | `0.6` | 测试结果警告阈值 |
| `TEST_RESULT_FAIL_THRESHOLD` | float | `0.4` | 测试结果失败阈值 |
| `TEST_DATA_START_VALUE` | int | `100` | 测试数据起始值 |
| `TEST_DATA_END_VALUE` | int | `120` | 测试数据结束值 |
| `TEST_DATA_START_VALUE_LARGE` | int | `1000` | 测试数据起始值（大） |
| `TEST_DATA_END_VALUE_LARGE` | int | `1200` | 测试数据结束值（大） |
| `TEST_DATA_VOLUME_START` | int | `1000` | 测试成交量起始值 |
| `TEST_DATA_VOLUME_END` | int | `2000` | 测试成交量结束值 |
| `TEST_DATA_VOLUME_START_LARGE` | int | `10000` | 测试成交量起始值（大） |
| `TEST_DATA_VOLUME_END_LARGE` | int | `20000` | 测试成交量结束值（大） |
| `TEST_DATA_OFFSET` | int | `1` | 测试数据偏移量 |
| `TEST_DATA_OFFSET_LARGE` | int | `10` | 测试数据偏移量（大） |

---

## ToolConstants

工具相关常量，用于代码质量分析和架构检查。

| 字段名 | 类型 | 值 | 说明 |
|--------|------|------|------|
| `ANALYSIS_MAX_WORKERS` | int | `5` | 分析最大工作线程数 |
| `ANALYSIS_TIMEOUT` | int | `300` | 分析超时时间（秒） |
| `CODE_QUALITY_MAX_LINES` | int | `50` | 单函数最大行数 |
| `CODE_QUALITY_MAX_METHODS` | int | `20` | 单类最大方法数 |
| `CODE_QUALITY_MAX_ATTRIBUTES` | int | `15` | 单类最大属性数 |
| `CODE_QUALITY_MAX_IMPORTS` | int | `20` | 单文件最大导入数 |
| `CODE_QUALITY_MAX_NESTING` | int | `4` | 最大嵌套深度 |
| `ARCHITECTURE_CHECK_LEVEL_1` | int | `3` | 架构检查级别 1 |
| `ARCHITECTURE_CHECK_LEVEL_2` | int | `4` | 架构检查级别 2 |
| `ARCHITECTURE_CHECK_LEVEL_3` | int | `5` | 架构检查级别 3 |
| `STYLE_CHECK_MAX_LINE_LENGTH` | int | `500` | 样式检查最大行长度 |
| `STYLE_CHECK_INDENT_THRESHOLD` | float | `0.1` | 样式检查缩进阈值 |
| `REPORT_LINE_LENGTH` | int | `60` | 报告行长度 |
| `ANALYSIS_MAX_ITEMS` | int | `5` | 分析结果最大显示项数 |
| `CODE_ANALYSIS_MIN_LINE_LENGTH` | int | `20` | 代码分析最小行长度 |
| `CODE_ANALYSIS_MAX_DISPLAY_LENGTH` | int | `50` | 代码分析最大显示长度 |
| `CODE_ANALYSIS_MAX_DUPLICATES` | int | `5` | 代码分析最大重复项数 |

---

## DataServiceConstants

数据服务相关常量。

| 字段名 | 类型 | 值 | 说明 |
|--------|------|------|------|
| `CACHE_TTL_STOCK` | int | `3600` | 股票数据缓存 1 小时 |
| `CACHE_TTL_INDEX` | int | `7200` | 指数数据缓存 2 小时 |
| `CACHE_TTL_ETF` | int | `3600` | ETF 数据缓存 1 小时 |
| `CACHE_TTL_REALTIME` | int | `300` | 实时数据缓存 5 分钟 |
| `CACHE_TTL_INDUSTRY` | int | `86400` | 行业数据缓存 1 天 |
| `CACHE_TTL_CONCEPT` | int | `86400` | 概念数据缓存 1 天 |
| `CACHE_TTL_GENERAL` | int | `3600` | 通用数据缓存 1 小时 |
| `QUALITY_SCORE_EXCELLENT` | int | `90` | 数据质量评分：优秀 |
| `QUALITY_SCORE_GOOD` | int | `75` | 数据质量评分：良好 |
| `QUALITY_SCORE_FAIR` | int | `60` | 数据质量评分：一般 |
| `TIMELINESS_SCORE_TODAY` | float | `1.0` | 时效性评分：今天 |
| `TIMELINESS_SCORE_1_DAY` | float | `0.9` | 时效性评分：1 天内 |
| `TIMELINESS_SCORE_3_DAYS` | float | `0.7` | 时效性评分：3 天内 |
| `TIMELINESS_SCORE_7_DAYS` | float | `0.5` | 时效性评分：7 天内 |
| `TIMELINESS_SCORE_30_DAYS` | float | `0.3` | 时效性评分：30 天内 |
| `TIMELINESS_SCORE_OLD` | float | `0.1` | 时效性评分：超过 30 天 |
| `TIMELINESS_THRESHOLD_1_DAY` | int | `1` | 时效性阈值：1 天 |
| `TIMELINESS_THRESHOLD_3_DAYS` | int | `3` | 时效性阈值：3 天 |
| `TIMELINESS_THRESHOLD_7_DAYS` | int | `7` | 时效性阈值：7 天 |
| `TIMELINESS_THRESHOLD_30_DAYS` | int | `30` | 时效性阈值：30 天 |

---

## NTFConstants

NTF（成交量-价格偏离度）引擎相关常量。

| 字段名 | 类型 | 值 | 说明 |
|--------|------|------|------|
| `HEAT_THRESHOLD` | float | `0.8` | 过热阈值（分位数高于 80%） |
| `PANIC_THRESHOLD` | float | `0.1` | 恐慌阈值（分位数低于 10%） |
| `VOLUME_RATIO_THRESHOLD` | float | `2.0` | 成交量脉冲阈值 |
| `WINDOW` | int | `20` | 计算成交量均值的窗口大小 |
| `CONFIDENCE_SUPPORT` | float | `0.85` | 支撑信号置信度 |
| `CONFIDENCE_RESISTANCE` | float | `0.80` | 阻力信号置信度 |
| `CONFIDENCE_LIQUIDITY` | float | `0.40` | 流动性脉冲置信度 |

---

## LPPLConstants

LPPL（Log-Periodic Power Law）泡沫检测相关常量。

| 字段名 | 类型 | 值 | 说明 |
|--------|------|------|------|
| `MAX_ITER` | int | `500` | 优化器最大迭代次数 |
| `POP_SIZE` | int | `10` | 差分进化种群大小 |
| `TOLERANCE` | float | `0.01` | 优化容差 |
| `MUTATION_MIN` | float | `0.5` | 变异因子最小值 |
| `MUTATION_MAX` | float | `1.0` | 变异因子最大值 |
| `RECOMBINATION` | float | `0.7` | 重组概率 |
| `SEED` | int | `42` | 随机种子 |
| `WORKERS` | int | `1` | 工作进程数 |
| `RMSE_REJECT_THRESHOLD` | float | `0.1` | RMSE 拒绝阈值 |
| `MIN_DATA_POINTS` | int | `60` | 最小数据点数 |
| `TC_SEARCH_RANGE` | int | `50` | tc 搜索范围 |
| `TC_FUTURE_RANGE` | int | `100` | tc 未来范围 |
| `TC_BACKWARD` | int | `50` | tc 向后搜索范围 |
| `TC_FORWARD` | int | `100` | tc 向前搜索范围 |
| `A_MULTIPLIER` | float | `1.1` | A 参数乘数 |
| `B_MIN` | int | `-20` | B 参数下界 |
| `B_MAX` | int | `20` | B 参数上界 |
| `C_MIN` | int | `-20` | C 参数下界 |
| `C_MAX` | int | `20` | C 参数上界 |
| `PHI_MAX` | float | `6.283185307179586` | Phi 参数上界（2*pi） |
| `M_MIN` | float | `0.1` | Sornette 约束：m 最小值 |
| `M_MAX` | float | `0.9` | Sornette 约束：m 最大值 |
| `W_MIN` | int | `6` | Sornette 约束：w 最小值 |
| `W_MAX` | int | `13` | Sornette 约束：w 最大值 |
| `C_MIN_ABS` | float | `0.01` | C 绝对值最小值 |
| `C_ABS_FOR_BUBBLE` | float | `0.1` | 判定泡沫的 C 绝对值阈值 |
| `TC_WEIGHT` | float | `0.4` | 置信度计算中 tc 权重 |
| `COST_WEIGHT` | float | `0.4` | 置信度计算中 cost 权重 |
| `DATA_WEIGHT` | float | `0.2` | 置信度计算中数据权重 |
| `DATA_REFERENCE` | int | `200` | 数据参考长度 |
| `COST_SCALE` | float | `0.1` | 代价函数缩放因子 |
| `CONFIDENCE_THRESHOLD` | float | `0.6` | 置信度阈值 |
| `CONFIDENCE_WARNING` | float | `0.4` | 置信度警告阈值 |
| `DANGER_DAYS` | int | `10` | 危险天数阈值 |
| `WARNING_DAYS` | int | `20` | 警告天数阈值 |
| `CACHE_ENABLED` | bool | `True` | 是否启用缓存 |
| `CACHE_PRECISION` | int | `4` | 缓存精度（小数位） |
| `EPSILON` | float | `1e-10` | 极小值常量 |
| `WINDOWS_ALL` | list | `[100, 150, 200, 250, 300, 400, 500, 600, 750]` | 全部扫描窗口 |
| `WINDOWS_LIST` | list | `[200, 400, 600]` | 默认窗口列表 |
| `DATA_LENGTH_LARGE` | int | `600` | 大数据长度回退值 |
| `TC_DAYS_DEFAULT_LARGE` | int | `150` | 大数据 tc 天数默认值 |
| `DATA_LENGTH_MEDIUM` | int | `300` | 中数据长度回退值 |
| `TC_DAYS_DEFAULT_MEDIUM` | int | `80` | 中数据 tc 天数默认值 |
| `TC_DAYS_DEFAULT_SMALL` | int | `40` | 小数据 tc 天数默认值 |

---

## RegimeConstants

市场状态检测器相关常量。

| 字段名 | 类型 | 值 | 说明 |
|--------|------|------|------|
| `ENTROPY_PERCENTILE_THRESHOLD` | float | `0.1` | 熵值分位数阈值（低于此值为 FROZEN 状态） |
| `TURNOVER_Z_SCORE_THRESHOLD` | float | `2.5` | 成交量 Z-Score 阈值（绝对值超过此值为 STRESSED 状态） |
| `MIN_DATA_POINTS` | int | `30` | 最小数据点数 |
| `ENTROPY_WINDOW` | int | `60` | 熵值计算窗口 |
| `TURNOVER_Z_PERIOD` | int | `20` | 成交量 Z-Score 计算周期 |

---

## UATConstants

UAT 测试相关常量。

| 字段名 | 类型 | 值 | 说明 |
|--------|------|------|------|
| `UAT_TEST_DAYS` | int | `365` | UAT 测试天数 |
| `UAT_TEST_COUNT` | int | `3` | UAT 测试次数 |
| `UAT_TEST_INTERVAL` | int | `5` | UAT 测试间隔 |
| `UAT_TEST_THRESHOLD` | int | `3` | UAT 测试阈值 |

---

## ResultsConstants

计算结果管理相关常量。

| 字段名 | 类型 | 值 | 说明 |
|--------|------|------|------|
| `RESULTS_DIR_NAME` | str | `"results"` | 结果目录名 |
| `REPORTS_DIR_NAME` | str | `"reports"` | 报告目录名 |
| `HANDS_DIR_NAME` | str | `"hands"` | 交易记录目录名 |
| `REVIEW_DIR_NAME` | str | `"review"` | 复盘目录名 |
| `RESULTS_FILE_SUFFIX` | str | `".json"` | 结果文件后缀 |
| `REPORT_FILE_PREFIX` | str | `"Report_"` | 报告文件前缀 |
| `REPORT_FILE_SUFFIX` | str | `".md"` | 报告文件后缀 |
| `RESULTS_DATE_FORMAT` | str | `"%Y%m%d"` | 结果日期格式 |
| `REPORT_DATE_FORMAT` | str | `"%Y-%m-%d"` | 报告日期格式 |
| `DATE_FOLDER_FORMAT` | str | `"%Y-%m-%d"` | 日期文件夹格式 |
| `USE_DATE_FOLDERS` | bool | `True` | 是否使用日期文件夹 |
| `MAX_RESULTS_PER_SYMBOL` | int | `30` | 每只股票最大结果数 |
| `CLEANUP_THRESHOLD_DAYS` | int | `30` | 清理阈值天数 |
| `JSON_INDENT` | int | `2` | JSON 缩进空格数 |
| `ENCODING` | str | `"utf-8"` | 文件编码 |

---

## BacktestConstants

回测引擎相关常量。

| 字段名 | 类型 | 值 | 说明 |
|--------|------|------|------|
| `DEFAULT_INITIAL_CAPITAL` | float | `100000.0` | 默认初始资金 10 万元 |
| `DEFAULT_COMMISSION_RATE` | float | `0.0003` | 佣金率 0.03% |
| `DEFAULT_STAMP_DUTY_RATE` | float | `0.001` | 印花税率 0.1%（仅卖出） |
| `DEFAULT_SLIPPAGE_RATE` | float | `0.001` | 滑点率 0.1% |
| `DEFAULT_MIN_COMMISSION` | float | `5.0` | 最低佣金 5 元 |
| `DEFAULT_TRAIN_WINDOW` | int | `252` | 默认训练窗口（1 年交易日） |
| `DEFAULT_TEST_WINDOW` | int | `63` | 默认测试窗口（1 季度交易日） |
| `MAX_POSITION_PCT` | float | `0.95` | 最大仓位比例 95% |
| `MIN_CASH_RESERVE` | float | `1000.0` | 最小现金保留 1000 元 |

---

## MarketHours

A 股市场交易时间常量。该类同时提供方法用于判断市场状态。

### 常量字段

| 字段名 | 类型 | 值 | 说明 |
|--------|------|------|------|
| `MORNING_START_HOUR` | int | `9` | 上午开盘小时 |
| `MORNING_START_MINUTE` | int | `30` | 上午开盘分钟 |
| `MORNING_END_HOUR` | int | `11` | 上午收盘小时 |
| `MORNING_END_MINUTE` | int | `30` | 上午收盘分钟 |
| `AFTERNOON_START_HOUR` | int | `13` | 下午开盘小时 |
| `AFTERNOON_START_MINUTE` | int | `0` | 下午开盘分钟 |
| `AFTERNOON_END_HOUR` | int | `15` | 下午收盘小时 |
| `AFTERNOON_END_MINUTE` | int | `0` | 下午收盘分钟 |
| `TRADING_DAYS` | list | `[0, 1, 2, 3, 4]` | 交易日（周一=0 到 周五=4） |

### 类方法

| 方法名 | 参数 | 返回类型 | 说明 |
|--------|------|----------|------|
| `is_market_open(dt)` | `dt: Optional[datetime]` | `bool` | 检查指定时间市场是否开放 |
| `get_next_open_time(dt)` | `dt: Optional[datetime]` | `datetime` | 获取下一个市场开放时间 |
| `get_market_status(dt)` | `dt: Optional[datetime]` | `str` | 获取市场状态描述（交易中/休市/开盘前/已收盘/午休） |

---

## WindowConfig

LPPL 窗口配置数据类（`@dataclass(frozen=True)`）。

### 字段

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `short_windows` | `tuple[int, ...]` | 短窗口序列 |
| `medium_windows` | `tuple[int, ...]` | 中窗口序列 |
| `long_windows` | `tuple[int, ...]` | 长窗口序列 |

### 属性与方法

| 名称 | 返回类型 | 说明 |
|------|----------|------|
| `all_windows` (property) | `tuple[int, ...]` | 所有窗口的合并元组 |
| `get_category(window)` | `str` | 根据窗口大小返回分类：`"short"` (<200), `"medium"` (200-500), `"long"` (>500) |

### 默认实例 WINDOW_CONFIG

| 窗口类型 | 范围 | 步长 |
|----------|------|------|
| `short_windows` | 50 ~ 290 | 10 |
| `medium_windows` | 300 ~ 580 | 20 |
| `long_windows` | 600 ~ 1150 | 50 |

---

## 模块级 LPPL 常量

定义在类之外的 LPPL 相关模块级常量。

| 变量名 | 类型 | 值 | 说明 |
|--------|------|------|------|
| `REQUIRED_COLUMNS` | `list[str]` | `["date", "open", "close", "high", "low", "volume"]` | 必需的 DataFrame 列名 |
| `ENABLE_NUMBA_JIT` | bool | `True` | 是否启用 Numba JIT 编译 |
| `ENABLE_JOBLIB_PARALLEL` | bool | `True` | 是否启用 Joblib 并行计算 |
| `W_BOUNDS` | `tuple[float, float]` | `(5, 18)` | w 参数边界 |
| `M_BOUNDS` | `tuple[float, float]` | `(0.1, 0.9)` | m 参数边界 |
| `RANDOM_SEED` | int | `42` | 随机种子 |
| `OUTPUT_DIR` | str | `"output"` | 输出目录 |

---

## 模块级 Wyckoff 常量

定义在类之外的 Wyckoff 相关模块级常量。

| 变量名 | 类型 | 值 | 说明 |
|--------|------|------|------|
| `SPRING_LOW_FACTOR` | float | `1.01` | Spring 低点因子 |
| `SPRING_CLOSE_FACTOR` | float | `1.0` | Spring 收盘因子 |
| `MIN_RR_RATIO` | float | `2.5` | 最小风险收益比 |
| `MIN_WYCKOFF_DATA_ROWS` | int | `200` | Wyckoff 分析最小数据行数 |
| `BC_LOOKBACK_WINDOW` | int | `20` | BC（Buying Climax）回看窗口 |
| `SPRING_FREEZE_DAYS` | int | `3` | Spring 冻结天数 |
| `WYCKOFF_OUTPUT_DIR` | str | `"data/state/wyckoff"` | Wyckoff 输出目录 |
| `TR_MAX_RANGE_PCT` | float | `0.20` | 交易区间最大范围百分比 20% |
| `TR_MAX_SHORT_TREND` | float | `0.05` | 交易区间最大短期趋势 5% |
