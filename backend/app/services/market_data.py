from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta
import json
import logging
import math

import akshare as ak
import pandas as pd
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, sessionmaker

from ..database import Base
from ..models import DailyPrice, Instrument
from ..schemas import InstrumentInput, MarketDataSyncRequest

logger = logging.getLogger(__name__)


DEFAULT_INSTRUMENTS = [
    InstrumentInput(symbol="399376", name="国证小盘成长", market="CN", asset_type="INDEX"),
    InstrumentInput(symbol="399373", name="国证大盘价值", market="CN", asset_type="INDEX"),
    InstrumentInput(symbol="159915", name="创业板ETF", market="CN", asset_type="ETF"),
    InstrumentInput(symbol="510300", name="沪深300ETF", market="CN", asset_type="ETF"),
    InstrumentInput(symbol="588000", name="科创50ETF", market="CN", asset_type="ETF"),
    InstrumentInput(symbol="512100", name="中证1000ETF", market="CN", asset_type="ETF"),
    InstrumentInput(symbol="AAA", name="AAA", market="CN", asset_type="INDEX"),
    InstrumentInput(symbol="BBB", name="BBB", market="CN", asset_type="INDEX"),
]


@dataclass(frozen=True)
class SyncItemResult:
    symbol: str
    inserted: int
    updated: int
    range: dict[str, str]


class DataSyncError(RuntimeError):
    pass


def init_database(engine: object) -> None:
    Base.metadata.create_all(bind=engine)


def iter_trading_days(start_date: date, end_date: date) -> list[date]:
    days: list[date] = []
    current = start_date
    while current <= end_date:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def generate_demo_prices(symbol: str, start_date: date, end_date: date, source: str) -> list[dict[str, object]]:
    seed = sum((index + 1) * ord(char) for index, char in enumerate(symbol))
    base_price = 80 + (seed % 180)
    trading_days = iter_trading_days(start_date, end_date)
    rows: list[dict[str, object]] = []
    close = float(base_price)

    for index, trade_date in enumerate(trading_days):
        drift = ((seed % 13) - 6) * 0.00005
        wave = math.sin((index + seed % 29) / 11) * 0.005
        pulse = math.cos((index + seed % 17) / 19) * 0.003
        daily_move = drift + wave + pulse

        open_price = close * (1 + daily_move / 3)
        close = max(1.0, close * (1 + daily_move))
        high = max(open_price, close) * 1.004
        low = min(open_price, close) * 0.996
        volume = float(1_000_000 + ((seed * (index + 3)) % 250_000))
        amount = volume * close

        rows.append(
            {
                "symbol": symbol,
                "trade_date": trade_date,
                "open": round(open_price, 4),
                "high": round(high, 4),
                "low": round(low, 4),
                "close": round(close, 4),
                "volume": round(volume, 2),
                "amount": round(amount, 2),
                "source": source,
                "raw_payload": None,
            }
        )
    return rows


def _format_ymd(value: date) -> str:
    return value.strftime("%Y%m%d")


def _format_iso_date(value: date) -> str:
    return value.strftime("%Y-%m-%d")


def _to_tencent_symbol(instrument: InstrumentInput) -> str:
    symbol = instrument.symbol.lower()
    if symbol.startswith(("sh", "sz", "bj")):
        return symbol
    if symbol.startswith("399"):
        return f"sz{symbol}"
    if symbol.startswith(("5", "6", "9", "000")):
        return f"sh{symbol}"
    return f"sz{symbol}"


