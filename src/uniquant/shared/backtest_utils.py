import pandas as pd


def filter_suspended(df: pd.DataFrame, threshold: int = 5) -> pd.DataFrame:
    if "volume" not in df.columns or "close" not in df.columns:
        return df
    suspended = (df["volume"] == 0) & (df["close"] == df["close"].shift(1))
    bad_streak = suspended.rolling(window=threshold).sum()
    return df[bad_streak < threshold].reset_index(drop=True)
