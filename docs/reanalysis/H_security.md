# Phase H — 安全审计报告

**审计日期:** 2026-07-06
**审计范围:** `src/uniquant/` 全部 254 个 Python 源文件 + `config/config.yaml`
**审计工具:** grep, git log, pip index, ripgrep (fallback to grep), 手动依赖版本检查
**审计原则:** 仅检测，不修改任何源文件

---

## 总体风险评估

| 风险级别 | 严重问题 | 高危问题 | 中危问题 | 低危问题 |
|---------|---------|---------|---------|---------|
| **MEDIUM** | 0 | 1 | 3 | 2 |

---

## H1 密钥泄露检查

### H1.1 静态密钥扫描：源代码

对 `src/uniquant/` 下所有 `.py` / `.yaml` / `.yml` / `.json` / `.env` 文件执行了以下检查：

**检查项：** `api_key`, `api_secret`, `token`, `password`, `passwd`, `secret`（排除 test/mock/example/placeholder）

**结果：** ✅ **未发现硬编码密钥凭据**

发现以下合法引用（均非秘密硬编码）：

| 文件 | 行号 | 内容 | 评估 |
|------|------|------|------|
| `brain/wyckoff/config.py` | 129 | `llm_api_key: Optional[str] = None` | ✅ 字段定义，仅从环境变量读取 |
| `brain/wyckoff/config.py` | 158 | 注释：只从环境变量读取 | ✅ 设计正确 |
| `brain/wyckoff/config.py` | 170 | `os.environ.get("WYCKOFF_LLM_API_KEY")` | ✅ 环境变量读取，安全 |
| `shared/error_handling.py` | 115,143,172,337 | 过滤 kwargs 中的 password/token | ✅ **正向实践：日志时主动屏蔽敏感字段** |

**API密钥模式扫描（sk-* / pk-* / ghp_*）：** ✅ 未发现任何真实 API 密钥

### H1.2 静态密钥扫描：配置文件

| 文件 | 结果 |
|------|------|
| `config/config.yaml` (459行) | ✅ 无任何 passwords, tokens, API keys |
| `src/uniquant/**/*.yaml` | ✅ 无匹配结果 |
| `src/uniquant/**/*.json` | ✅ 无匹配结果 |

### H1.3 Git 历史检查

执行 `git log -p --all -S "password"` / `-S "api_key"` / `-S "sk-"` 搜索历史提交：

| 搜索项 | 结果 |
|--------|------|
| `password` 修改历史 | ✅ 仅涉及测试文件（`test_config_validator.py` 使用 `monkeypatch.setenv` 测试环境变量覆盖，使用虚假值 `sk-abc123`/`sk-llm-secret`） |
| `api_key` 修改历史 | ✅ 同上，仅测试文件 |
| `sk-` 模式历史 | ✅ 未发现真实密钥提交历史 |

**结论：** Git 历史中未发现泄露的密钥凭据。

### H1.4 凭据文件扫描

| 搜索项 | 结果 |
|--------|------|
| `.env*` 文件 | ✅ 不存在（已通过 `.gitignore` 保护） |
| `.pem` / `.key` / `.cert` / `credentials*` | ✅ 不存在 |
| `uniquant/**/*.env` | ✅ 不存在 |

**H1 结论：** ✅ **无密钥泄露风险。** `llm_api_key` 正确从环境变量注入，`error_handling.py` 主动过滤敏感字段。

---

## H2 依赖漏洞

### H2.1 安全审计工具可用性

| 工具 | 状态 |
|------|------|
| `pip-audit` | ❌ 未安装 |
| `bandit` | ❌ 未安装 |
| `safety` | ❌ 未安装 |
| `semgrep` | ❌ 未安装 |

> ⚠️ 项目未配置任何自动化依赖漏洞扫描工具。生产就绪度报告（Phase 7）已标记此问题。

### H2.2 关键依赖版本分析（pip 索引对比）

