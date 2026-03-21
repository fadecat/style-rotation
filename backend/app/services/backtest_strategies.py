"""Factor-based signal computation for backtest strategies.

Each compute_* function takes a ratio Series and returns a signal Series.
Positive signal -> hold left, negative -> hold right.

Ensemble strategies compute multiple signals and use majority vote.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Individual factor functions
# ---------------------------------------------------------------------------

def compute_ratio_ma(ratio: pd.Series, *, n: int = 20) -> pd.Series:
    """Ratio / MA(n) - 1."""
    return ratio / ratio.rolling(n).mean() - 1


def compute_ratio_mom(ratio: pd.Series, *, n: int = 20) -> pd.Series:
    """Ratio momentum (pct_change)."""
    return ratio.pct_change(n)


def compute_ratio_rsi(ratio: pd.Series, *, n: int = 14) -> pd.Series:
    """RSI of ratio, centered at 0 (range -0.5 to +0.5)."""
    delta = ratio.diff()
    gain = delta.clip(lower=0).rolling(n).mean()
    loss = (-delta.clip(upper=0)).rolling(n).mean()
    rs = gain / loss.replace(0, np.nan)
    return rs / (1 + rs) - 0.5


def compute_ratio_bb(ratio: pd.Series, *, n: int = 20) -> pd.Series:
    """Bollinger band z-score of ratio."""
    ma = ratio.rolling(n).mean()
    std = ratio.rolling(n).std()
    return (ratio - ma) / std.replace(0, np.nan)


def compute_ratio_channel(ratio: pd.Series, *, n: int = 20) -> pd.Series:
    """Channel position of ratio, centered at 0 (range -0.5 to +0.5)."""
    rng = ratio.rolling(n).max() - ratio.rolling(n).min()
    return (ratio - ratio.rolling(n).min()) / rng.replace(0, np.nan) - 0.5


def compute_ratio_macd(
    ratio: pd.Series, *, fast: int = 5, slow: int = 20, sig: int = 9
) -> pd.Series:
    """MACD histogram of ratio."""
    ema_f = ratio.ewm(span=fast).mean()
    ema_s = ratio.ewm(span=slow).mean()
    macd = ema_f - ema_s
    signal = macd.ewm(span=sig).mean()
    return macd - signal


def compute_ratio_sharpe(ratio: pd.Series, *, n: int = 20) -> pd.Series:
    """Volatility-adjusted momentum (Sharpe-style)."""
    mom = ratio.pct_change(n)
    vol = ratio.pct_change().rolling(n).std()
    return mom / vol.replace(0, np.nan)


# ---------------------------------------------------------------------------
# Ensemble: majority vote across multiple signals
# ---------------------------------------------------------------------------

def compute_ensemble(ratio: pd.Series, *, members: list[str]) -> pd.Series:
    """Majority vote across member strategies. Returns +1/-1/0."""
    sigs = pd.DataFrame({m: compute_signal(m, ratio) for m in members})
    votes_left = (sigs > 0).sum(axis=1)
    votes_right = (sigs < 0).sum(axis=1)
    result = pd.Series(0.0, index=ratio.index)
    result[votes_left > votes_right] = 1.0
    result[votes_right > votes_left] = -1.0
    # NaN where all members are NaN
    all_nan = sigs.isna().all(axis=1)
    result[all_nan] = np.nan
    return result


# ---------------------------------------------------------------------------
# Strategy registry
# ---------------------------------------------------------------------------

STRATEGY_REGISTRY: dict[str, dict] = {
    # --- 推荐策略 (t+1验证, 建议配合 weekly 使用) ---
    "ratio_mom20": {"fn": compute_ratio_mom, "args": {"n": 20}, "label": "★ 动量(20) — 双标的最强"},
    "ratio_channel20": {"fn": compute_ratio_channel, "args": {"n": 20}, "label": "★ 通道(20) — 样本外第一"},
    "ratio_macd_12_26": {"fn": compute_ratio_macd, "args": {"fast": 12, "slow": 26, "sig": 9}, "label": "★ MACD(12,26) — 抗手续费"},
    "ratio_ma20": {"fn": compute_ratio_ma, "args": {"n": 20}, "label": "★ MA(20) — 经典稳健"},
    "ensemble_tech5": {
        "fn": compute_ensemble,
        "args": {"members": ["ratio_ma20", "ratio_rsi14", "ratio_bb20", "ratio_macd_5_20", "ratio_channel20"]},
        "label": "★ 技术投票(5) — 单标的最高",
    },
    "ensemble_mixed5": {
        "fn": compute_ensemble,
        "args": {"members": ["ratio_ma5", "ratio_ma10", "ratio_ma20", "ratio_mom10", "ratio_rsi14"]},
        "label": "★ 混合投票(5) — 7/8年盈利",
    },
    # --- MA 趋势 ---
    "ratio_ma5":  {"fn": compute_ratio_ma, "args": {"n": 5},  "label": "MA(5)"},
    "ratio_ma10": {"fn": compute_ratio_ma, "args": {"n": 10}, "label": "MA(10)"},
    "ratio_ma15": {"fn": compute_ratio_ma, "args": {"n": 15}, "label": "MA(15)"},
    "ratio_ma30": {"fn": compute_ratio_ma, "args": {"n": 30}, "label": "MA(30)"},
    "ratio_ma40": {"fn": compute_ratio_ma, "args": {"n": 40}, "label": "MA(40)"},
    "ratio_ma60": {"fn": compute_ratio_ma, "args": {"n": 60}, "label": "MA(60)"},
    # --- 动量 ---
    "ratio_mom5":  {"fn": compute_ratio_mom, "args": {"n": 5},  "label": "动量(5)"},
    "ratio_mom10": {"fn": compute_ratio_mom, "args": {"n": 10}, "label": "动量(10)"},
    "ratio_mom30": {"fn": compute_ratio_mom, "args": {"n": 30}, "label": "动量(30)"},
    "ratio_mom60": {"fn": compute_ratio_mom, "args": {"n": 60}, "label": "动量(60)"},
    # --- RSI ---
    "ratio_rsi10": {"fn": compute_ratio_rsi, "args": {"n": 10}, "label": "RSI(10)"},
    "ratio_rsi14": {"fn": compute_ratio_rsi, "args": {"n": 14}, "label": "RSI(14)"},
    "ratio_rsi20": {"fn": compute_ratio_rsi, "args": {"n": 20}, "label": "RSI(20)"},
    # --- 布林 ---
    "ratio_bb20": {"fn": compute_ratio_bb, "args": {"n": 20}, "label": "布林(20)"},
    "ratio_bb40": {"fn": compute_ratio_bb, "args": {"n": 40}, "label": "布林(40)"},
    "ratio_bb60": {"fn": compute_ratio_bb, "args": {"n": 60}, "label": "布林(60)"},
    # --- 通道 ---
    "ratio_channel60": {"fn": compute_ratio_channel, "args": {"n": 60}, "label": "通道(60)"},
    # --- MACD ---
    "ratio_macd_5_20":  {"fn": compute_ratio_macd, "args": {"fast": 5, "slow": 20, "sig": 9}, "label": "MACD(5,20,9)"},
    # --- Sharpe ---
    "ratio_sharpe20": {"fn": compute_ratio_sharpe, "args": {"n": 20}, "label": "Sharpe(20)"},
    "ratio_sharpe60": {"fn": compute_ratio_sharpe, "args": {"n": 60}, "label": "Sharpe(60)"},
    # --- Ensemble ---
    "ensemble_fast3": {
        "fn": compute_ensemble,
        "args": {"members": ["ratio_ma5", "ratio_mom5", "ratio_ma10"]},
        "label": "快速投票(3)",
    },
}


def compute_signal(name: str, ratio: pd.Series) -> pd.Series:
    """Compute signal series for a named strategy."""
    entry = STRATEGY_REGISTRY[name]
    return entry["fn"](ratio, **entry["args"])


AVAILABLE_STRATEGIES: list[dict[str, str]] = [
    {"key": k, "label": v["label"]} for k, v in STRATEGY_REGISTRY.items()
]