def _normalize_akshare_frame(df: pd.DataFrame, instrument: InstrumentInput, source: str) -> list[dict[str, object]]:
    if df.empty:
        raise DataSyncError(f"no market data returned for {instrument.symbol}")

    temp_df = df.copy()
    if "日期" in temp_df.columns:
        temp_df = temp_df.rename(
            columns={
                "日期": "trade_date",
                "开盘": "open",
                "最高": "high",
                "最低": "low",
                "收盘": "close",
                "成交量": "volume",
                "成交额": "amount",
            }
        )
    elif "date" in temp_df.columns:
        temp_df = temp_df.rename(columns={"date": "trade_date"})
        if "amount" in temp_df.columns and "volume" not in temp_df.columns:
            temp_df["volume"] = None
    else:
        raise DataSyncError(f"unsupported upstream schema for {instrument.symbol}")

    required = {"trade_date", "close"}
    if not required.issubset(set(temp_df.columns)):
        raise DataSyncError(f"upstream data missing required columns for {instrument.symbol}")

    for column in ["open", "high", "low", "close", "volume", "amount"]:
        if column in temp_df.columns:
            temp_df[column] = pd.to_numeric(temp_df[column], errors="coerce")
        else:
            temp_df[column] = None

    temp_df["trade_date"] = pd.to_datetime(temp_df["trade_date"], errors="coerce").dt.date
    temp_df = temp_df.dropna(subset=["trade_date", "close"]).sort_values("trade_date").reset_index(drop=True)

    rows: list[dict[str, object]] = []
    for row in temp_df.to_dict(orient="records"):
        rows.append(
            {
                "symbol": instrument.symbol,
                "trade_date": row["trade_date"],
                "open": round(float(row["open"]), 4) if pd.notna(row["open"]) else None,
                "high": round(float(row["high"]), 4) if pd.notna(row["high"]) else None,
                "low": round(float(row["low"]), 4) if pd.notna(row["low"]) else None,
                "close": round(float(row["close"]), 4),
                "volume": round(float(row["volume"]), 2) if pd.notna(row["volume"]) else None,
                "amount": round(float(row["amount"]), 2) if pd.notna(row["amount"]) else None,
                "source": source,
                "raw_payload": json.dumps(row, ensure_ascii=False, default=str),
            }
        )
    return rows


def _fetch_eastmoney_history(instrument: InstrumentInput, start_date: date, end_date: date) -> pd.DataFrame:
    start_text = _format_ymd(start_date)
    end_text = _format_ymd(end_date)
    asset_type = instrument.asset_type.upper()

    if asset_type == "ETF":
        return ak.fund_etf_hist_em(
            symbol=instrument.symbol,
            period="daily",
            start_date=start_text,
            end_date=end_text,
            adjust="",
        )
    if asset_type == "INDEX":
        return ak.index_zh_a_hist(
            symbol=instrument.symbol,
            period="daily",
            start_date=start_text,
            end_date=end_text,
        )
    return ak.stock_zh_a_hist(
        symbol=instrument.symbol,
        period="daily",
        start_date=start_text,
        end_date=end_text,
        adjust="",
    )


def _fetch_tencent_history(instrument: InstrumentInput, start_date: date, end_date: date) -> pd.DataFrame:
    if instrument.asset_type.upper() == "ETF":
        raise DataSyncError("tencent source is not supported for ETF symbols in this project")
    return ak.stock_zh_a_hist_tx(
        symbol=_to_tencent_symbol(instrument),
        start_date=_format_iso_date(start_date),
        end_date=_format_iso_date(end_date),
        adjust="",
    )


def fetch_market_rows(instrument: InstrumentInput, payload: MarketDataSyncRequest) -> list[dict[str, object]]:
    source = payload.source.lower()
    logger.info(
        "sync.fetch.start symbol=%s asset_type=%s source=%s start_date=%s end_date=%s",
        instrument.symbol,
        instrument.asset_type,
        payload.source,
        payload.start_date,
        payload.end_date,
    )
    if source == "demo":
        rows = generate_demo_prices(instrument.symbol, payload.start_date, payload.end_date, payload.source)
        logger.info(
            "sync.fetch.done symbol=%s source=%s rows=%s mode=demo",
            instrument.symbol,
            payload.source,
            len(rows),
        )
        return rows
    if source == "eastmoney":
        raise DataSyncError("eastmoney source is disabled in this project")

    try:
        if source == "tencent":
            frame = _fetch_tencent_history(instrument, payload.start_date, payload.end_date)
        else:
            raise DataSyncError(f"unsupported source: {payload.source}")
    except DataSyncError:
        raise
    except Exception as exc:
        logger.exception(
            "sync.fetch.error symbol=%s asset_type=%s source=%s start_date=%s end_date=%s",
            instrument.symbol,
            instrument.asset_type,
            payload.source,
            payload.start_date,
            payload.end_date,
        )
        raise DataSyncError(f"failed to fetch {instrument.symbol} from {payload.source}: {exc}") from exc

    logger.info(
        "sync.fetch.raw symbol=%s source=%s rows=%s columns=%s",
        instrument.symbol,
        payload.source,
        len(frame),
        list(frame.columns),
    )
    rows = _normalize_akshare_frame(frame, instrument, payload.source)
    logger.info(
        "sync.fetch.done symbol=%s source=%s rows=%s earliest=%s latest=%s",
        instrument.symbol,
        payload.source,
        len(rows),
        rows[0]["trade_date"] if rows else None,
        rows[-1]["trade_date"] if rows else None,
    )
    return rows


