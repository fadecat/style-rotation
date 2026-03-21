from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import DailyPrice, IndexValuation, Instrument


class InsufficientDataError(ValueError):
    pass


@dataclass(frozen=True)
class StyleRotationParams:
    left_symbol: str
    right_symbol: str
    start_date: str | None
    end_date: str | None
    return_window: int
    ma_window: int
    quantile_window_min: int


VALUATION_METRICS = {
    "pe": {"column": "pe_ttm", "label": "PE", "percentile_column": "pe_percentile"},
    "pb": {"column": "pb", "label": "PB", "percentile_column": "pb_percentile"},
    "dividend_yield": {"column": "dividend_yield", "label": "股息率", "percentile_column": None},
}



def calculate_style_rotation(
    df_left: pd.DataFrame,
    df_right: pd.DataFrame,
    params: StyleRotationParams,
) -> dict[str, object]:
    df_left = df_left.copy()
    df_right = df_right.copy()

    df_left["trade_date"] = pd.to_datetime(df_left["trade_date"])
    df_right["trade_date"] = pd.to_datetime(df_right["trade_date"])

    df_left["close"] = df_left["close"].astype(float)
    df_right["close"] = df_right["close"].astype(float)

    df_left = df_left.sort_values("trade_date").reset_index(drop=True)
    df_right = df_right.sort_values("trade_date").reset_index(drop=True)

    df = pd.merge(
        df_left[["trade_date", "close"]],
        df_right[["trade_date", "close"]],
        on="trade_date",
        how="inner",
        suffixes=("_left", "_right"),
    )

    if df.empty:
        raise InsufficientDataError("aligned data is empty")

    df = df.sort_values("trade_date").reset_index(drop=True)
    df["left_return"] = df["close_left"].pct_change(params.return_window) * 100
    df["right_return"] = df["close_right"].pct_change(params.return_window) * 100
    df["spread"] = df["left_return"] - df["right_return"]
    df = df.dropna(subset=["left_return", "right_return", "spread"]).reset_index(drop=True)

    if df.empty:
        raise InsufficientDataError("not enough data after return window")

    df["ma"] = df["spread"].rolling(params.ma_window).mean()
    df["p90_dynamic"] = df["spread"].expanding(min_periods=params.quantile_window_min).quantile(0.9)
    df["p10_dynamic"] = df["spread"].expanding(min_periods=params.quantile_window_min).quantile(0.1)
    df["date_str"] = df["trade_date"].dt.strftime("%Y-%m-%d")

    signals_all: list[dict[str, object]] = []
    for index in range(1, len(df)):
        prev_spread = df["spread"].iloc[index - 1]
        curr_spread = df["spread"].iloc[index]
        prev_ma = df["ma"].iloc[index - 1]
        curr_ma = df["ma"].iloc[index]
        prev_p90 = df["p90_dynamic"].iloc[index - 1]
        prev_p10 = df["p10_dynamic"].iloc[index - 1]

        if pd.notna(prev_spread) and pd.notna(curr_spread) and pd.notna(prev_ma) and pd.notna(curr_ma):
            if pd.notna(prev_p90) and prev_spread > prev_ma and curr_spread < curr_ma and prev_spread > prev_p90:
                signals_all.append(
                    {
                        "date": df["date_str"].iloc[index],
                        "type": "sell",
                        "spread": round(float(curr_spread), 2),
                    }
                )
            elif pd.notna(prev_p10) and prev_spread < prev_ma and curr_spread > curr_ma and prev_spread < prev_p10:
                signals_all.append(
                    {
                        "date": df["date_str"].iloc[index],
                        "type": "buy",
                        "spread": round(float(curr_spread), 2),
                    }
                )

    global_p90 = round(float(df["spread"].quantile(0.9)), 2)
    global_p10 = round(float(df["spread"].quantile(0.1)), 2)

    if params.start_date:
        df = df[df["date_str"] >= params.start_date].reset_index(drop=True)
        signals_all = [signal for signal in signals_all if signal["date"] >= params.start_date]
    if params.end_date:
        df = df[df["date_str"] <= params.end_date].reset_index(drop=True)
        signals_all = [signal for signal in signals_all if signal["date"] <= params.end_date]

    df = df.dropna(subset=["ma", "p90_dynamic", "p10_dynamic"]).reset_index(drop=True)
    signals_all = [signal for signal in signals_all if signal["date"] in set(df["date_str"].tolist())]

    if df.empty:
        raise InsufficientDataError("empty after date filter")

    left_base = float(df["close_left"].iloc[0])
    right_base = float(df["close_right"].iloc[0])
    df["left_nav"] = df["close_left"] / left_base
    df["right_nav"] = df["close_right"] / right_base

    latest_date = df["date_str"].iloc[-1]
    latest_signal = next((signal["type"] for signal in reversed(signals_all) if signal["date"] == latest_date), "none")

    return {
        "dates": df["date_str"].tolist(),
        "left_close": df["close_left"].round(4).tolist(),
        "right_close": df["close_right"].round(4).tolist(),
        "left_return": df["left_return"].round(2).tolist(),
        "right_return": df["right_return"].round(2).tolist(),
        "spread": df["spread"].round(2).tolist(),
        "ma": df["ma"].round(2).tolist(),
        "p90_dynamic": df["p90_dynamic"].round(2).tolist(),
        "p10_dynamic": df["p10_dynamic"].round(2).tolist(),
        "left_nav": df["left_nav"].round(4).tolist(),
        "right_nav": df["right_nav"].round(4).tolist(),
        "signals": signals_all,
        "global_p90": global_p90,
        "global_p10": global_p10,
        "latest_signal": latest_signal,
    }


