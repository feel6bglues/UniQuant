import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from ..shared.logger_factory import get_logger

logger = get_logger(__name__)


class ManagerReportService:
    """Report preview/export/compare helpers for AssetManager."""

    _PREVIEW_STYLE = """
            <style>
                .report-preview {
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    line-height: 1.6;
                    color: #333;
                    max-width: 900px;
                    margin: 0 auto;
                    padding: 20px;
                }
                .report-preview h1 {
                    color: #1a1a1a;
                    border-bottom: 2px solid #4CAF50;
                    padding-bottom: 10px;
                }
                .report-preview h2 {
                    color: #2c3e50;
                    margin-top: 30px;
                }
                .report-preview table {
                    border-collapse: collapse;
                    width: 100%;
                    margin: 15px 0;
                }
                .report-preview th, .report-preview td {
                    border: 1px solid #ddd;
                    padding: 8px 12px;
                    text-align: left;
                }
                .report-preview th {
                    background-color: #4CAF50;
                    color: white;
                }
                .report-preview tr:nth-child(even) {
                    background-color: #f2f2f2;
                }
                .report-preview code {
                    background-color: #f4f4f4;
                    padding: 2px 6px;
                    border-radius: 3px;
                    font-family: 'Courier New', monospace;
                }
                .report-preview blockquote {
                    border-left: 4px solid #4CAF50;
                    margin: 0;
                    padding-left: 16px;
                    color: #666;
                }
            </style>
    """

    def __init__(self, *, read_report: Callable[[str], str]):
        self._read_report = read_report

    def get_report_html_preview(self, file_path: str) -> str:
        try:
            import markdown

            content = self._read_report(file_path)
            if content.startswith("Error") or content == "Report not found.":
                return f"<p>无法读取报告: {content}</p>"

            html_content = markdown.markdown(
                content, extensions=["tables", "fenced_code", "toc"]
            )
            return (
                f"{self._PREVIEW_STYLE}\n"
                f'            <div class="report-preview">\n                {html_content}\n            </div>\n            '
            )
        except ImportError:
            logger.error("markdown模块未安装")
            return "<p>HTML预览需要安装markdown模块: pip install markdown</p>"
        except Exception as exc:
            logger.error("生成HTML预览失败: %s", exc)
            return f"<p>生成预览失败: {exc}</p>"

    def export_report_to_pdf(
        self, file_path: str, output_path: Optional[str] = None
    ) -> str:
        try:
            try:
                from weasyprint import HTML
            except ImportError:
                logger.warning("weasyprint未安装，PDF导出功能受限")
                return ""

            html_content = self.get_report_html_preview(file_path)
            if output_path is None:
                output_path = str(Path(file_path).with_suffix(".pdf"))

            HTML(string=html_content).write_pdf(output_path)
            logger.info("PDF导出成功: %s", output_path)
            return output_path
        except Exception as exc:
            logger.error("PDF导出失败: %s", exc)
            return ""

    def compare_reports(self, file_path1: str, file_path2: str) -> Dict[str, Any]:
        try:
            import difflib

            content1 = self._read_report(file_path1)
            content2 = self._read_report(file_path2)

            if content1.startswith("Error") or content2.startswith("Error"):
                return {"error": "无法读取报告内容"}

            diff = list(
                difflib.unified_diff(
                    content1.splitlines(),
                    content2.splitlines(),
                    fromfile=file_path1,
                    tofile=file_path2,
                    lineterm="",
                )
            )
            added = sum(
                1 for line in diff if line.startswith("+") and not line.startswith("+++")
            )
            removed = sum(
                1 for line in diff if line.startswith("-") and not line.startswith("---")
            )

            return {
                "status": "success",
                "file1": file_path1,
                "file2": file_path2,
                "diff": "\n".join(diff),
                "added_lines": added,
                "removed_lines": removed,
                "total_changes": added + removed,
            }
        except Exception as exc:
            logger.error("报告对比失败: %s", exc)
            return {"error": str(exc)}

    def get_report_metadata(self, file_path: str) -> Dict[str, Any]:
        try:
            import re

            path = Path(file_path)
            if not path.exists():
                return {"error": "文件不存在"}

            stat = path.stat()
            content = self._read_report(file_path)

            title_match = re.search(r"^# (.+)$", content, re.MULTILINE)
            ticker_match = re.search(r"代码[:：]?\s*(\d{6}\.[A-Z]{2})", content)
            date_match = re.search(r"(\d{4}-\d{2}-\d{2})", content)

            return {
                "status": "success",
                "filename": path.name,
                "title": title_match.group(1) if title_match else path.stem,
                "ticker": ticker_match.group(1) if ticker_match else "Unknown",
                "report_date": date_match.group(1) if date_match else "",
                "file_size_kb": round(stat.st_size / 1024, 2),
                "created": datetime.datetime.fromtimestamp(stat.st_mtime).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "line_count": len(content.splitlines()),
                "word_count": len(content.split()),
            }
        except Exception as exc:
            logger.error("获取报告元数据失败: %s", exc)
            return {"error": str(exc)}
