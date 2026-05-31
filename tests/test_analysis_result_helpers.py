from uniquant.shared.analysis_result import (
    AnalysisResult,
    AnalysisResultBuilder,
    AnalysisStatus,
)


class TestAnalysisResult:
    def test_ok_to_dict_and_helpers(self):
        result = AnalysisResult.ok(
            data={"symbol": "000001.SZ", "score": 88},
            metadata={"source": "unit"},
            processing_time_ms=12.5,
        )

        result.add_warning("delayed").add_metadata("batch", "A")

        payload = result.to_dict()

        assert payload["status"] == "success"
        assert payload["success"] is True
        assert payload["data"]["symbol"] == "000001.SZ"
        assert payload["metadata"]["source"] == "unit"
        assert payload["metadata"]["batch"] == "A"
        assert payload["warnings"] == ["delayed"]
        assert payload["processing_time_ms"] == 12.5
        assert "timestamp" in payload
        assert result.get_data_field("score") == 88
        assert result.get_data_field("missing", "fallback") == "fallback"
        assert result.is_valid() is True

    def test_partial_failed_and_error_states(self):
        partial = AnalysisResult.partial(
            data={"symbol": "000001.SZ"},
            warnings=["partial data"],
        )
        failed = AnalysisResult.failed(
            error="calculation failed",
            warnings=["stale cache"],
            metadata={"phase": "close"},
        )
        error = AnalysisResult.create_error("unexpected")

        assert partial.status is AnalysisStatus.PARTIAL
        assert partial.success is True
        assert partial.is_valid() is True

        assert failed.status is AnalysisStatus.FAILED
        assert failed.success is False
        assert failed.warnings == ["stale cache"]
        assert failed.metadata["phase"] == "close"
        assert failed.is_valid() is False

        assert error.status is AnalysisStatus.ERROR
        assert error.success is False
        assert error.error == "unexpected"
        assert error.is_valid() is False


class TestAnalysisResultBuilder:
    def test_builder_builds_partial_result_from_warning(self):
        result = (
            AnalysisResultBuilder()
            .with_data("symbol", "000001.SZ")
            .with_metadata("source", "builder")
            .with_warning("partial input")
            .build()
        )

        assert result.status is AnalysisStatus.PARTIAL
        assert result.success is True
        assert result.data == {"symbol": "000001.SZ"}
        assert result.metadata == {"source": "builder"}
        assert result.warnings == ["partial input"]

    def test_builder_error_and_failed_paths(self):
        error_result = (
            AnalysisResultBuilder()
            .with_data("symbol", "000001.SZ")
            .with_error("network down")
            .build()
        )
        failed_result = AnalysisResultBuilder().mark_failed().build()

        assert error_result.status is AnalysisStatus.ERROR
        assert error_result.success is False
        assert error_result.error == "network down"

        assert failed_result.status is AnalysisStatus.FAILED
        assert failed_result.success is False