def _load_price_frame(session: Session, symbol: str, start: date | None, end: date | None) -> pd.DataFrame:
    query = select(DailyPrice.trade_date, DailyPrice.close).where(DailyPrice.symbol == symbol)
    if start:
        query = query.where(DailyPrice.trade_date >= start)
    if end:
        query = query.where(DailyPrice.trade_date <= end)
    query = query.order_by(DailyPrice.trade_date.asc())

    rows = session.execute(query).all()
    return pd.DataFrame(rows, columns=["trade_date", "close"])


def _load_instrument_name(session: Session, symbol: str) -> str:
    instrument = session.scalar(select(Instrument).where(Instrument.symbol == symbol))
    return instrument.name if instrument else symbol


def _build_metric_comparison(
    session: Session,
    left_symbol: str,
    right_symbol: str,
    metric_key: str,
    start: date | None,
    end: date | None,
) -> dict[str, object]:
    metric = VALUATION_METRICS[metric_key]
    value_column = getattr(IndexValuation, metric["column"])
    percentile_name = metric["percentile_column"]
    percentile_column = getattr(IndexValuation, percentile_name) if percentile_name else None

    query_columns = [IndexValuation.trade_date, IndexValuation.symbol, value_column]
    if percentile_column is not None:
        query_columns.append(percentile_column)

    query = select(*query_columns).where(
        IndexValuation.symbol.in_([left_symbol, right_symbol]),
        value_column.is_not(None),
    )
    if start:
        query = query.where(IndexValuation.trade_date >= start)
    if end:
        query = query.where(IndexValuation.trade_date <= end)
    query = query.order_by(IndexValuation.trade_date.asc())

    rows = session.execute(query).all()
    values_by_symbol: dict[str, dict[str, float]] = {left_symbol: {}, right_symbol: {}}
    percentile_by_symbol: dict[str, dict[str, float | None]] = {left_symbol: {}, right_symbol: {}}
    for row in rows:
        trade_date, symbol, value = row[:3]
        percentile_value = row[3] if percentile_column is not None and len(row) > 3 else None
        values_by_symbol.setdefault(symbol, {})[trade_date.isoformat()] = round(float(value), 6)
        if percentile_column is not None:
            percentile_by_symbol.setdefault(symbol, {})[trade_date.isoformat()] = (
                round(float(percentile_value), 6) if percentile_value is not None else None
            )

    all_dates = sorted(set(values_by_symbol[left_symbol]) | set(values_by_symbol[right_symbol]))
    left_values = [values_by_symbol[left_symbol].get(item) for item in all_dates]
    right_values = [values_by_symbol[right_symbol].get(item) for item in all_dates]
    result = {
        "label": metric["label"],
        "dates": all_dates,
        "left": left_values,
        "right": right_values,
        "left_count": len(values_by_symbol[left_symbol]),
        "right_count": len(values_by_symbol[right_symbol]),
    }
    if percentile_column is not None:
        result["left_percentile"] = [percentile_by_symbol[left_symbol].get(item) for item in all_dates]
        result["right_percentile"] = [percentile_by_symbol[right_symbol].get(item) for item in all_dates]
    return result


