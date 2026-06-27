# R6 Security & Data Integrity Audit Report

**Audit Date:** 2026-06-06
**Auditor:** UniQuant R6 Security & Data Integrity Auditor
**Scope:** StorageManager, ConfigLoader, TDX Parser, config.yaml
**Severity Scale:** CRITICAL / HIGH / MEDIUM / LOW / INFO

---

## Executive Summary

| Severity | Count | Status |
|----------|-------|--------|
| CRITICAL | 0     | --     |
| HIGH     | 2     | Open   |
| MEDIUM   | 4     | Open   |
| LOW      | 3     | Open   |
| INFO     | 3     | Noted  |

No CRITICAL vulnerabilities found. Two HIGH-severity issues require attention: path traversal exposure in `write_parquet()` and `save_stock_gbbq_data()`, and a JS engine that executes file content without integrity verification.

---

## 1. Path Traversal Analysis

### 1.1 `StorageManager.write_parquet()` -- HIGH

**File:** `/home/james/Documents/Project/UniQuant/src/uniquant/data/lake/storage_manager.py` (lines 64-89)

**Finding:** The `file_path` parameter is passed directly to `Path()` and used to construct directories and files with no validation. A caller passing a user-controlled string such as `"../../etc/cron.d/malicious.parquet"` would write files outside the intended `data_dir`.

```python
def write_parquet(self, file_path: str, df: pd.DataFrame, overwrite: bool = False) -> bool:
    file_path_obj = Path(file_path)           # No validation
    dir_path = file_path_obj.parent
    self.ensure_directory(str(dir_path))       # Creates arbitrary directories
    ...
    df.to_parquet(file_path, ...)              # Writes to arbitrary location
```

**Risk:** Arbitrary file write if any upstream code passes unsanitized user input to `write_parquet()`.

**Recommendation:**
- Validate that the resolved `file_path` is within `self.data_dir`:
  ```python
  resolved = file_path_obj.resolve()
  if not str(resolved).startswith(str(self.data_dir.resolve())):
      raise DataStorageError(f"Path traversal detected: {file_path}")
  ```

### 1.2 `StorageManager.save_stock_gbbq_data()` -- HIGH

**File:** `/home/james/Documents/Project/UniQuant/src/uniquant/data/parsers/tdx_parser.py` (lines 282-289)

**Finding:** The `code` parameter is interpolated directly into a file path:

```python
output_path = Path(output_dir) / f"{code}.parquet"
df.to_parquet(str(output_path), compression="snappy")
```

If `code` contains `../../` or similar traversal sequences, files can be written outside `output_dir`.

**Risk:** Arbitrary file write via crafted stock code string.

**Recommendation:**
- Sanitize `code` to contain only alphanumeric characters and dots:
  ```python
  import re
  if not re.match(r'^[A-Za-z0-9.]+$', code):
      raise ValueError(f"Invalid stock code: {code}")
  ```

### 1.3 `_get_file_path()` -- LOW (Mitigated)

**File:** `/home/james/Documents/Project/UniQuant/src/uniquant/data/lake/storage_manager.py` (lines 495-514)

**Finding:** The `symbol` parameter is used in `f"{symbol}.parquet"` which becomes a single filename, not a path component. Python's `Path` operator `/` does not interpret slashes within a single path segment as directory separators in a dangerous way. However, if `symbol` contains `../`, the concatenation `self.daily_dir / f"{symbol}.parquet"` would create a path like `data/lake/quotes/daily/../../../etc/passwd.parquet` -- but this only happens if `Path` normalizes the combined path. In practice, Python's `pathlib` does normalize `..` in the final path, so this is still a traversal risk but mitigated by the fact that `symbol` comes from internal `_normalize_stock_code()` which strips non-numeric prefixes.

**Risk:** Low -- internal callers generally sanitize symbols.

---

## 2. Configuration Security

### 2.1 Config File -- No Hardcoded Secrets

**File:** `/home/james/Documents/Project/UniQuant/config/config.yaml` (430 lines)

**Finding:** The configuration file contains NO hardcoded API keys, passwords, or tokens. All sensitive fields are either:
- Set to `null` (SSL `client_cert`, `client_key`, `ca_bundle`)
- Loaded from environment variables (LLM API key in WyckoffConfig)

**Note (INFO):** Line 17 exposes a local filesystem path containing a username:
```yaml
tdx:
  path: "/home/james/.local/share/tdxcfv/drive_c/tc"
```
This is not a security vulnerability but exposes the system username. Consider using relative paths or environment variable substitution.

### 2.2 API Key Handling -- GOOD

**File:** `/home/james/Documents/Project/UniQuant/src/uniquant/brain/wyckoff/config.py` (lines 158-170)

**Finding:** `llm_api_key` is intentionally excluded from YAML parsing and loaded only from environment variable `WYCKOFF_LLM_API_KEY`. This follows security best practices.

