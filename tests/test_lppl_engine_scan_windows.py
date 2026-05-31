import pandas as pd

from uniquant.brain.lppl.engine import LPPLEngine


def test_scan_all_windows_selects_best_result_per_bucket(monkeypatch):
    monkeypatch.setenv("LPPL_DISABLE_PARALLEL", "1")
    monkeypatch.setattr(
        "uniquant.brain.lppl.engine.LPPLConstants.WINDOWS_ALL",
        [120, 250, 350, 700],
    )
    monkeypatch.setattr(
        "uniquant.brain.lppl.engine.LPPLConstants.RMSE_REJECT_THRESHOLD",
        1.0,
    )

    rmse_by_window = {
        120: 0.20,
        250: 0.10,
        350: 0.30,
        700: 0.40,
    }

    def fake_fit_single_window(self, subset):
        window = len(subset)
        return {
            "params": [window, 0.5, 8.0, 1.0, -1.0, 0.2, 0.0],
            "rmse": rmse_by_window[window],
        }

    monkeypatch.setattr(
        "uniquant.brain.lppl.calculator.LPPLCalculator.fit_single_window",
        fake_fit_single_window,
    )

    df = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=800, freq="D"),
            "close": [100 + i * 0.1 for i in range(800)],
        }
    )

    results = LPPLEngine().scan_all_windows(df)

    assert len(results) == 3
    assert results[0]["span"] == "Short (100-300d)"
    assert results[0]["window"] == 250
    assert results[0]["rmse"] == 0.10
    assert results[1]["span"] == "Medium (300-600d)"
    assert results[1]["window"] == 350
    assert results[2]["span"] == "Long (>600d)"
    assert results[2]["window"] == 700