def _build_valuation_comparison(
    session: Session,
    left_symbol: str,
    right_symbol: str,
    start: date | None,
    end: date | None,
) -> dict[str, object]:
    return {
        metric_key: _build_metric_comparison(session, left_symbol, right_symbol, metric_key, start, end)
        for metric_key in VALUATION_METRICS
    }


def build_style_rotation_response(session: Session, params: StyleRotationParams) -> dict[str, object]:
    query_start = None
    if params.start_date:
        query_start = date.fromisoformat(params.start_date) - timedelta(days=max(400, params.return_window + 150))
    query_end = date.fromisoformat(params.end_date) if params.end_date else None

    df_left = _load_price_frame(session, params.left_symbol, query_start, query_end)
    df_right = _load_price_frame(session, params.right_symbol, query_start, query_end)

    if df_left.empty or df_right.empty:
        raise InsufficientDataError("symbol data is missing")

    result = calculate_style_rotation(df_left, df_right, params)
    signals = result["signals"]
    valuation_start = date.fromisoformat(params.start_date) if params.start_date else None
    valuation_end = date.fromisoformat(params.end_date) if params.end_date else None
    return {
        "meta": {
            "left_symbol": params.left_symbol,
            "right_symbol": params.right_symbol,
            "left_name": _load_instrument_name(session, params.left_symbol),
            "right_name": _load_instrument_name(session, params.right_symbol),
            "return_window": params.return_window,
            "ma_window": params.ma_window,
            "quantile_window_min": params.quantile_window_min,
            "start_date": params.start_date,
            "end_date": params.end_date,
        },
        "series": {
            "dates": result["dates"],
            "left_close": result["left_close"],
            "right_close": result["right_close"],
            "spread": result["spread"],
            "ma": result["ma"],
            "p90_dynamic": result["p90_dynamic"],
            "p10_dynamic": result["p10_dynamic"],
        },
        "summary": {
            "latest_spread": result["spread"][-1],
            "latest_ma": result["ma"][-1],
            "global_p90": result["global_p90"],
            "global_p10": result["global_p10"],
            "signal_count": len(signals),
            "latest_signal": result["latest_signal"],
        },
        "signals": signals,
        "valuations": _build_valuation_comparison(
            session,
            params.left_symbol,
            params.right_symbol,
            valuation_start,
            valuation_end,
        ),
    }


# ---------------------------------------------------------------------------
# Dual-threshold rotation backtest
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BacktestParams:
    left_symbol: str
    right_symbol: str
    start_date: str
    end_date: str
    strategy: str = "ratio_mom20"
    fee: float = 0.001
    rebalance: str = "weekly"  # "daily" | "weekly" | "monthly"


def run_backtest(
    session: Session,
    params: BacktestParams,
) -> dict[str, object]:
    """Factor-based rotation backtest.

    Signal is computed by the chosen strategy on the price ratio.
    signal > 0 → hold left, signal < 0 → hold right.
    Signal at t close → position changes from t+1.
    """
    # 120 extra trading days (~170 calendar days) for signal warm-up
    query_start = date.fromisoformat(params.start_date) - timedelta(days=250)
    query_end = date.fromisoformat(params.end_date)

    df_left = _load_price_frame(session, params.left_symbol, query_start, query_end)
    df_right = _load_price_frame(session, params.right_symbol, query_start, query_end)

    if df_left.empty or df_right.empty:
        raise InsufficientDataError("symbol data is missing")

    return _calc_backtest(df_left, df_right, params)


