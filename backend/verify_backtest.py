"""Verify backtest correctness per spec."""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from app.database import create_session_factory
from app.config import get_settings
from app.services.style_rotation import BacktestParams, run_backtest

settings = get_settings()
engine, session_factory = create_session_factory(settings.database_url)

params = BacktestParams(
    left_symbol="000852",
    right_symbol="000922",
    start_date="2016-01-01",
    end_date="2026-03-20",
    return_window=252,
)

with session_factory() as session:
    # Step 1: check raw prices
    from app.services.style_rotation import _load_price_frame
    from datetime import date
    df_l = _load_price_frame(session, "000852", date(2016, 1, 1), date(2026, 3, 20))
    df_r = _load_price_frame(session, "000922", date(2016, 1, 1), date(2026, 3, 20))

    print("=== Step 1: Raw prices ===")
    print(f"000852 rows: {len(df_l)}")
    if len(df_l) > 0:
        print("First 5:")
        print(df_l.head(5).to_string(index=False))
        print("Last 5:")
        print(df_l.tail(5).to_string(index=False))
    else:
        print("NO DATA for 000852!")

    print()
    print(f"000922 rows: {len(df_r)}")
    if len(df_r) > 0:
        print("First 5:")
        print(df_r.head(5).to_string(index=False))
        print("Last 5:")
        print(df_r.tail(5).to_string(index=False))
    else:
        print("NO DATA for 000922!")

    if len(df_l) == 0 or len(df_r) == 0:
        print("\nMissing data. Cannot proceed.")
        sys.exit(1)

    # Step 2: baselines
    result = run_backtest(session, params)
    stats = result["stats"]
    print("\n=== Step 2: Baseline NAVs ===")
    print(f"left_nav[-1]  (000852): {stats['left_nav_final']}")
    print(f"right_nav[-1] (000922): {stats['right_nav_final']}")

    left_ok = 0.5 < stats["left_nav_final"] < 1.2
    right_ok = 1.0 < stats["right_nav_final"] < 2.0
    if not left_ok:
        print(f"WARNING: left_nav_final={stats['left_nav_final']} outside expected ~0.80 range")
    if not right_ok:
        print(f"WARNING: right_nav_final={stats['right_nav_final']} outside expected ~1.40 range")

    # Step 3: full results
    print("\n=== Step 3: Stats ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")

    print(f"\n=== Trades ({len(result['trades'])}) ===")
    for t in result["trades"]:
        print(f"  {t['date']}  {t['action']:4s}  nav_before={t['nav_before']}  nav_after={t['nav_after']}")

    # Verify alternation
    actions = [t["action"] for t in result["trades"]]
    print(f"\nFirst trade action: {actions[0] if actions else 'NONE'}")
    alternation_ok = True
    for i in range(1, len(actions)):
        if actions[i] == actions[i - 1]:
            print(f"ERROR: consecutive same action at index {i}: {actions[i]}")
            alternation_ok = False
    if alternation_ok and actions:
        print("Alternation check: PASS (buy/sell strictly alternate)")
    if actions and actions[0] != "buy":
        print(f"ERROR: first trade is '{actions[0]}', expected 'buy'")
    else:
        print("First-trade check: PASS (first is buy)")
