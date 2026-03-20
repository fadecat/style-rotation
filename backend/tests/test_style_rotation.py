from __future__ import annotations

import unittest

import pandas as pd

from backend.app.services.style_rotation import StyleRotationParams, calculate_style_rotation


class StyleRotationGoldenTest(unittest.TestCase):
    def test_matches_golden_sample(self) -> None:
        df_left = pd.DataFrame(
            [
                {"trade_date": "2024-01-02", "close": 100.00000},
                {"trade_date": "2024-01-03", "close": 101.00000},
                {"trade_date": "2024-01-04", "close": 106.05000},
                {"trade_date": "2024-01-05", "close": 106.05000},
                {"trade_date": "2024-01-08", "close": 101.80800},
                {"trade_date": "2024-01-09", "close": 103.84416},
            ]
        )
        df_right = pd.DataFrame(
            [
                {"trade_date": "2024-01-02", "close": 100.00000},
                {"trade_date": "2024-01-03", "close": 100.00000},
                {"trade_date": "2024-01-04", "close": 100.00000},
                {"trade_date": "2024-01-05", "close": 100.00000},
                {"trade_date": "2024-01-08", "close": 100.00000},
                {"trade_date": "2024-01-09", "close": 100.00000},
            ]
        )
        params = StyleRotationParams(
            left_symbol="AAA",
            right_symbol="BBB",
            start_date="2024-01-04",
            end_date="2024-01-09",
            return_window=1,
            ma_window=2,
            quantile_window_min=2,
        )

        result = calculate_style_rotation(df_left, df_right, params)

        self.assertEqual(result["dates"], ["2024-01-04", "2024-01-05", "2024-01-08", "2024-01-09"])
        self.assertEqual(result["left_close"], [106.05, 106.05, 101.808, 103.8442])
        self.assertEqual(result["right_close"], [100.0, 100.0, 100.0, 100.0])
        self.assertEqual(result["left_return"], [5.0, 0.0, -4.0, 2.0])
        self.assertEqual(result["right_return"], [0.0, 0.0, 0.0, 0.0])
        self.assertEqual(result["spread"], [5.0, 0.0, -4.0, 2.0])
        self.assertEqual(result["ma"], [3.0, 2.5, -2.0, -1.0])
        self.assertEqual(result["p90_dynamic"], [4.6, 4.2, 3.8, 3.8])
        self.assertEqual(result["p10_dynamic"], [1.4, 0.2, -2.8, -2.4])
        self.assertEqual(result["left_nav"], [1.0, 1.0, 0.96, 0.9792])
        self.assertEqual(result["right_nav"], [1.0, 1.0, 1.0, 1.0])
        self.assertEqual(
            result["signals"],
            [
                {"date": "2024-01-05", "type": "sell", "spread": 0.0},
                {"date": "2024-01-09", "type": "buy", "spread": 2.0},
            ],
        )
        self.assertEqual(result["global_p90"], 3.8)
        self.assertEqual(result["global_p10"], -2.4)
        self.assertEqual(result["latest_signal"], "buy")


if __name__ == "__main__":
    unittest.main()