def _calc_backtest(
    df_left: pd.DataFrame,
    df_right: pd.DataFrame,
    params: BacktestParams,
) -> dict[str, object]:
    from .backtest_strategies import AVAILABLE_STRATEGIES, compute_signal

    dl = df_left.copy()
    dr = df_right.copy()
    dl["trade_date"] = pd.to_datetime(dl["trade_date"])
    dr["trade_date"] = pd.to_datetime(dr["trade_date"])
    dl["close"] = dl["close"].astype(float)
    dr["close"] = dr["close"].astype(float)
    dl = dl.sort_values("trade_date").reset_index(drop=True)
    dr = dr.sort_values("trade_date").reset_index(drop=True)

    df = pd.merge(
        dl[["trade_date", "close"]],
        dr[["trade_date", "close"]],
        on="trade_date",
        how="inner",
        suffixes=("_left", "_right"),
    ).sort_values("trade_date").reset_index(drop=True)

    if len(df) < 30:
        raise InsufficientDataError("not enough data for backtest")

    # Compute ratio and signal on full history (including warm-up)
    df["ratio"] = df["close_left"] / df["close_right"]
    df["signal"] = compute_signal(params.strategy, df["ratio"])
    df["date_str"] = df["trade_date"].dt.strftime("%Y-%m-%d")

    # Trim to requested date range
    start_str = params.start_date
    end_str = params.end_date
    df_range = df[
        (df["date_str"] >= start_str) & (df["date_str"] <= end_str)
    ].reset_index(drop=True)

    if df_range.empty:
        raise InsufficientDataError("no data in requested date range")

    # Baselines
    left_base = float(df_range["close_left"].iloc[0])
    right_base = float(df_range["close_right"].iloc[0])
    left_nav_series = (df_range["close_left"] / left_base).round(4).tolist()
    right_nav_series = (df_range["close_right"] / right_base).round(4).tolist()

    # Daily returns
    left_daily = (df_range["close_left"] / df_range["close_left"].shift(1) - 1).fillna(0.0)
    right_daily = (df_range["close_right"] / df_range["close_right"].shift(1) - 1).fillna(0.0)

    dates_list = df_range["date_str"].tolist()
    signal_list = df_range["signal"].values  # numpy array for speed
    n = len(df_range)

    # Also get the signal value from the day before range start (for t+1 logic)
    pre_range = df[df["date_str"] < start_str]
    prev_signal = float(pre_range["signal"].iloc[-1]) if len(pre_range) > 0 and pd.notna(pre_range["signal"].iloc[-1]) else np.nan

    # Build rebalance mask
    if params.rebalance == "weekly":
        rebal_mask = (df_range["trade_date"].dt.weekday == 4).values  # Friday
    elif params.rebalance == "monthly":
        ym = df_range["trade_date"].dt.to_period("M")
        rebal_mask = (ym != ym.shift(-1)).values
        rebal_mask[-1] = True
    else:
        rebal_mask = np.ones(n, dtype=bool)  # daily

    # Walk day by day — t+1 execution:
    #   signal at t close → position changes from t+1
    #   This avoids look-ahead bias and matches real-world execution.
    nav_series: list[float] = [1.0] * n
    holding: str | None = None  # "left" | "right"
    nav_val = 1.0
    FEE = params.fee

    l_ret = left_daily.values
    r_ret = right_daily.values

    # Round-trip trade tracking
    trades: list[dict] = []
    current_trade_entry_idx: int | None = None
    current_trade_entry_nav: float = 1.0
    current_trade_holding: str | None = None

    def _open_trade(day_idx: int, hold: str, nav: float) -> None:
        nonlocal current_trade_entry_idx, current_trade_entry_nav, current_trade_holding
        current_trade_entry_idx = day_idx
        current_trade_entry_nav = nav
        current_trade_holding = hold

    def _close_trade(day_idx: int, nav: float) -> None:
        nonlocal current_trade_entry_idx, current_trade_entry_nav, current_trade_holding
        if current_trade_entry_idx is None:
            return
        trades.append({
            "entry_date": dates_list[current_trade_entry_idx],
            "exit_date": dates_list[day_idx],
            "holding": current_trade_holding,
            "days": day_idx - current_trade_entry_idx,
            "entry_nav": round(current_trade_entry_nav, 4),
            "exit_nav": round(nav, 4),
            "return_pct": round((nav / current_trade_entry_nav - 1) * 100, 2),
        })
        current_trade_entry_idx = None

    for i in range(n):
        # t+1: use previous day's signal to decide today's holding
        # Only act on rebalance days
        sig = prev_signal if i == 0 else signal_list[i - 1]

        if rebal_mask[i] and not np.isnan(sig):
            if sig > 0:
                desired = "left"
            elif sig < 0:
                desired = "right"
            else:
                desired = holding  # exactly zero → keep current

            if desired is not None and desired != holding:
                if holding is not None:
                    _close_trade(i, nav_val)
                nav_val *= (1 - FEE)
                holding = desired
                _open_trade(i, holding, nav_val)

        # Apply daily return (skip day 0 — no return on first day)
        if holding is not None and i > 0:
            r = l_ret[i] if holding == "left" else r_ret[i]
            if not np.isnan(r):
                nav_val *= (1 + r)

        nav_series[i] = round(nav_val, 6)

    # Close last open trade at end
    if current_trade_entry_idx is not None:
        _close_trade(n - 1, nav_val)

    # Drawdown curve
    peak = 0.0
    drawdown: list[float] = []
    for v in nav_series:
        if v > peak:
            peak = v
        dd = ((v - peak) / peak * 100) if peak > 0 else 0.0
        drawdown.append(round(dd, 2))

    # Max drawdown days
    max_dd_days = _calc_max_dd_days(nav_series)

    # Yearly stats
    yearly = _calc_yearly_stats(dates_list, nav_series, trades)

    # Summary stats
    final_nav = nav_series[-1] if nav_series else 1.0
    total_return = round((final_nav - 1) * 100, 2)
    n_years = max((date.fromisoformat(end_str) - date.fromisoformat(start_str)).days / 365.25, 0.01)
    annual_return = round((final_nav ** (1 / n_years) - 1) * 100, 2)
    max_dd = min(drawdown) if drawdown else 0.0
    win_trades = [t for t in trades if t["return_pct"] > 0]
    win_rate = round(len(win_trades) / len(trades) * 100, 1) if trades else 0.0
    avg_days = round(sum(t["days"] for t in trades) / len(trades), 1) if trades else 0.0

    from .backtest_strategies import STRATEGY_REGISTRY
    strategy_label = STRATEGY_REGISTRY.get(params.strategy, {}).get("label", params.strategy)

    stats = {
        "strategy_name": strategy_label,
        "total_return_pct": total_return,
        "final_nav": round(final_nav, 4),
        "annual_return_pct": annual_return,
        "max_drawdown_pct": round(abs(max_dd), 2),
        "max_drawdown_days": max_dd_days,
        "trade_count": len(trades),
        "win_rate": win_rate,
        "avg_holding_days": avg_days,
        "left_nav_final": left_nav_series[-1],
        "right_nav_final": right_nav_series[-1],
    }

    return {
        "dates": dates_list,
        "nav": nav_series,
        "left_nav": left_nav_series,
        "right_nav": right_nav_series,
        "signal": [round(s, 6) if pd.notna(s) else None for s in signal_list],
        "drawdown": drawdown,
        "trades": trades,
        "yearly": yearly,
        "stats": stats,
        "available_strategies": AVAILABLE_STRATEGIES,
    }


