# -*- coding: utf-8 -*-
import logging
import multiprocessing
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeoutError
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from uniquant.shared.constants import ENABLE_JOBLIB_PARALLEL, OUTPUT_DIR, WINDOW_CONFIG
from uniquant.brain.lppl.core import (
    calculate_bottom_signal_strength,
    detect_negative_bubble,
    validate_input_data,
)
from uniquant.brain.lppl.engine import DEFAULT_CONFIG, LPPLConfig, calculate_risk_level, fit_single_window

logger = logging.getLogger(__name__)

JOBLIB_AVAILABLE = False
try:
    from joblib import Parallel, delayed

    JOBLIB_AVAILABLE = True
    logger.info("joblib parallel processing available")
except ImportError:
    JOBLIB_AVAILABLE = False
    logger.warning("joblib not available, using ProcessPoolExecutor")


def performance_monitor(func):
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        elapsed = end_time - start_time
        logger.info("%s executed in %.2f seconds", func.__name__, elapsed)
        return result

    return wrapper


def get_optimal_workers() -> int:
    cpu_count = multiprocessing.cpu_count()
    optimal_workers = max(1, min(4, cpu_count - 2))
    return optimal_workers


def fit_single_window_task(args: Tuple[int, pd.Series, np.ndarray]) -> Optional[Dict[str, Any]]:
    window_size, dates_series, prices_array = args
    try:
        result = fit_single_window(prices_array, window_size, DEFAULT_CONFIG)
        if result is None:
            return None
        last_date_raw = dates_series.iloc[-1] if hasattr(dates_series, "iloc") else dates_series[-1]
        if hasattr(last_date_raw, "to_pydatetime"):
            last_date = last_date_raw
        else:
            last_date = pd.Timestamp(last_date_raw)
        return {
            "window": window_size,
            "params": np.array(result["params"]),
            "rmse": result["rmse"],
            "r_squared": result["r_squared"],
            "last_date": last_date,
        }
    except Exception as e:
        logger.error("fit_single_window_task failed: %s", e)
        return None


def _fit_single_window_compat(task: tuple) -> Optional[Dict[str, Any]]:
    window_size, dates_series, prices_array = task
    res = fit_single_window(close_prices=prices_array, window_size=window_size)
    if res is None:
        return None
    return {
        "window": res["window_size"],
        "params": res["params"],
        "rmse": res["rmse"],
        "last_date": pd.Timestamp(dates_series.iloc[-1]),
    }


