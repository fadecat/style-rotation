from __future__ import annotations

from datetime import date
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import pandas as pd
from sqlalchemy import select

from backend.app.main import create_app
from backend.app.models import DailyPrice, IndexValuation, Instrument
from backend.app.schemas import InstrumentInput, MarketDataSyncRequest
from backend.app.services.market_data import init_database, sync_market_data


class ApiTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        database_url = f"sqlite+pysqlite:///{self.temp_dir.name}/test.db"
        self.app = create_app(database_url=database_url, seed_demo=False)
        init_database(self.app.state.engine)
        self.client = TestClient(self.app)

        session = self.app.state.session_factory()
        try:
            sync_market_data(
                session,
                MarketDataSyncRequest(
                    symbols=[
                        InstrumentInput(symbol="AAA", name="AAA", market="CN", asset_type="INDEX"),
                        InstrumentInput(symbol="BBB", name="BBB", market="CN", asset_type="INDEX"),
                    ],
                    source="demo",
                    start_date=date(2022, 1, 1),
                    end_date=date(2026, 3, 20),
                ),
            )
        finally:
            session.close()

    def tearDown(self) -> None:
        self.client.close()
        self.app.state.engine.dispose()
        self.temp_dir.cleanup()

    def seed_index_instrument(self, symbol: str, name: str) -> None:
        session = self.app.state.session_factory()
        try:
            session.add(Instrument(symbol=symbol, name=name, market="CN", asset_type="INDEX", source="manual"))
            session.commit()
        finally:
            session.close()

    def test_same_symbol_returns_400(self) -> None:
        response = self.client.get("/api/style-rotation", params={"left_symbol": "AAA", "right_symbol": "AAA"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], 400)

    def test_instruments_endpoint(self) -> None:
        response = self.client.get("/api/instruments")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["data"]["items"]), 2)

    @patch("backend.app.services.market_data.ak.stock_zh_a_hist_tx")
    def test_sync_endpoint_uses_akshare_tencent_for_index(self, mock_tx_hist) -> None:
        mock_tx_hist.return_value = pd.DataFrame(
            [
                {
                    "date": "2024-01-02",
                    "open": 10.0,
                    "close": 10.2,
                    "high": 10.3,
                    "low": 9.9,
                    "amount": 10200,
                },
                {
                    "date": "2024-01-03",
                    "open": 10.2,
                    "close": 10.5,
                    "high": 10.6,
                    "low": 10.1,
                    "amount": 12600,
                },
            ]
        )

        response = self.client.post(
            "/api/market-data/sync",
            json={
                "symbols": [{"symbol": "399376", "name": "国证小盘成长", "market": "CN", "asset_type": "INDEX"}],
                "source": "tencent",
                "start_date": "2024-01-02",
                "end_date": "2024-01-03",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["code"], 200)
        mock_tx_hist.assert_called_once()

        session = self.app.state.session_factory()
        try:
            prices = session.scalars(
                select(DailyPrice).where(DailyPrice.symbol == "399376").order_by(DailyPrice.trade_date.asc())
            ).all()
            self.assertEqual(len(prices), 2)
            self.assertEqual(float(prices[0].close), 10.2)
            self.assertEqual(prices[0].source, "tencent")
        finally:
            session.close()

    @patch("backend.app.services.market_data.ak.stock_zh_a_hist_tx")
    def test_sync_clears_existing_rows_only_within_selected_range(self, mock_index_hist) -> None:
        mock_index_hist.return_value = pd.DataFrame(
            [
                {
                    "date": "2024-01-02",
                    "open": 20.0,
                    "close": 20.2,
                    "high": 20.3,
                    "low": 19.9,
                    "amount": 40400,
                },
                {
                    "date": "2024-01-03",
                    "open": 20.2,
                    "close": 20.4,
                    "high": 20.5,
                    "low": 20.1,
                    "amount": 42840,
                },
            ]
        )

        session = self.app.state.session_factory()
        try:
            sync_market_data(
                session,
                MarketDataSyncRequest(
                    symbols=[InstrumentInput(symbol="399376", name="旧指数", market="CN", asset_type="INDEX")],
                    source="demo",
                    start_date=date(2024, 1, 1),
                    end_date=date(2024, 1, 5),
                ),
            )
        finally:
            session.close()

        response = self.client.post(
            "/api/market-data/sync",
            json={
                "symbols": [{"symbol": "399376", "name": "新指数", "market": "CN", "asset_type": "INDEX"}],
                "source": "tencent",
                "start_date": "2024-01-02",
                "end_date": "2024-01-03",
            },
        )

        self.assertEqual(response.status_code, 200)

        session = self.app.state.session_factory()
        try:
            prices = session.scalars(
                select(DailyPrice).where(DailyPrice.symbol == "399376").order_by(DailyPrice.trade_date.asc())
            ).all()
            self.assertGreater(len(prices), 2)

            by_date = {price.trade_date.isoformat(): price for price in prices}
            self.assertEqual(float(by_date["2024-01-02"].close), 20.2)
            self.assertEqual(float(by_date["2024-01-03"].close), 20.4)
            self.assertEqual(by_date["2024-01-02"].source, "tencent")
            self.assertEqual(by_date["2024-01-01"].source, "demo")
        finally:
            session.close()

    @patch("backend.app.services.market_data.ak.stock_zh_a_hist_tx")
    def test_sync_endpoint_returns_502_on_upstream_failure(self, mock_tx_hist) -> None:
        mock_tx_hist.side_effect = RuntimeError("upstream down")

        response = self.client.post(
            "/api/market-data/sync",
            json={
                "symbols": [{"symbol": "399376", "name": "国证小盘成长", "market": "CN", "asset_type": "INDEX"}],
                "source": "tencent",
                "start_date": "2024-01-02",
                "end_date": "2024-01-03",
            },
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["code"], 502)

    def test_sync_endpoint_rejects_eastmoney_source(self) -> None:
        response = self.client.post(
            "/api/market-data/sync",
            json={
                "symbols": [{"symbol": "399376", "name": "国证小盘成长", "market": "CN", "asset_type": "INDEX"}],
                "source": "eastmoney",
                "start_date": "2024-01-02",
                "end_date": "2024-01-03",
            },
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["code"], 502)
        self.assertIn("disabled", response.json()["message"])

    def test_upload_valuation_csv_for_pe(self) -> None:
        self.seed_index_instrument("000922", "中证红利")

        csv_content = """日期,收盘点位,全收益收盘点位(元),市值(元),流通市值(元),自由流通市值(元),PE-TTM市值加权,PE-TTM 分位点,PE-TTM 80%分位点值,PE-TTM 50%分位点值,PE-TTM 20%分位点值
2026-03-20,=5772.6500,=12121.5800,=24146985436231.3125,=15938202596389,=5176079006417.8994,=8.7460,=0.8390,=8.5650,=7.6592,=6.0261
2026-03-19,=5799.1900,=12177.3200,=24288465659526.4648,=16050799474511,=5202452064512.2373,=8.7745,=0.8434,=8.5650,=7.6580,=6.0245
"""

        response = self.client.post(
            "/api/valuations/upload",
            data={"symbol": "000922", "metric_type": "pe"},
            files={"file": ("中证红利_PE.csv", csv_content.encode("utf-8"), "text/csv")},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["code"], 200)
        self.assertEqual(response.json()["data"]["row_count"], 2)

        session = self.app.state.session_factory()
        try:
            valuations = session.scalars(
                select(IndexValuation).where(IndexValuation.symbol == "000922").order_by(IndexValuation.trade_date.desc())
            ).all()
            self.assertEqual(len(valuations), 2)
            self.assertEqual(float(valuations[0].pe_ttm), 8.746)
            self.assertEqual(float(valuations[0].pe_percentile), 0.839)
        finally:
            session.close()

    def test_upload_valuation_csv_rejects_wrong_shape(self) -> None:
        self.seed_index_instrument("000922", "中证红利")

        csv_content = "日期,收盘点位\n2026-03-20,=5772.6500\n"

        response = self.client.post(
            "/api/valuations/upload",
            data={"symbol": "000922", "metric_type": "pb"},
            files={"file": ("bad.csv", csv_content.encode("utf-8"), "text/csv")},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], 400)

    def test_upload_valuation_csv_replaces_old_metric_rows_for_same_symbol(self) -> None:
        self.seed_index_instrument("000922", "中证红利")

        first_csv = """日期,收盘点位,全收益收盘点位(元),市值(元),流通市值(元),自由流通市值(元),PE-TTM市值加权,PE-TTM 分位点,PE-TTM 80%分位点值,PE-TTM 50%分位点值,PE-TTM 20%分位点值
2026-03-20,=5772.6500,=12121.5800,=24146985436231.3125,=15938202596389,=5176079006417.8994,=8.7460,=0.8390,=8.5650,=7.6592,=6.0261
2026-03-19,=5799.1900,=12177.3200,=24288465659526.4648,=16050799474511,=5202452064512.2373,=8.7745,=0.8434,=8.5650,=7.6580,=6.0245
"""
        second_csv = """日期,收盘点位,全收益收盘点位(元),市值(元),流通市值(元),自由流通市值(元),PE-TTM市值加权,PE-TTM 分位点,PE-TTM 80%分位点值,PE-TTM 50%分位点值,PE-TTM 20%分位点值
2026-03-20,=5772.6500,=12121.5800,=24146985436231.3125,=15938202596389,=5176079006417.8994,=9.1000,=0.9000,=8.8000,=7.7000,=6.1000
"""

        first_response = self.client.post(
            "/api/valuations/upload",
            data={"symbol": "000922", "metric_type": "pe"},
            files={"file": ("first.csv", first_csv.encode("utf-8"), "text/csv")},
        )
        self.assertEqual(first_response.status_code, 200)

        second_response = self.client.post(
            "/api/valuations/upload",
            data={"symbol": "000922", "metric_type": "pe"},
            files={"file": ("second.csv", second_csv.encode("utf-8"), "text/csv")},
        )
        self.assertEqual(second_response.status_code, 200)

        session = self.app.state.session_factory()
        try:
            valuations = session.scalars(
                select(IndexValuation).where(IndexValuation.symbol == "000922").order_by(IndexValuation.trade_date.desc())
            ).all()
            self.assertEqual(len(valuations), 1)
            self.assertEqual(valuations[0].trade_date.isoformat(), "2026-03-20")
            self.assertEqual(float(valuations[0].pe_ttm), 9.1)
            self.assertEqual(valuations[0].source_file, "second.csv")
        finally:
            session.close()

    def test_upload_valuation_csv_rejects_filename_symbol_mismatch(self) -> None:
        self.seed_index_instrument("399376", "国证小盘成长")
        self.seed_index_instrument("000922", "中证红利")

        csv_content = """日期,收盘点位,全收益收盘点位(元),市值(元),流通市值(元),自由流通市值(元),PE-TTM市值加权,PE-TTM 分位点,PE-TTM 80%分位点值,PE-TTM 50%分位点值,PE-TTM 20%分位点值
2026-03-20,=5772.6500,=12121.5800,=24146985436231.3125,=15938202596389,=5176079006417.8994,=8.7460,=0.8390,=8.5650,=7.6592,=6.0261
"""

        response = self.client.post(
            "/api/valuations/upload",
            data={"symbol": "399376", "metric_type": "pe"},
            files={"file": ("中证红利_PE.csv", csv_content.encode("utf-8"), "text/csv")},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], 400)
        self.assertIn("selected symbol is 399376", response.json()["message"])


if __name__ == "__main__":
    unittest.main()
