"""
计算结果管理器
负责管理分析计算结果的存储、读取和报告生成
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional


from uniquant.shared.constants import ResultsConstants
from uniquant.shared.logger_factory import get_logger

logger = get_logger("ResultsManager")


class ResultsManager:
    """
    计算结果管理器
    
    职责:
    - 管理计算结果文件的存储和读取
    - 从结果文件批量生成报告
    - 清理过期结果文件
    """
    
    def __init__(self, root_dir: Optional[Path] = None, use_date_folders: bool = True):
        """
        初始化结果管理器
        
        Args:
            root_dir: 项目根目录，默认从配置获取
            use_date_folders: 是否使用日期子目录存储
        """
        if root_dir is None:
            from uniquant.shared.config_loader import get_config
            root_dir = get_config().ROOT_DIR
        
        self.root_dir = Path(root_dir)
        self.use_date_folders = use_date_folders
        self.results_dir = self.root_dir / ResultsConstants.HANDS_DIR_NAME / ResultsConstants.RESULTS_DIR_NAME
        self.reports_dir = self.root_dir / ResultsConstants.HANDS_DIR_NAME / ResultsConstants.REPORTS_DIR_NAME
        self.review_dir = self.root_dir / ResultsConstants.HANDS_DIR_NAME / ResultsConstants.REVIEW_DIR_NAME
        
        self._ensure_directories()
    
    def _ensure_directories(self) -> None:
        """确保目录存在"""
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.review_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_results_dir_for_date(self, date_str: Optional[str] = None) -> Path:
        """
        获取指定日期的结果目录
        
        Args:
            date_str: 日期字符串，格式 YYYY-MM-DD，默认为当天
            
        Returns:
            结果目录路径
        """
        if not self.use_date_folders:
            return self.results_dir
        
        folder_date = date_str or datetime.now().strftime(ResultsConstants.DATE_FOLDER_FORMAT)
        target_dir = self.results_dir / folder_date
        target_dir.mkdir(parents=True, exist_ok=True)
        return target_dir

    def _normalize_result_date(self, value: Optional[str]) -> Optional[str]:
        """将日期标准化为 YYYY-MM-DD，无法识别时返回原值。"""
        if not value:
            return value

        if len(value) == 8 and value.isdigit():
            return f"{value[:4]}-{value[4:6]}-{value[6:8]}"

        return value

    def _sortable_result_date(self, value: Optional[str]) -> str:
        """返回适合排序的标准化日期字符串，无法解析时返回空串。"""
        normalized = self._normalize_result_date(value)
        if not normalized:
            return ""

        try:
            return datetime.strptime(normalized, "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError:
            return ""

    def _extract_symbol_and_date(self, filepath: Path) -> Optional[Dict[str, str]]:
        """兼容新旧结果目录与文件名协议。"""
        relative_parts = filepath.relative_to(self.results_dir).parts
        filename = filepath.stem

        if len(relative_parts) >= 2:
            raw_date = relative_parts[0]
            normalized_date = self._normalize_result_date(raw_date) or raw_date
            file_symbol = filename.rsplit("_", 1)[0] if "_" in filename else filename
            return {"symbol": file_symbol, "date": normalized_date}

        parts = filename.rsplit("_", 1)
        if len(parts) == 2:
            return {
                "symbol": parts[0],
                "date": self._normalize_result_date(parts[1]) or parts[1],
            }

        return {"symbol": filename, "date": ""}

    def _report_exists(self, symbol: str, date_str: Optional[str]) -> bool:
        """兼容新旧报告目录与命名协议。"""
        normalized_date = self._normalize_result_date(date_str) or datetime.now().strftime("%Y-%m-%d")
        date_folder_report = (
            self.reports_dir
            / normalized_date
            / f"{ResultsConstants.REPORT_FILE_PREFIX}{symbol}{ResultsConstants.REPORT_FILE_SUFFIX}"
        )
        legacy_report = (
            self.reports_dir
            / f"{ResultsConstants.REPORT_FILE_PREFIX}{symbol}_{normalized_date}{ResultsConstants.REPORT_FILE_SUFFIX}"
        )
        return date_folder_report.exists() or legacy_report.exists()
    
    def list_results(self, symbol: Optional[str] = None, date: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        列出计算结果文件
        
        Args:
            symbol: 股票代码过滤，如 '000001.SZ'
            date: 日期过滤，格式 'YYYY-MM-DD' 或 'YYYYMMDD'
            
        Returns:
            结果文件信息列表
        """
        results: List[Dict[str, Any]] = []
        
        if not self.results_dir.exists():
            return results
        
        if self.use_date_folders:
            glob_pattern = f"**/*{ResultsConstants.RESULTS_FILE_SUFFIX}"
        else:
            glob_pattern = f"*{ResultsConstants.RESULTS_FILE_SUFFIX}"
        
        for filepath in self.results_dir.glob(glob_pattern):
            try:
                parsed = self._extract_symbol_and_date(filepath)
                if parsed is None:
                    continue

                file_symbol = parsed["symbol"]
                folder_date = parsed["date"]

                if date:
                    normalized_date = (self._normalize_result_date(date) or date).replace("-", "")
                    normalized_folder = folder_date.replace("-", "")
                    if normalized_folder != normalized_date:
                        continue
                
                if symbol and file_symbol != symbol:
                    continue
                
                stat = filepath.stat()
                results.append({
                    "symbol": file_symbol,
                    "date": folder_date,
                    "filepath": str(filepath),
                    "size_kb": round(stat.st_size / 1024, 2),
                    "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                })
            except Exception as e:
                logger.warning(f"解析结果文件失败 {filepath}: {e}")
                continue
        
        return sorted(
            results,
            key=lambda x: (
                self._sortable_result_date(x.get("date")),
                x["modified"],
                x["filepath"],
            ),
            reverse=True,
        )
    
    def read_result(self, filepath: str) -> Optional[Dict[str, Any]]:
        """
        读取计算结果文件
        
        Args:
            filepath: 结果文件路径
            
        Returns:
            结果数据字典，失败返回 None
        """
        try:
            path = Path(filepath)
            if not path.exists():
                logger.error(f"结果文件不存在: {filepath}")
                return None
            
            with open(path, "r", encoding=ResultsConstants.ENCODING) as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败 {filepath}: {e}")
            return None
        except (IOError, OSError) as e:
            logger.error(f"读取文件失败 {filepath}: {e}")
            return None
    
    def get_latest_result(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        获取指定股票的最新计算结果
        
        Args:
            symbol: 股票代码
            
        Returns:
            最新结果数据，不存在返回 None
        """
        results = self.list_results(symbol=symbol)
        if not results:
            return None
        
        latest_path = results[0]["filepath"]
        return self.read_result(latest_path)
    
    def generate_report_from_result(self, result_filepath: str) -> bool:
        """
        从计算结果文件生成报告
        
        Args:
            result_filepath: 结果文件路径
            
        Returns:
            是否成功
        """
        try:
            result_data = self.read_result(result_filepath)
            if result_data is None:
                return False
            
            symbol = result_data.get("symbol", "UNKNOWN")
            decision_result = result_data.get("decision_result", {})
            data_pack = result_data.get("data_pack", {})

            indicators = result_data.get("indicators") or data_pack.get("indicators", {})
            
            from .reporter import Reporter
            reporter = Reporter(output_dir=str(self.reports_dir))
            
            context = {
                "symbol": symbol,
                "decision_packet": decision_result,
                "result_file": result_filepath,
                "indicators": indicators,
                "report_date": str(result_data.get("date", "")).split(" ")[0] or None,
            }
            
            success = reporter.generate_research_report(context)
            
            if success:
                logger.info(f"报告生成成功: {symbol}")
            else:
                logger.warning(f"报告生成失败: {symbol}")
            
            return success
        except Exception as e:
            logger.error(f"从结果生成报告失败 {result_filepath}: {e}")
            return False
    
    def generate_reports_from_results(
        self, 
        symbols: Optional[List[str]] = None,
        date: Optional[str] = None,
        force: bool = False
    ) -> Dict[str, bool]:
        """
        批量从计算结果生成报告
        
        Args:
            symbols: 股票代码列表，None 表示全部
            date: 日期过滤
            force: 是否强制重新生成（即使报告已存在）
            
        Returns:
            股票代码 -> 是否成功的映射
        """
        results = {}
        result_files = self.list_results(date=date)
        
        for result_info in result_files:
            symbol = result_info["symbol"]
            
            if symbols and symbol not in symbols:
                continue
            
            if not force and self._report_exists(symbol, result_info["date"]):
                logger.info(f"报告已存在，跳过: {symbol}")
                results[symbol] = True
                continue
            
            success = self.generate_report_from_result(result_info["filepath"])
            results[symbol] = success
        
        return results
    
    def cleanup_old_results(self, days: Optional[int] = None) -> int:
        """
        清理过期的计算结果文件
        
        Args:
            days: 保留天数，默认使用常量配置
            
        Returns:
            删除的文件数量
        """
        if days is None:
            days = ResultsConstants.CLEANUP_THRESHOLD_DAYS
        
        threshold = datetime.now() - timedelta(days=days)
        deleted_count = 0
        
        if not self.results_dir.exists():
            return deleted_count
        
        for filepath in self.results_dir.glob(f"*{ResultsConstants.RESULTS_FILE_SUFFIX}"):
            try:
                stat = filepath.stat()
                modified = datetime.fromtimestamp(stat.st_mtime)
                
                if modified < threshold:
                    filepath.unlink()
                    deleted_count += 1
                    logger.info(f"删除过期结果文件: {filepath}")
            except Exception as e:
                logger.warning(f"清理文件失败 {filepath}: {e}")
        
        return deleted_count
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        获取结果统计信息
        
        Returns:
            统计信息字典
        """
        results = self.list_results()
        
        symbols = set(r["symbol"] for r in results)
        total_size = sum(r["size_kb"] for r in results)
        
        return {
            "total_results": len(results),
            "unique_symbols": len(symbols),
            "total_size_mb": round(total_size / 1024, 2),
            "results_dir": str(self.results_dir),
            "reports_dir": str(self.reports_dir),
        }
