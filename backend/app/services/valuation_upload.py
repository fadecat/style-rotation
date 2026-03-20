from __future__ import annotations

from dataclasses import asdict, dataclass
import io
import logging

import pandas as pd
from sqlalchemy import delete, or_, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ..models import IndexValuation

logger = logging.getLogger(__name__)

METRIC_PE = "pe"
METRIC_PB = "pb"
METRIC_DIVIDEND = "dividend_yield"
SUPPORTED_METRICS = {METRIC_PE, METRIC_PB, METRIC_DIVIDEND}


class ValuationUploadError(RuntimeError):
    pass


@dataclass(frozen=True)
class ValuationUploadResult:
    symbol: str
    metric_type: str
    inserted: int
    updated: int
    row_count: int
    earliest_date: str | None
    latest_date: str | None
    source_file: str


@dataclass(frozen=True)
class ValuationMetricStatus:
    exists: bool
    row_count: int
    earliest_date: str | None
    latest_date: str | None


COMMON_COLUMN_MAP = {
    "日期": "trade_date",
    "收盘点位": "close",
    "全收益收盘点位(元)": "total_return_close",
    "市值(元)": "market_value",
    "流通市值(元)": "float_market_value",
    "自由流通市值(元)": "free_float_market_value",
}

METRIC_COLUMN_MAP = {
    METRIC_PE: {
        "PE-TTM市值加权": "pe_ttm",
        "PE-TTM 分位点": "pe_percentile",
        "PE-TTM 80%分位点值": "pe_p80",
        "PE-TTM 50%分位点值": "pe_p50",
        "PE-TTM 20%分位点值": "pe_p20",
    },
    METRIC_PB: {
        "PB市值加权": "pb",
        "PB 分位点": "pb_percentile",
        "PB 80%分位点值": "pb_p80",
        "PB 50%分位点值": "pb_p50",
        "PB 20%分位点值": "pb_p20",
    },
    METRIC_DIVIDEND: {
        "股息率市值加权": "dividend_yield",
    },
}

ALL_METRIC_COLUMNS = sorted({column for mapping in METRIC_COLUMN_MAP.values() for column in mapping.values()})
SHARED_COLUMNS = ["close", "total_return_close", "market_value", "float_market_value", "free_float_market_value"]