```python
# NOTE: llm_api_key 只从环境变量读取，不写入 YAML 解析路径
config.llm_api_key = os.environ.get("WYCKOFF_LLM_API_KEY")
```

### 2.3 Error Logging Redaction -- GOOD

**File:** `/home/james/Documents/Project/UniQuant/src/uniquant/shared/error_handling.py` (lines 110-112, 138-140, 167-169, 334-336)

**Finding:** The `@handle_errors()` decorator filters out `password` and `token` kwargs before logging. This prevents credential leakage in error logs.

```python
"func_kwargs": {k: v for k, v in kwargs.items() if k not in ["password", "token"]},
```

**Recommendation (LOW):** Extend the filter to include `api_key`, `secret`, `credential`, and `client_key` for defense-in-depth.

### 2.4 `.gitignore` Coverage -- GOOD

**Finding:** `data/lake/`, `data/cache/`, `*.log`, `logs/`, and `__pycache__/` are all excluded from version control. No sensitive data files are tracked.

---

## 3. TDX Parser Buffer & Integer Overflow Analysis

### 3.1 `parse_day_file()` -- LOW (Safe)

**File:** `/home/james/Documents/Project/UniQuant/src/uniquant/data/parsers/tdx_parser.py` (lines 34-98)

**Finding:** The parser reads the entire file into memory (`f.read()`) and uses `struct.iter_unpack()` with format `<IIIIIfii` (32 bytes per record). `struct.iter_unpack` silently discards incomplete trailing bytes, preventing buffer over-read. Python's arbitrary-precision integers eliminate integer overflow risk.

**Potential Issue (LOW):** `file_size % 32 != 0` logs a warning but does not prevent parsing. Corrupted files with non-multiple-of-32 sizes will have their trailing bytes silently ignored. This is acceptable behavior.

### 3.2 `_parse_gbbq_manually()` -- MEDIUM

**File:** `/home/james/Documents/Project/UniQuant/src/uniquant/data/parsers/tdx_parser.py` (lines 172-265)

**Finding:**
1. **Record count is attacker-controlled:** The first 4 bytes of the file are unpacked as a uint32 count value (line 195). A malicious file could set this to `0xFFFFFFFF` (~4 billion), causing the `for` loop to iterate billions of times. However, the boundary check `if data_offset + 29 > len(file_content): break` on line 201 prevents actual buffer over-read -- the loop will simply break early when it runs out of data.

2. **TEA decryption reads from `bin_keys` using byte values as indices:** Lines 213-221 use `ebx_tmp` (derived from the ciphertext) as an index into `bin_keys`. The `bin_keys` buffer is approximately 4KB (from `hexdump_keys`), and `ebx_tmp` is derived from byte values (0-255), so `ebx_tmp * 4 + offset` could reach up to `255 * 4 + 0xC48 = 0x1044`. This must be within the `bin_keys` buffer size. Since `GbbqReader` provides the standard key table, this is safe for valid TDX files.

3. **Boundary check is correct:** The check `data_offset + 29 > len(file_content)` correctly prevents reading beyond the buffer. If the file is truncated mid-record, the parser exits cleanly.

**Risk:** Denial-of-service via crafted file with enormous count value (but breaks early). No memory corruption.

### 3.3 `parse_gbbq_file()` -- LOW (Delegated)

**File:** `/home/james/Documents/Project/UniQuant/src/uniquant/data/parsers/tdx_parser.py` (lines 100-169)

**Finding:** This method delegates to `pytdx.reader.GbbqReader.get_df()` which is a third-party library. The method properly handles `None` returns and empty DataFrames. The column regex `r'^\d{6}$'` (line 149) correctly validates stock codes as exactly 6 digits, preventing injection through malformed data.

---

## 4. Parquet Write Atomicity

### 4.1 `write_parquet()` -- MEDIUM (Not Atomic)

**File:** `/home/james/Documents/Project/UniQuant/src/uniquant/data/lake/storage_manager.py` (lines 64-89)

**Finding:** This method writes directly to the target file path with `df.to_parquet(file_path, compression="snappy")`. If the process crashes or power is lost during the write, the file may be left in a partially written (corrupted) state.

The `FileLock` mechanism (line 81) protects against concurrent writes from multiple processes, but does NOT provide atomicity against process failure during write.

**Risk:** Data corruption on crash/power loss during Parquet write.

### 4.2 `write_data()` -- GOOD (Atomic)

**File:** `/home/james/Documents/Project/UniQuant/src/uniquant/data/lake/storage_manager.py` (lines 523-545)

**Finding:** The `write_data()` method implements a proper write-to-temp-then-rename pattern:

```python
temp_path = file_path.with_suffix(".tmp")
if not self.write_parquet(str(temp_path), df, overwrite=True):
    ...
if file_path.exists():
    file_path.unlink()
temp_path.rename(file_path)
```

