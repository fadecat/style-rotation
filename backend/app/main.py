from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
import logging

from fastapi import Depends, FastAPI, File, Form, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .database import get_session, create_session_factory
from .models import Instrument
from .schemas import MarketDataSyncRequest
from .services.market_data import DataSyncError, get_market_data_status, init_database, seed_default_data, sync_market_data
from .services.style_rotation import BacktestParams, InsufficientDataError, StyleRotationParams, build_style_rotation_response, run_backtest
from .services.valuation_upload import SUPPORTED_METRICS, ValuationUploadError, get_valuation_status, upload_valuation_csv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)


def create_app(database_url: str | None = None, seed_demo: bool = True) -> FastAPI:
    settings: Settings = get_settings(database_url)
    engine, session_factory = create_session_factory(settings.database_url)
    init_database(engine)
    if seed_demo:
        seed_default_data(session_factory)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        engine.dispose()

    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory

    @app.get("/api/health")
    def healthcheck() -> dict[str, object]:
        return {"code": 200, "message": "success", "data": {"status": "ok"}}

    @app.get("/api/instruments")
    def list_instruments(
        asset_type: str | None = Query(default=None),
        keyword: str | None = Query(default=None),
        is_active: bool = Query(default=True),
        session: Session = Depends(get_session),
    ) -> dict[str, object]:
        query = select(Instrument).order_by(Instrument.symbol.asc())
        query = query.where(Instrument.is_active == is_active)
        if asset_type:
            query = query.where(Instrument.asset_type == asset_type)
        if keyword:
            like_value = f"%{keyword}%"
            query = query.where((Instrument.symbol.like(like_value)) | (Instrument.name.like(like_value)))

        items = [
            {
                "symbol": item.symbol,
                "name": item.name,
                "market": item.market,
                "asset_type": item.asset_type,
            }
            for item in session.scalars(query).all()
        ]
        return {"code": 200, "message": "success", "data": {"items": items}}

    @app.post("/api/market-data/sync")
    def sync_endpoint(
        payload: MarketDataSyncRequest,
        session: Session = Depends(get_session),
    ) -> dict[str, object]:
        try:
            data = sync_market_data(session, payload)
        except DataSyncError as exc:
            return JSONResponse(status_code=502, content={"code": 502, "message": str(exc), "data": None})
        return {"code": 200, "message": "sync success", "data": data}

    @app.get("/api/market-data/status")
    def market_data_status_endpoint(
        symbol: str = Query(...),
        session: Session = Depends(get_session),
    ) -> dict[str, object]:
        normalized_symbol = symbol.strip()
        instrument = session.scalar(select(Instrument).where(Instrument.symbol == normalized_symbol))
        if instrument is None:
            return JSONResponse(
                status_code=400,
                content={"code": 400, "message": f"unknown symbol: {normalized_symbol}", "data": None},
            )

        data = get_market_data_status(session, normalized_symbol)
        return {"code": 200, "message": "success", "data": data}

    @app.post("/api/valuations/upload")
    async def upload_valuation_endpoint(
        symbol: str = Form(...),
        metric_type: str = Form(...),
        file: UploadFile = File(...),
        session: Session = Depends(get_session),
    ) -> dict[str, object]:
        normalized_symbol = symbol.strip()
        normalized_metric = metric_type.strip().lower()
        if normalized_metric not in SUPPORTED_METRICS:
            return JSONResponse(
                status_code=400,
                content={"code": 400, "message": f"unsupported metric_type: {metric_type}", "data": None},
            )

        instrument = session.scalar(select(Instrument).where(Instrument.symbol == normalized_symbol))
        if instrument is None:
            return JSONResponse(
                status_code=400,
                content={"code": 400, "message": f"unknown symbol: {normalized_symbol}", "data": None},
            )
        if instrument.asset_type != "INDEX":
            return JSONResponse(
                status_code=400,
                content={"code": 400, "message": f"valuation upload only supports INDEX symbol: {normalized_symbol}", "data": None},
            )

        filename = (file.filename or "upload.csv").strip()
        known_indexes = session.scalars(
            select(Instrument).where(Instrument.asset_type == "INDEX", Instrument.is_active == True)
        ).all()
        conflicting_hint = next(
            (
                item
                for item in known_indexes
                if item.symbol != instrument.symbol
                and any(token and token in filename for token in (item.symbol, item.name))
            ),
            None,
        )
        selected_hint_found = any(token and token in filename for token in (instrument.symbol, instrument.name))
        if conflicting_hint and not selected_hint_found:
            return JSONResponse(
                status_code=400,
                content={
                    "code": 400,
                    "message": (
                        f"upload filename appears to belong to {conflicting_hint.symbol}/{conflicting_hint.name}, "
                        f"but selected symbol is {instrument.symbol}/{instrument.name}"
                    ),
                    "data": None,
                },
            )

        content = await file.read()
        try:
            data = upload_valuation_csv(
                session=session,
                symbol=normalized_symbol,
                metric_type=normalized_metric,
                source_file=filename,
                content=content,
            )
        except ValuationUploadError as exc:
            session.rollback()
            return JSONResponse(status_code=400, content={"code": 400, "message": str(exc), "data": None})
        return {"code": 200, "message": "valuation upload success", "data": data}

    @app.get("/api/valuations/status")
    def valuation_status_endpoint(
        symbol: str = Query(...),
        session: Session = Depends(get_session),
    ) -> dict[str, object]:
        normalized_symbol = symbol.strip()
        instrument = session.scalar(select(Instrument).where(Instrument.symbol == normalized_symbol))
        if instrument is None:
            return JSONResponse(
                status_code=400,
                content={"code": 400, "message": f"unknown symbol: {normalized_symbol}", "data": None},
            )
        if instrument.asset_type != "INDEX":
            return JSONResponse(
                status_code=400,
                content={"code": 400, "message": f"valuation status only supports INDEX symbol: {normalized_symbol}", "data": None},
            )

        data = get_valuation_status(session, normalized_symbol)
        return {"code": 200, "message": "success", "data": data}

    @app.get("/api/style-rotation")
    def style_rotation(
        left_symbol: str = Query(default=settings.default_left_symbol),
        right_symbol: str = Query(default=settings.default_right_symbol),
        start_date: date | None = Query(default=None),
        end_date: date | None = Query(default=None),
        return_window: int = Query(default=250, ge=1),
        ma_window: int = Query(default=20, ge=1),
        quantile_window_min: int = Query(default=20, ge=1),
        session: Session = Depends(get_session),
    ) -> dict[str, object]:
        if left_symbol == right_symbol:
            return JSONResponse(
                status_code=400,
                content={"code": 400, "message": "left_symbol and right_symbol must differ", "data": None},
            )

        params = StyleRotationParams(
            left_symbol=left_symbol,
            right_symbol=right_symbol,
            start_date=start_date.isoformat() if start_date else None,
            end_date=end_date.isoformat() if end_date else None,
            return_window=return_window,
            ma_window=ma_window,
            quantile_window_min=quantile_window_min,
        )

        try:
            data = build_style_rotation_response(session, params)
        except InsufficientDataError:
            return JSONResponse(status_code=404, content={"code": 404, "message": "insufficient data", "data": None})

        return {"code": 200, "message": "success", "data": data}

    @app.get("/api/strategies")
    def strategies_endpoint() -> dict:
        from .services.backtest_strategies import AVAILABLE_STRATEGIES
        return {"code": 200, "message": "success", "data": AVAILABLE_STRATEGIES}

    @app.get("/api/backtest")
    def backtest_endpoint(
        left_symbol: str = Query(default="000852"),
        right_symbol: str = Query(default="000922"),
        start_date: date = Query(default=date(2016, 1, 1)),
        end_date: date = Query(default=date(2026, 3, 20)),
        strategy: str = Query(default="ratio_mom20"),
        fee: float = Query(default=0.001, ge=0, le=0.05),
        rebalance: str = Query(default="weekly", pattern="^(daily|weekly|monthly)$"),
        session: Session = Depends(get_session),
    ) -> dict[str, object]:
        if left_symbol == right_symbol:
            return JSONResponse(
                status_code=400,
                content={"code": 400, "message": "left_symbol and right_symbol must differ", "data": None},
            )
        params = BacktestParams(
            left_symbol=left_symbol,
            right_symbol=right_symbol,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            strategy=strategy,
            fee=fee,
            rebalance=rebalance,
        )
        try:
            data = run_backtest(session, params)
        except InsufficientDataError as exc:
            return JSONResponse(status_code=404, content={"code": 404, "message": str(exc), "data": None})
        return {"code": 200, "message": "success", "data": data}

    return app


app = create_app()