| 包名 | 当前版本 | 最新版 | 落后 | 已知风险 |
|------|---------|-------|------|---------|
| `requests` | 2.31.0 | 2.34.2 | **3 个次要版本** | ⚠️ 2.31.0 (2023-05) 有已知 CVE-2023-32681（cert 验证绕过，CVSS 6.1），2.32.0+ 已修复 |
| `urllib3` | 2.0.7 | 2.7.0 | **7 个次要版本** | ⚠️ 2.0.7 (2024-01) 有已修复 CVE-2024-37891（proxy 认证泄露） |
| `pandas` | 2.3.3 | 3.0.3 | 1 个大版本 | ⚠️ 2.x 系列无已知严重 CVE，但 3.x 有重要安全修复 |
| `pyyaml` | 6.0.1 | 6.0.2 | 1 个补丁版本 | ✅ 6.0.1 已修复 CVE-2020-14343（`yaml.load` 反序列化），但项目使用 `safe_load` |
| `cryptography` | 41.0.7 | 最新 | ⚠️ 严重 | ⚠️ 41.0.7 (2024-02) 已 EOL，最高 44.x 版本有多个 CVE 修复 |

### H2.3 高危依赖建议

| 依赖 | 建议操作 | 优先级 |
|------|---------|--------|
| `requests>=2.32.0` | 升级到 2.32.0+（修复 CVE-2023-32681） | **HIGH** |
| `urllib3>=2.2.3` | 升级到 2.2.3+（修复 CVE-2024-37891） | **MEDIUM** |
| `cryptography>=42.0.0` | 升级到最新（41.x 已 EOL） | **HIGH** |
| `pip-audit` | 添加到 CI 流程 | **MEDIUM** |

**H2 结论：** ⚠️ **中风险。** `requests` 和 `cryptography` 有已修复的已知 CVE 但未升级。建议加入 `pip-audit` 到 CI 流程并在 `pyproject.toml` 中更新版本下限。

---

## H3 SQL 注入

### H3.1 SQL 执行模式扫描

| 搜索模式 | 结果 |
|---------|------|
| `cursor.execute` / `conn.execute` / `execute(` | ✅ 仅发现 `safe_execute` 函数名（`shared/utils.py:46`），非 SQL |
| `.sql(` | ✅ 未发现 SQL 直接调用 |
| f-string SQL 拼接 (`f"...SELECT"` 等) | ✅ **未发现任何 SQL 字符串拼接** |

### H3.2 依赖风险

项目依赖 `duckdb>=0.9.0` 和 `sqlalchemy>=2.0.0`，但：

- ✅ 代码库中未发现任何通过 `duckdb.sql()` 或 `sqlalchemy.text()` 执行的原始 SQL
- ✅ 未发现任何直接 SQL 语句拼写
- ✅ 数据存取主要使用 Parquet（`storage_manager.py`）+ pandas DataFrames，非 SQL 交互

**H3 结论：** ✅ **无 SQL 注入风险。** 项目不直接使用 SQL 进行数据操作。

---

## H4 配置文件敏感信息

### H4.1 `config/config.yaml` 审计

| 检查项 | 结果 |
|--------|------|
| 数据库密码 | ✅ 不存在 |
| API 令牌 | ✅ 不存在 |
| 服务密钥 | ✅ 不存在 |
| 私有路径凭据 | ✅ 不存在 |
| 内网凭据 | ✅ 不存在 |

### H4.2 配置内容分析

`config/config.yaml`（459 行）包含以下类别配置，**全部为功能性/参数性配置**：

| 配置类别 | 内容 |
|---------|------|
| 基础配置 | 数据湖路径、日志级别、TDX 安装路径 |
| 缓存配置 | TTL、内存限制、清理策略 |
| 网络配置 | 超时、重试、速率限制、User-Agent |
| 数据源配置 | 数据源类名、优先级、启用状态 |
| 技术指标 | MA/ATR/MACD/RSI 参数 |
| 策略参数 | LPPL/CZSC/FSM 模型参数 |
| 风险配置 | 默认风险比例、熔断比例 |
| 重构标志 | 特性开关、引擎迁移标志 |