class LPPLComputation:
    def __init__(
        self,
        output_dir: str = None,
        max_workers: Optional[int] = None,
        lppl_config: Optional[LPPLConfig] = None,
    ):
        self.output_dir = output_dir or OUTPUT_DIR
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

        self.max_workers = max_workers if max_workers else get_optimal_workers()
        self.lppl_config = lppl_config if lppl_config is not None else DEFAULT_CONFIG
        logger.info("LPPLComputation initialized with max_workers=%s", self.max_workers)

    def _format_output(
        self, symbol: str, name: str, window: int, res: Dict[str, Any], time_span: str = ""
    ) -> List:
        try:
            tc, m, w, a, b, c, phi = res["params"]
            days_left = tc - window

            if days_left < 0:
                days_left = 0

            last_date = res["last_date"]
            if not hasattr(last_date, "strftime"):
                last_date = pd.Timestamp(last_date)

            crash_date = last_date + timedelta(days=int(days_left))

            risk_label, _, _ = calculate_risk_level(m, w, days_left, r2=res.get("r_squared", 0.0), lppl_config=self.lppl_config)

            is_negative, bottom_signal = detect_negative_bubble(m, w, b, days_left)
            bottom_strength = (
                calculate_bottom_signal_strength(m, w, b, res["rmse"]) if is_negative else 0.0
            )

            return [
                name,
                symbol,
                time_span,
                window,
                f"{res['rmse']:.5f}",
                f"{m:.3f}",
                f"{w:.3f}",
                f"{days_left:.1f} 天",
                crash_date.strftime("%Y-%m-%d"),
                risk_label,
                bottom_signal,
                f"{bottom_strength:.2f}",
            ]
        except (KeyError, ValueError, TypeError) as e:
            logger.error("Error formatting output: %s", e)
            return []

    def process_index_multiprocess(
        self, symbol: str, name: str, df: pd.DataFrame
    ) -> Tuple[List, List]:
        logger.info("  > Scanning %s (%s) with Batch Parallel Processing...", name, symbol)

        is_valid, msg = validate_input_data(df, symbol)
        if not is_valid:
            logger.error("Invalid input data for %s: %s", symbol, msg)
            return [], []

        tasks = []
        windows = WINDOW_CONFIG.all_windows

        dates_array = df["date"].values
        prices_array = df["close"].values

        for window in windows:
            if len(df) >= window:
                tasks.append((window, dates_array[-window:], prices_array[-window:]))

        if not tasks:
            logger.warning("  No valid windows for %s", symbol)
            return [], []

        results = {
            "short": {"rmse": float("inf"), "res": None},
            "medium": {"rmse": float("inf"), "res": None},
            "long": {"rmse": float("inf"), "res": None},
        }

        cnt_success = 0
        logger.info("  > Scanning %s (%s)...", name, symbol)
        start_time = time.time()

        if JOBLIB_AVAILABLE and ENABLE_JOBLIB_PARALLEL:
            parallel_results = Parallel(
                n_jobs=self.max_workers, backend="loky", timeout=300, verbose=0
            )(delayed(fit_single_window_task)(task) for task in tasks)

            for i, res in enumerate(parallel_results):
                window = tasks[i][0]
                if res is not None:
                    cnt_success += 1

                    category = WINDOW_CONFIG.get_category(window)
                    if res["rmse"] < results[category]["rmse"]:
                        results[category]["rmse"] = res["rmse"]
                        results[category]["res"] = res
                else:
                    pass
        else:
            batch_size = self.max_workers * 2

            with ProcessPoolExecutor(max_workers=self.max_workers) as executor:
                for i in range(0, len(tasks), batch_size):
                    batch = tasks[i : i + batch_size]

                    future_to_window = {
                        executor.submit(fit_single_window_task, task): task[0] for task in batch
                    }

                    for future in as_completed(future_to_window):
                        window = future_to_window[future]
                        try:
                            res = future.result(timeout=120)
                            if res:
                                cnt_success += 1

                                category = WINDOW_CONFIG.get_category(window)
                                if res["rmse"] < results[category]["rmse"]:
                                    results[category]["rmse"] = res["rmse"]
                                    results[category]["res"] = res
                            else:
                                pass
                        except FuturesTimeoutError:
                            logger.warning("Task timeout for window %s", window)
                        except Exception as e:
                            logger.warning("Error processing window %s: %s", window, e)

        elapsed_time = time.time() - start_time
        logger.info(
            "  Done scanning %s (%s) (Time: %.2fs, Success: %s/%s)", name, symbol, elapsed_time, cnt_success, len(tasks)
        )

        output_rows = []
        params_data = []

        span_map = {"short": "短期", "medium": "中期", "long": "长期"}

        for key, val in results.items():
            if val["res"]:
                res = val["res"]
                formatted = self._format_output(symbol, name, res["window"], res, span_map[key])
                if formatted:
                    output_rows.append(formatted)

                    params_data.append(
                        {
                            "symbol": symbol,
                            "name": name,
                            "time_span": span_map[key],
                            "window": res["window"],
                            "params": res["params"].tolist(),
                            "rmse": res["rmse"],
                            "last_date": res["last_date"].strftime("%Y-%m-%d"),
                        }
                    )

        return output_rows, params_data

    @performance_monitor
    def run_computation(
        self, data_dict: Dict[str, Dict[str, Any]], close_executor: bool = False
    ) -> List:
        if not data_dict:
            logger.warning("Empty data_dict provided")
            return []

        all_report_data = []
        all_params_data = []

        index_tasks = []
        for symbol, info in data_dict.items():
            name = info.get("name", symbol)
            df = info.get("data")

            is_valid, msg = validate_input_data(df, symbol)
            if is_valid:
                index_tasks.append((symbol, name, df))
            else:
                logger.warning("Skipping %s (%s): %s", name, symbol, msg)

        if not index_tasks:
            logger.warning("No valid indices to process")
            return []

        logger.info("Processing %s indices (parallel windows)...", len(index_tasks))

        for symbol, name, df in index_tasks:
            logger.info("Processing %s (%s)...", name, symbol)
            try:
                rows, params = self.process_index_multiprocess(symbol, name, df)
                if rows:
                    all_report_data.extend(rows)
                    all_params_data.extend(params)
                    logger.info("Completed processing %s (%s)", name, symbol)
            except Exception as e:
                logger.error("Error processing %s (%s): %s", name, symbol, e)

        if all_report_data:
            try:
                all_report_data.sort(key=lambda x: float(x[4]) if x[4] else float("inf"))
            except (ValueError, IndexError) as e:
                logger.warning("Error sorting results: %s", e)

        return all_report_data, all_params_data

    def generate_markdown(self, report_data: List, data_date: str = None) -> Optional[str]:
        if not report_data:
            logger.warning("No report data provided")
            return None

        if data_date is None:
            data_date = datetime.now().strftime("%Y%m%d")

        filename = f"lppl_report_{data_date}.md"
        file_path = os.path.join(self.output_dir, filename)

        markdown_content = (
            f"# LPPL模型扫描报告\n\n**生成时间**: {datetime.now()}\n\n**数据日期**: {data_date}\n\n"
        )
        markdown_content += "| 指数名称 | 指数代码 | 时间跨度 | 窗口(天) | RMSE | m | w | 距离崩盘 | 崩盘日期 | 风险等级 | 抄底信号 | 信号强度 |\n"
        markdown_content += "|---|---|---|---|---|---|---|---|---|---|---|---|\n"

        for row in report_data:
            if row:
                line = "|" + "|".join(str(x) for x in row) + "|\n"
                markdown_content += line

        markdown_content += "\n\n---\n\n### AI Agent Context Block\n\n"
        markdown_content += "```markdown\n"
        markdown_content += f"# LPPL Scan Data - {data_date}\n"
        markdown_content += (
            "| Index | Code | Window | Crash_Date | Days_Left | Risk | m | RMSE | Bottom_Signal |\n"
        )
        markdown_content += "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n"

        for row in report_data:
            if row and len(row) >= 12:
                risk_level = row[9]
                bottom_signal = row[10] if len(row) > 10 else "无"
                if (
                    "极高" in risk_level
                    or "高" in risk_level
                    or "抄底" in bottom_signal
                    or "上证" in row[0]
                    or "创业" in row[0]
                ):
                    days = str(row[7]).replace(" 天", "")
                    m_val = row[5]
                    rmse_val = row[4]
                    markdown_content += f"| {row[0]} | {row[1]} | {row[3]} ({row[2]}) | {row[8]} | {days} | {risk_level} | {m_val} | {rmse_val} | {bottom_signal} |\n"

        markdown_content += "```\n"

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(markdown_content)
            logger.info("Markdown report saved to: %s", file_path)
            return file_path
        except PermissionError as e:
            logger.error("Permission denied saving MD: %s", e)
            return None
        except OSError as e:
            logger.error("OS error saving MD: %s", e)
            return None

    def save_params_to_json(self, params_data: List, data_date: str = None) -> Optional[str]:
        if not params_data:
            logger.warning("No parameters to save")
            return None

        import json

        if data_date is None:
            data_date = datetime.now().strftime("%Y%m%d")

        filename = f"lppl_params_{data_date}.json"
        file_path = os.path.join(self.output_dir, filename)

        json_data = {
            "data_date": data_date,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "parameters": params_data,
        }

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(json_data, f, ensure_ascii=False, indent=2)
            logger.info("Full LPPL parameters saved to: %s", file_path)
            return file_path
        except PermissionError as e:
            logger.error("Permission denied saving parameters: %s", e)
            return None
        except OSError as e:
            logger.error("OS error saving parameters: %s", e)
            return None
