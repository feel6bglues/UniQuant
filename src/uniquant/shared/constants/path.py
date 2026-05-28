"""路径相关常量"""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent

OUTPUT_DIR = "hands/reports"


class PathConstants:
    """路径相关常量"""

    DATA_DIR = PROJECT_ROOT / "data"
    RAW_DIR = PROJECT_ROOT / "data" / "raw"
    CLEAN_DIR = PROJECT_ROOT / "data" / "clean"
    LAKE_DIR = PROJECT_ROOT / "data" / "lake"
    REPORT_DIR = PROJECT_ROOT / "data" / "reports"
    LOG_DIR = PROJECT_ROOT / "logs"

    FILE_SUFFIX_CSV = ".csv"
    FILE_SUFFIX_PARQUET = ".parquet"
    FILE_SUFFIX_JSON = ".json"
    FILE_SUFFIX_LOG = ".log"

    CONFIG_FILE = "config.yaml"
    STOCK_LIST_FILE = PROJECT_ROOT / "data" / "stock_list.json"

    CSV_SUFFIX = ".csv"
    PARQUET_SUFFIX = ".parquet"
    JSON_SUFFIX = ".json"
    LOG_SUFFIX = ".log"


TDX_DIR = PROJECT_ROOT / "tdx"
DATA_DIR = PROJECT_ROOT / "data"
LAKE_QUOTES_DIR = PROJECT_ROOT / "data" / "lake" / "quotes"
LAKE_FINANCIAL_DIR = PROJECT_ROOT / "data" / "lake" / "financial"
LAKE_INDEX_DIR = PROJECT_ROOT / "data" / "lake" / "index"
STOCK_LIST_FILE = PROJECT_ROOT / "data" / "all_stock_codes.csv"