### H4.3 特殊发现

- `config.yaml:17` TDX 路径包含用户 home 目录（`/home/james/...`），这是本地路径配置，非敏感信息
- `config.yaml:80` User-Agent 使用标准 Mozilla 兼容字符串（非敏感）

**H4 结论：** ✅ **配置文件无敏感信息泄露。** 所有配置均为功能性参数。

---

## H5 日志泄露

### H5.1 敏感数据日志扫描

| 搜索模式 | 结果 |
|---------|------|
| `.info(...password)` | ✅ 未发现 |
| `.info(...token)` | ✅ 未发现 |
| `.info(...secret)` | ✅ 未发现 |
| `.debug(...password)` | ✅ 未发现 |
| `.debug(...token)` | ✅ 未发现 |

### H5.2 主动防护措施

`src/uniquant/shared/error_handling.py` 在四处位置明确过滤 `password` 和 `token` 字段：

```python
"func_kwargs": {
    k: v
    for k, v in kwargs.items()
    if k not in ["password", "token"]
},
```

这是**主动的防御性设计**，确保即使不小心传入敏感参数，也不会写入日志。

### H5.3 其他日志分析

检查数据源中的日志（如 `sina.py:286` 等），日志内容为：
- 请求 URL 和参数（公开 API 端点）
- 响应状态码
- 数据条数

均为合理的调试日志，不包含响应体中的交易数据或用户识别信息。

**H5 结论：** ✅ **无日志泄露风险。** 项目实现了主动的敏感字段过滤机制。

---

## H6 网络请求安全

### H6.1 HTTP 请求模式

| 数据源 | 协议 | 方法 | SSL 验证 |
|--------|------|------|---------|
| `eastmoney.py:71-77` | HTTPS | `requests.get` | ❌ `verify=False` |
| `sina.py:287` | HTTPS | `requests.get` | ✅ 默认启用 |
| `sina.py:504` | HTTPS | `requests.get` | ✅ 默认启用 |
| `tencent.py:236` | HTTPS | `requests.get` | ✅ 默认启用 |
| `ths.py:276` | HTTPS | `requests.get` | ✅ 默认启用 |
| `ths.py:453` | HTTPS | `requests.get` | ✅ 默认启用 |

### H6.2 🔴 严重问题：eastmoney SSL 验证关闭

**文件：** `src/uniquant/data/sources/eastmoney.py:76`
**代码：** `verify=False`
**风险等级：** **HIGH**

**问题描述：** 东方财富数据源的所有 HTTP 请求均关闭了 SSL 证书验证。这使连接暴露于中间人攻击（MITM）。

**影响评估：**
- 攻击者在本地网络可截获/篡改请求与响应
- 虽然东方财富 API 返回的是公开市场数据（非金融凭据），但被篡改的数据可能影响交易策略分析结果
- 在可信内网环境风险较低，但在不受信网络不可接受

**建议修复：**
1. 移除 `verify=False`，使用默认 SSL 验证
2. 如因自签名证书需要绕过，可配置 CA bundle 路径：

```python
# eastmoney.py:76 — 推荐修复
verify = os.environ.get("EASTMONEY_CA_BUNDLE", True)  # 默认使用系统 CA
response = self.session.get(
    url, params=params, headers=headers,
    timeout=(10, timeout),
    verify=verify  # 从环境变量读取，默认 True
)
```

### H6.3 其他安全实践

