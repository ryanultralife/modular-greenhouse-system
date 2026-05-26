#!/usr/bin/env python3
"""
DAILY PRODUCTION PLANNER v1.0
For Josh – Modular Greenhouses

Run this every morning to get today's prioritized build list.
"""

import json
from datetime import datetime

# Simulated current stock (in real use this would read from a file or database)
CURRENT_STOCK = {
    "Gable_Sets": 5,
    "WRW_Bays": 18,
    "WRUB": 12,
    "WRKB": 14,
    "Reinforced_Side": 9,
    "Dormer_Kits": 2,
    "Toggle_Clamps": 87,
    "H_Bolts": 312
}

# Incoming orders today (simulated)
TODAY_ORDERS = [
    {"id": "ORD-1042", "type": "16ft_Standard", "qty": 1, "same_day": True},
    {"id": "ORD-1043", "type": "12ft_RaisedBed", "qty": 1, "same_day": False},
    {"id": "ORD-1044", "type": "20ft_HighSnow", "qty": 1, "same_day": False},
]

def generate_daily_plan():
    print("=" * 60)
    print(f"DAILY PRODUCTION PLAN – {datetime.now().strftime('%A, %B %d, %Y')}")
    print("=" * 60)

    plan = []
    same_day = [o for o in TODAY_ORDERS if o["same_day"]]
    build_to_order = [o for o in TODAY_ORDERS if not o["same_day"]]

    # Priority 1: Same-day ship orders
    if same_day:
        print("\n🚨 SAME-DAY SHIP ORDERS (Highest Priority)")
        for order in same_day:
            print(f"   • {order['id']} – {order['type']} (Pull from stock)")

    # Priority 2: Replenish low stock
    print("\n📦 REPLENISH STOCK (Focus Today)")
    if CURRENT_STOCK["Gable_Sets"] < 6:
        plan.append("Build 4 Gable End Sets (UGW + LGW)")
    if CURRENT_STOCK["WRW_Bays"] < 15:
        plan.append("Build 10 WRW Core Bays")
    if CURRENT_STOCK["Dormer_Kits"] < 3:
        plan.append("Build 3 Dormer Kits")
    if CURRENT_STOCK["WRUB"] < 10 or CURRENT_STOCK["WRKB"] < 10:
        plan.append("Build 15 WRUB + 15 WRKB + 10 Reinforced Side Braces")

    for item in plan:
        print(f"   • {item}")

    # Priority 3: Build-to-order
    if build_to_order:
        print("\n🔨 BUILD-TO-ORDER (Add to Queue)")
        for order in build_to_order:
            print(f"   • {order['id']} – {order['type']}")

    print("\n" + "=" * 60)
    print("RECOMMENDED 8-HOUR FOCUS: Gable Ends + WRW Bays")
    print("=" * 60)

if __name__ == "__main__":
    generate_daily_plan()