def _decode_upload(content: bytes) -> pd.DataFrame:
    attempts = ("utf-8-sig", "utf-8", "gb18030")
    last_error: Exception | None = None
    for encoding in attempts:
        try:
            return pd.read_csv(io.BytesIO(content), encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    raise ValuationUploadError(f"unable to decode csv file: {last_error}")


def _clean_cell(value: object) -> object:
    if isinstance(value, str):
        return value.strip().lstrip("=")
    return value


def _normalize_frame(df: pd.DataFrame, symbol: str, metric_type: str, source_file: str) -> list[dict[str, object]]:
    if metric_type not in SUPPORTED_METRICS:
        raise ValuationUploadError(f"unsupported metric_type: {metric_type}")

    temp_df = df.copy()
    temp_df.columns = [str(column).strip() for column in temp_df.columns]
    temp_df = temp_df.map(_clean_cell)

    required_columns = {"日期", *COMMON_COLUMN_MAP.keys(), *METRIC_COLUMN_MAP[metric_type].keys()}
    missing = [column for column in required_columns if column not in temp_df.columns]
    if missing:
        raise ValuationUploadError(f"csv missing required columns: {missing}")

    rename_map = {**COMMON_COLUMN_MAP, **METRIC_COLUMN_MAP[metric_type]}
    temp_df = temp_df.rename(columns=rename_map)
    temp_df["trade_date"] = pd.to_datetime(temp_df["trade_date"], errors="coerce").dt.date

    numeric_columns = [column for column in rename_map.values() if column != "trade_date"]
    for column in numeric_columns:
        temp_df[column] = pd.to_numeric(temp_df[column], errors="coerce")

    temp_df = temp_df.dropna(subset=["trade_date"]).sort_values("trade_date").reset_index(drop=True)
    if temp_df.empty:
        raise ValuationUploadError("csv contains no valid valuation rows")

    rows: list[dict[str, object]] = []
    for row in temp_df.to_dict(orient="records"):
        item = {
            "symbol": symbol,
            "trade_date": row["trade_date"],
            "source": "gxl_csv",
            "source_file": source_file,
        }
        for column in numeric_columns:
            value = row.get(column)
            item[column] = round(float(value), 6) if pd.notna(value) else None
        rows.append(item)
    return rows


def clear_metric_for_symbol(session: Session, symbol: str, metric_type: str) -> tuple[int, int]:
    metric_columns = METRIC_COLUMN_MAP[metric_type].values()
    clear_stmt = (
        update(IndexValuation)
        .where(IndexValuation.symbol == symbol)
        .values({column: None for column in metric_columns})
    )
    cleared_rows = session.execute(clear_stmt).rowcount or 0

    remaining_metric_filters = [getattr(IndexValuation, column).is_not(None) for column in ALL_METRIC_COLUMNS]
    delete_stmt = delete(IndexValuation).where(
        IndexValuation.symbol == symbol,
        ~or_(*remaining_metric_filters),
    )
    deleted_rows = session.execute(delete_stmt).rowcount or 0
    return cleared_rows, deleted_rows


def upsert_valuation_rows(session: Session, rows: list[dict[str, object]], metric_type: str) -> tuple[int, int]:
    if not rows:
        return 0, 0

    symbol = str(rows[0]["symbol"])
    trade_dates = [row["trade_date"] for row in rows]
    existing_dates = set(
        date_value
        for date_value, in session.query(IndexValuation.trade_date)
        .filter(IndexValuation.symbol == symbol, IndexValuation.trade_date.in_(trade_dates))
        .all()
    )
    inserted = sum(1 for row in rows if row["trade_date"] not in existing_dates)
    updated = len(rows) - inserted

    stmt = sqlite_insert(IndexValuation).values(rows)
    metric_columns = list(METRIC_COLUMN_MAP[metric_type].values())
    update_columns = {column: getattr(stmt.excluded, column) for column in SHARED_COLUMNS + metric_columns}
    update_columns["source"] = stmt.excluded.source
    update_columns["source_file"] = stmt.excluded.source_file
    stmt = stmt.on_conflict_do_update(
        index_elements=[IndexValuation.symbol, IndexValuation.trade_date],
        set_=update_columns,
    )
    session.execute(stmt)
    return inserted, updated


def upload_valuation_csv(
    session: Session,
    symbol: str,
    metric_type: str,
    source_file: str,
    content: bytes,
) -> dict[str, object]:
    logger.info("valuation.upload.start symbol=%s metric_type=%s source_file=%s", symbol, metric_type, source_file)
    frame = _decode_upload(content)
    rows = _normalize_frame(frame, symbol=symbol, metric_type=metric_type, source_file=source_file)
    cleared_rows, deleted_rows = clear_metric_for_symbol(session, symbol, metric_type)
    logger.info(
        "valuation.upload.clear symbol=%s metric_type=%s cleared_rows=%s deleted_rows=%s",
        symbol,
        metric_type,
        cleared_rows,
        deleted_rows,
    )
    inserted, updated = upsert_valuation_rows(session, rows, metric_type)
    session.commit()
    result = ValuationUploadResult(
        symbol=symbol,
        metric_type=metric_type,
        inserted=inserted,
        updated=updated,
        row_count=len(rows),
        earliest_date=rows[0]["trade_date"].isoformat(),
        latest_date=rows[-1]["trade_date"].isoformat(),
        source_file=source_file,
    )
    logger.info(
        "valuation.upload.done symbol=%s metric_type=%s inserted=%s updated=%s row_count=%s earliest=%s latest=%s",
        symbol,
        metric_type,
        inserted,
        updated,
        len(rows),
        result.earliest_date,
        result.latest_date,
    )
    return asdict(result)


def get_valuation_status(session: Session, symbol: str) -> dict[str, object]:
    rows = session.query(
        IndexValuation.trade_date,
        IndexValuation.pe_ttm,
        IndexValuation.pb,
        IndexValuation.dividend_yield,
    ).filter(IndexValuation.symbol == symbol).all()

    metric_values: dict[str, list[str]] = {metric: [] for metric in SUPPORTED_METRICS}
    for trade_date, pe_ttm, pb, dividend_yield in rows:
        if pe_ttm is not None:
            metric_values[METRIC_PE].append(trade_date.isoformat())
        if pb is not None:
            metric_values[METRIC_PB].append(trade_date.isoformat())
        if dividend_yield is not None:
            metric_values[METRIC_DIVIDEND].append(trade_date.isoformat())

    metrics: dict[str, dict[str, object]] = {}
    for metric_key in sorted(SUPPORTED_METRICS):
        dates = sorted(metric_values[metric_key])
        status = ValuationMetricStatus(
            exists=bool(dates),
            row_count=len(dates),
            earliest_date=dates[0] if dates else None,
            latest_date=dates[-1] if dates else None,
        )
        metrics[metric_key] = asdict(status)

    return {"symbol": symbol, "metrics": metrics}
