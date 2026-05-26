#!/usr/bin/env python3
"""
INVENTORY TRACKER + LOW-STOCK ALERTS v1.0
For Josh – Modular Greenhouses
"""

import json
from datetime import datetime

# This would normally read from a real inventory system
INVENTORY = {
    "Gable_Sets": {"current": 5, "min": 6, "max": 10},
    "WRW_Bays": {"current": 18, "min": 15, "max": 30},
    "WRUB": {"current": 12, "min": 10, "max": 25},
    "WRKB": {"current": 14, "min": 10, "max": 25},
    "Reinforced_Side": {"current": 9, "min": 10, "max": 20},
    "Dormer_Kits": {"current": 2, "min": 3, "max": 8},
    "Toggle_Clamps": {"current": 87, "min": 100, "max": 300},
    "H_Bolts": {"current": 312, "min": 400, "max": 1000}
}

def check_inventory():
    print("=" * 55)
    print("INVENTORY STATUS & ALERTS")
    print("=" * 55)
    print(f"Checked: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")

    alerts = []
    for item, data in INVENTORY.items():
        status = "✅ OK"
        if data["current"] < data["min"]:
            status = "🔴 LOW STOCK"
            alerts.append(item)
        print(f"{item:20} | {data['current']:3} / {data['min']:3} | {status}")

    if alerts:
        print("\n" + "=" * 55)
        print("⚠️  ACTION REQUIRED – LOW STOCK ITEMS:")
        for item in alerts:
            print(f"   → Reorder or build: {item}")
    else:
        print("\n✅ All items above minimum stock levels.")

if __name__ == "__main__":
    check_inventory()