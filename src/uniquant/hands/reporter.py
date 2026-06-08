import datetime
import pandas as pd
from pathlib import Path
from typing import Any, Dict, Optional

from uniquant.shared.constants import ResultsConstants
from uniquant.shared.logger_factory import get_logger

logger = get_logger("Reporter")


class Reporter:
    """
    Dedicated Reporter class to generate standardized Markdown research reports.
    Aligned with Alpha-Tactician V2.0.0 Brain Architecture (Regime -> LPPL -> NTF -> CZSC -> Alpha).
    """

    def __init__(self, output_dir: Optional[str] = None, use_date_folders: bool = True):
        if output_dir is None:
            from uniquant.shared.config_loader import get_config
            root_dir = get_config().ROOT_DIR
            output_dir = root_dir / ResultsConstants.HANDS_DIR_NAME / ResultsConstants.REPORTS_DIR_NAME
        self.output_root = Path(output_dir)
        self.use_date_folders = use_date_folders
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.stock_name_map = self._load_stock_names()

    def _get_output_dir(self, date_str: str | None = None) -> Path:
        """获取输出目录，支持按日期分类"""
        if self.use_date_folders:
            date_folder = date_str or datetime.datetime.now().strftime("%Y-%m-%d")
            output_dir = self.output_root / date_folder
            output_dir.mkdir(parents=True, exist_ok=True)
            return output_dir
        return self.output_root

    def _load_stock_names(self) -> Dict[str, str]:
        """
        从all_stock_codes.csv文件加载股票代码和名称的映射
        """
        stock_name_map = {}
        csv_path = Path("data") / "all_stock_codes.csv"

        try:
            if csv_path.exists():
                df = pd.read_csv(csv_path)
                name_col = "code_name" if "code_name" in df.columns else "name"
                for row in df.itertuples(index=False):
                    stock_name_map[str(row.code)] = getattr(row, name_col, "")
                logger.info(f"成功加载 {len(stock_name_map)} 个股票名称")
            else:
                logger.warning(f"股票代码文件不存在: {csv_path}")
        except Exception as e:
            logger.error(f"加载股票名称失败: {e}")

        return stock_name_map

    def generate(self, symbol: str, data: Dict[str, Any], date_str: str | None = None) -> Path:
        """
        Generate a research report for a given symbol.

        Args:
            symbol: Stock symbol
            data: Report data dictionary

        Returns:
            Path to generated report file
        """
        output_dir = self._get_output_dir(date_str)

        report_name = f"Report_{symbol}.md"
        report_path = output_dir / report_name

        content = self._build_report_content(symbol, data)

        with open(report_path, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info(f"生成报告: {report_path}")
        return report_path

    def generate_research_report(self, context: Dict[str, Any]) -> bool:
        """兼容历史调用入口，生成研究报告并返回是否成功。"""
        try:
            symbol = context.get("symbol")
            if not symbol:
                logger.error("生成研究报告失败: 缺少 symbol")
                return False

            decision_packet = context.get("decision_packet", {}) or {}
            signals = []
            for key in ["final_decision", "regime", "risk", "ntf_side", "ma_status"]:
                value = decision_packet.get(key)
                if value not in (None, ""):
                    signals.append(f"{key}: {value}")

            score = decision_packet.get("final_score")
            if score is not None:
                signals.append(f"final_score: {score}")

            report_data = {
                "price": context.get("current_price"),
                "indicators": context.get("indicators", {}),
                "signals": signals,
                "analysis": context.get("analysis")
                or f"综合决策: {decision_packet.get('final_decision', 'UNKNOWN')}",
            }

            report_date = context.get("report_date")
            self.generate(symbol, report_data, date_str=report_date)
            return True
        except Exception as e:
            logger.error(f"生成研究报告失败: {e}")
            return False

    def _build_report_content(self, symbol: str, data: Dict[str, Any]) -> str:
        """
        构建报告内容
        """
        lines = []

        name = self.stock_name_map.get(symbol, symbol)
        lines.append(f"# {name} ({symbol}) 个股分析报告\n")
        lines.append(f"**生成时间**: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        lines.append("---\n")

        if "price" in data:
            lines.append("## 价格信息\n")
            lines.append(f"- 当前价格: {data['price']}\n")
            if "change" in data:
                lines.append(f"- 涨跌幅: {data['change']}%\n")
            lines.append("")

        if "indicators" in data:
            lines.append("## 技术指标\n")
            for k, v in data["indicators"].items():
                lines.append(f"- {k}: {v}\n")
            lines.append("")

        if "signals" in data:
            lines.append("## 交易信号\n")
            for signal in data["signals"]:
                lines.append(f"- {signal}\n")
            lines.append("")

        if "analysis" in data:
            lines.append("## 分析结论\n")
            lines.append(f"{data['analysis']}\n")

        return "".join(lines)