def upsert_instrument(session: Session, instrument: InstrumentInput, source: str) -> None:
    stmt = sqlite_insert(Instrument).values(
        symbol=instrument.symbol,
        name=instrument.name,
        market=instrument.market,
        asset_type=instrument.asset_type,
        source=source,
        is_active=True,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[Instrument.symbol],
        set_={
            "name": instrument.name,
            "market": instrument.market,
            "asset_type": instrument.asset_type,
            "source": source,
            "is_active": True,
        },
    )
    session.execute(stmt)


def upsert_daily_prices(session: Session, rows: list[dict[str, object]]) -> tuple[int, int]:
    if not rows:
        return 0, 0

    symbol = str(rows[0]["symbol"])
    trade_dates = [row["trade_date"] for row in rows]
    existing_dates = set(
        session.scalars(
            select(DailyPrice.trade_date).where(
                DailyPrice.symbol == symbol,
                DailyPrice.trade_date.in_(trade_dates),
            )
        ).all()
    )
    inserted = sum(1 for row in rows if row["trade_date"] not in existing_dates)
    updated = len(rows) - inserted

    stmt = sqlite_insert(DailyPrice).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[DailyPrice.symbol, DailyPrice.trade_date],
        set_={
            "open": stmt.excluded.open,
            "high": stmt.excluded.high,
            "low": stmt.excluded.low,
            "close": stmt.excluded.close,
            "volume": stmt.excluded.volume,
            "amount": stmt.excluded.amount,
            "source": stmt.excluded.source,
            "raw_payload": stmt.excluded.raw_payload,
        },
    )
    session.execute(stmt)
    return inserted, updated


def delete_existing_prices_for_range(
    session: Session,
    symbol: str,
    start_date: date,
    end_date: date,
) -> None:
    deleted = session.execute(
        delete(DailyPrice).where(
            DailyPrice.symbol == symbol,
            DailyPrice.trade_date >= start_date,
            DailyPrice.trade_date <= end_date,
        )
    )
    logger.info(
        "sync.delete symbol=%s start_date=%s end_date=%s deleted_rows=%s",
        symbol,
        start_date,
        end_date,
        deleted.rowcount,
    )


def sync_market_data(session: Session, payload: MarketDataSyncRequest) -> dict[str, object]:
    items: list[dict[str, object]] = []
    logger.info(
        "sync.request source=%s symbols=%s start_date=%s end_date=%s",
        payload.source,
        [instrument.symbol for instrument in payload.symbols],
        payload.start_date,
        payload.end_date,
    )

    for instrument in payload.symbols:
        upsert_instrument(session, instrument, payload.source)
        rows = fetch_market_rows(instrument, payload)
        delete_existing_prices_for_range(session, instrument.symbol, payload.start_date, payload.end_date)
        inserted, updated = upsert_daily_prices(session, rows)
        logger.info(
            "sync.write symbol=%s source=%s inserted=%s updated=%s rows=%s",
            instrument.symbol,
            payload.source,
            inserted,
            updated,
            len(rows),
        )
        items.append(
            asdict(
                SyncItemResult(
                    symbol=instrument.symbol,
                    inserted=inserted,
                    updated=updated,
                    range={
                        "start_date": payload.start_date.isoformat(),
                        "end_date": payload.end_date.isoformat(),
                    },
                )
            )
        )

    session.commit()
    logger.info(
        "sync.commit source=%s symbols=%s",
        payload.source,
        [instrument.symbol for instrument in payload.symbols],
    )
    return {"source": payload.source, "items": items}


def seed_default_data(session_factory: sessionmaker[Session]) -> None:
    session = session_factory()
    try:
        has_instruments = session.scalar(select(func.count()).select_from(Instrument)) or 0
        if has_instruments:
            return

        payload = MarketDataSyncRequest(
            symbols=DEFAULT_INSTRUMENTS,
            source="demo",
            start_date=date(2018, 1, 1),
            end_date=date.today(),
        )
        sync_market_data(session, payload)
    finally:
        session.close()