This provides atomic semantics: readers always see either the old file or the new file, never a partial write. The temp file is cleaned up on failure.

**Recommendation (MEDIUM):** `write_parquet()` itself should be made atomic (or at minimum documented as non-atomic), since it is a public API that other code may call directly. Consider adding an `atomic=True` parameter or making atomic behavior the default.

---

## 5. Arbitrary Code Execution Analysis

### 5.1 JS Engine (`JsExecutor`) -- MEDIUM

**File:** `/home/james/Documents/Project/UniQuant/src/uniquant/data/utils/js_executor.py` (lines 1-345)

**Finding:** The `JsExecutor` class uses `py_mini_racer` (a V8 JavaScript engine wrapper) to execute JavaScript code via `.eval()`. The executed JS content comes from:
1. A local file `ths.js` (line 32-34) -- read from disk
2. A hardcoded default JS snippet (line 51-58)
3. Browser environment mocks (line 70-231)

**Risk Assessment:**
- The JS content is **not user-controlled** -- it comes from local files and hardcoded strings.
- However, there is **no integrity verification** (no checksum, no signature) on the `ths.js` file. If an attacker can modify `ths.js` on disk, arbitrary JavaScript will execute within the Python process via V8.
- `py_mini_racer` provides some sandboxing (V8 isolate), but the JS engine has access to the same process memory space.
- The global singleton `js_executor = JsExecutor()` (line 325) means the engine persists for the process lifetime.

**Recommendation:**
- Add SHA-256 checksum verification for `ths.js` before loading.
- Consider pinning the expected hash in code and rejecting mismatched files.

### 5.2 `__import__` in Auto-Mined Factors -- LOW

**File:** `/home/james/Documents/Project/UniQuant/src/uniquant/brain/factors/auto_mined/round_*.py` (10 files)

**Finding:** All auto-mined factor files use:
```python
sys.path.insert(0, str(__import__('pathlib').Path(__file__).parents[5]))
```

This is a dynamic import used solely for path manipulation, not arbitrary code execution. The path is derived from `__file__` (the script's own location), not from user input.

**Risk:** Negligible -- `__import__` is equivalent to `import` here.

### 5.3 No `eval()`/`exec()` on User Input -- GOOD

**Finding:** No instances of `eval()` or `exec()` with user-controlled input were found anywhere in the `src/` tree. All `eval()` calls are on local file content or hardcoded strings.

---

## 6. Data Deserialization Safety

**Finding:** No use of `pickle`, `shelve`, `marshal`, or `yaml.unsafe_load` was found in the `src/uniquant/data/` directory. All YAML loading uses `yaml.safe_load()`. All structured data uses Parquet format (via Pandas), which is safe against deserialization attacks.

---

## 7. Summary of Recommendations

| # | Severity | Issue | Recommendation |
|---|----------|-------|----------------|
| 1 | HIGH | `write_parquet()` accepts arbitrary paths | Add path validation against `self.data_dir` |
| 2 | HIGH | `save_stock_gbbq_data()` unvalidated `code` in path | Regex-validate stock code to alphanumeric only |
| 3 | MEDIUM | `write_parquet()` not atomic | Add atomic write option or document limitation |
| 4 | MEDIUM | JS engine loads `ths.js` without integrity check | Add SHA-256 checksum verification |
| 5 | MEDIUM | GBBQ count DoS via crafted file | Cap max record count (e.g., 10 million) |
| 6 | MEDIUM | `error_handling.py` password/token filter incomplete | Extend filter to include `api_key`, `secret`, `credential` |
| 7 | LOW | `parse_day_file()` warning-only on non-aligned size | Consider rejecting files with `file_size % 32 != 0` |
| 8 | LOW | `_get_file_path()` path traversal via symbol | Add symbol sanitization (alphanumeric + dot only) |
| 9 | LOW | Hardcoded user path in `config.yaml` | Use environment variable or relative path |
| 10 | INFO | Config exposes local username path | Minor info leak, consider anonymizing |
| 11 | INFO | `data_type` fallthrough in `_get_file_path()` | Unrecognized types create arbitrary subdirectories |
| 12 | INFO | `FileLock` uses `.lock` suffix convention | Adequate for single-host; consider advisory locks for distributed |

---

## 8. Positive Findings

1. **No hardcoded secrets** in any configuration file or source code.
2. **LLM API keys** loaded exclusively from environment variables, not YAML.
3. **Error logging** redacts `password` and `token` from kwargs.
4. **Parquet write** in `write_data()` implements proper atomic write pattern.
5. **No pickle/shelve/marshal deserialization** in the data layer.
6. **TDX parser** has correct boundary checking for binary record parsing.
7. **.gitignore** properly excludes data directories and lock files.
8. **All YAML loading** uses `yaml.safe_load()`, preventing arbitrary object instantiation.

---

*Report generated: 2026-06-06 | Auditor: R6 Security & Data Integrity | Classification: Internal*