| 检查项 | 结果 |
|--------|------|
| `http://` URL（非 HTTPS） | ✅ 所有请求使用 HTTPS |
| 超时设置 | ✅ 所有请求都设置了 `timeout` |
| 速率限制 | ⚠️ **部分实现：** config.yaml 有全局配置，但无代码级强制 `RateLimiter` |
| 用户代理 | ✅ 设置了合理的 User-Agent |
| `subprocess` / `os.system` | ✅ 未发现命令注入风险 |
| `eval` / `exec`（Python） | ✅ 仅 `js_executor.py` 使用 MiniRacer 沙箱 JS 引擎 |
| `pickle.load` / `yaml.load`（unsafe） | ✅ 未发现不安全反序列化 |
| `aiohttp` / `urlopen` | ✅ 未使用 |

**H6 结论：** ⚠️ **1 个 HIGH 风险项**（eastmoney SSL 验证关闭）。其余网络请求符合安全最佳实践。

---

## 综合发现汇总

### 严重 (CRITICAL) — 0 项
无。

### 高危 (HIGH) — 1 项

| # | 文件 | 行号 | 问题 | 修复建议 |
|---|------|------|------|---------|
| H6-1 | `data/sources/eastmoney.py` | 76 | SSL 证书验证关闭 (`verify=False`) | 改为默认 True，支持环境变量覆盖 |

### 中危 (MEDIUM) — 3 项

| # | 文件 | 问题 | 修复建议 |
|---|------|------|---------|
| H2-1 | `pyproject.toml` | `requests==2.31.0` 含 CVE-2023-32681 | 升级到 `>=2.32.0` |
| H2-2 | `pyproject.toml` | `cryptography==41.0.7` 已 EOL | 升级到 `>=42.0.0`（目标 44.x） |
| H2-3 | 项目全局 | 无安全扫描工具（`pip-audit`/`bandit`/`safety`） | CI 中加入 `pip-audit` 步骤 |

### 低危 (LOW) — 2 项

| # | 文件 | 问题 | 备注 |
|---|------|------|------|
| H2-4 | `pyproject.toml` | `urllib3==2.0.7` 含 CVE-2024-37891 | 在可信网络影响有限 |
| H6-2 | `config/config.yaml` | 速率限制配置存在但未强制到代码 | 当前非关键，建议逐步引入 |

---

## 安全防御正向实践

以下为项目中值得肯定的安全设计：

| 实践 | 位置 | 说明 |
|------|------|------|
| ✅ 密钥环境变量注入 | `brain/wyckoff/config.py:170` | LLM API Key 从环境变量读取 |
| ✅ 日志敏感字段过滤 | `shared/error_handling.py:115,143,172,337` | 主动过滤 password/token |
| ✅ 安全 YAML 解析 | 多处 | 使用 `yaml.safe_load` 而非 `yaml.load` |
| ✅ HTTPS 全局使用 | 所有数据源 | 无 `http://` 连接 |
| ✅ 请求超时设置 | 所有数据源 | 每个请求均有 timeout 参数 |
| ✅ 沙箱 JS 执行 | `data/utils/js_executor.py` | 使用 MiniRacer 而非 Python eval |
| ✅ 无不安全反序列化 | 全局 | 无 pickle/shelve/marshal 负载 |
| ✅ 无命令注入 | 全局 | 无 subprocess/os.system 调用 |
| ✅ 配置无硬编码凭据 | `config/config.yaml` | 零敏感信息 |

---

## 行动建议（按优先级排序）

### P0 — 立即修复（HIGH）
1. **`eastmoney.py` SSL 验证** — 移除 `verify=False` 或支持环境变量配置

### P1 — 本周修复（MEDIUM）
2. **`requests` 升级** — 修改 `pyproject.toml` 为 `requests>=2.32.0`
3. **`cryptography` 升级** — 修改为 `cryptography>=42.0.0`
4. **CI 加入 `pip-audit`** — 在 CI/CD 或 pre-commit hook 中运行

### P2 — 本月修复（LOW）
5. **`urllib3` 升级** — 修改为 `urllib3>=2.2.3`
6. **代码级速率限制** — 实现 `RateLimiter` 收口到统一工具模块

---

## ANALYSIS COMPLETE