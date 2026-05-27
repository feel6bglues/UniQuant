import numpy as np
import pandas as pd


def mad_winsorize(series: pd.Series, n: float = 5) -> pd.Series:
    median = series.median()
    mad = (series - median).abs().median()
    if mad == 0:
        return series
    mad_scaled = mad * 1.4826
    upper = median + n * mad_scaled
    lower = median - n * mad_scaled
    return series.clip(lower, upper)


class FactorNeutralizer:
    def neutralize(
        self,
        factor: pd.Series,
        industry_dummies: pd.DataFrame,
        log_market_cap: pd.Series,
        winsorize_n: float = 5,
    ) -> pd.Series:
        if len(factor) < 10:
            return factor
        cleaned = mad_winsorize(factor, n=winsorize_n)
        X = np.column_stack([
            np.ones(len(cleaned)),
            log_market_cap.values,
            industry_dummies.values,
        ])
        valid = ~np.isnan(cleaned.values) & ~np.isnan(X).any(axis=1)
        if valid.sum() < 10:
            return factor
        y = cleaned.values[valid]
        X_valid = X[valid]
        coef, _, _, _ = np.linalg.lstsq(X_valid, y, rcond=None)
        residual = np.full(len(factor), np.nan)
        residual[valid] = y - X_valid @ coef
        return pd.Series(residual, index=factor.index, name=factor.name)
