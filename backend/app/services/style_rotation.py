from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import DailyPrice, Instrument


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
    }
