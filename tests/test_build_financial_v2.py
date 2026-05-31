import pytest

try:
    from scripts.build_financial_v2 import build_financial_v2, convert_file, list_input_files
except ImportError:
    pytest.skip("scripts/build_financial_v2.py not found", allow_module_level=True)

from pathlib import Path

import pandas as pd


def test_convert_file_normalizes_code_and_report_date(tmp_path: Path) -> None:
    input_path = tmp_path / "002270.SZ.parquet"
    output_path = tmp_path / "out" / "002270.SZ.parquet"
    pd.DataFrame(
        {
            "code": [2270, 2270],
            "report_date": [
                pd.Timestamp("2025-12-31").to_datetime64().astype("datetime64[us]"),
                pd.Timestamp("2025-09-30").to_datetime64().astype("datetime64[us]"),
            ],
            "基本每股收益": [1.5, 1.2],
        }
    ).to_parquet(input_path, index=False)

    result = convert_file(input_path, output_path)
    converted = pd.read_parquet(output_path)

    assert result["original_code_dtype"] == "int64"
    assert result["converted_code_dtype"] == "object"
    assert result["converted_report_date_dtype"] == "datetime64[ns]"
    assert converted["code"].tolist() == ["002270.SZ", "002270.SZ"]
    assert converted["report_date"].dtype == "datetime64[ns]"
    assert converted["report_date"].tolist() == [
        pd.Timestamp("2025-09-30"),
        pd.Timestamp("2025-12-31"),
    ]


def test_build_financial_v2_applies_offset_and_limit(tmp_path: Path) -> None:
    input_dir = tmp_path / "financial"
    input_dir.mkdir(parents=True, exist_ok=True)
    for code in ["000001.SZ", "000002.SZ", "000004.SZ"]:
        pd.DataFrame(
            {
                "code": [int(code[:6])],
                "report_date": [pd.Timestamp("2025-09-30")],
                "基本每股收益": [1.0],
            }
        ).to_parquet(input_dir / f"{code}.parquet", index=False)

    selected = list_input_files(input_dir, offset=1, limit=1)
    assert [path.name for path in selected] == ["000002.SZ.parquet"]

    output_root = tmp_path / "v2"
    summary = build_financial_v2(
        input_dir=input_dir,
        output_root=output_root,
        offset=1,
        limit=1,
        batch_size=1,
    )

    assert summary["selected_files"] == 1
    assert summary["converted_files"] == 1
    assert summary["failed_files"] == 0
    assert summary["code_dtypes"] == ["object"]
    assert summary["report_date_dtypes"] == ["datetime64[ns]"]
    assert sorted((output_root / "financial_v2").glob("*.parquet"))[0].name == "000002.SZ.parquet"
