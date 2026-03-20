from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class InstrumentInput(BaseModel):
    symbol: str
    name: str
    market: str = "CN"
    asset_type: str = "INDEX"


class MarketDataSyncRequest(BaseModel):
    symbols: list[InstrumentInput] = Field(min_length=1)
    source: str = "demo"
    start_date: date
    end_date: date