def _calc_max_dd_days(nav_series: list[float]) -> int:
    """Longest drawdown duration in trading days."""
    max_days = 0
    current_days = 0
    peak = 0.0
    for v in nav_series:
        if v >= peak:
            peak = v
            current_days = 0
        else:
            current_days += 1
            if current_days > max_days:
                max_days = current_days
    return max_days


def _calc_yearly_stats(
    dates: list[str], nav: list[float], trades: list[dict]
) -> list[dict]:
    """Per-year return, max drawdown, trade count."""
    if not dates:
        return []
    years: dict[str, list[tuple[int, str, float]]] = {}
    for i, (d, v) in enumerate(zip(dates, nav)):
        y = d[:4]
        years.setdefault(y, []).append((i, d, v))

    result = []
    for y in sorted(years):
        entries = years[y]
        first_nav = entries[0][2]
        last_nav = entries[-1][2]
        ret = round((last_nav / first_nav - 1) * 100, 2) if first_nav > 0 else 0.0

        # Max drawdown within year
        peak = 0.0
        max_dd = 0.0
        for _, _, v in entries:
            if v > peak:
                peak = v
            dd = (peak - v) / peak if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd

        # Trade count in year
        tc = sum(1 for t in trades if t["entry_date"][:4] == y)

        result.append({
            "year": y,
            "return_pct": ret,
            "max_drawdown_pct": round(max_dd * 100, 2),
            "trade_count": tc,
        })
    return result
