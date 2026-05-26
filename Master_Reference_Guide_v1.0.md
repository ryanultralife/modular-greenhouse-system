# MASTER REFERENCE GUIDE v1.0
## Complete Calculations, BOMs, Inventory, Production & Installation
**Josh – Modular Greenhouses | Reno, Nevada | May 2026**

---

## 1. COMPONENT CALCULATIONS & SPECIFICATIONS

### 1.1 WRW Core Bay (Wall-Roof Weldment)
- **Material**: 6061-T6, 1" sq × .065" wall
- **Dimensions**: 48.03125" wide × 60.03125" tall
- **Weight**: 12.5 lbs
- **Holes**: 17× 9/64" + multiple 3/8" (exact locations per drawing)
- **Load Capacity** (per bay, High Snow):
  - Roof Snow: 24 psf → 1,150 lb horizontal thrust
  - Wind Uplift: 920 lb per connection
- **Bracing Required**: 1 set per 2 bays minimum

### 1.2 Braces
| Brace Type       | Length    | Angle   | Weight | Primary Load          | Capacity     |
|------------------|-----------|---------|--------|-----------------------|--------------|
| WRUB             | 52.56"    | 51.5°   | 1.8 lb | Roof thrust (tension) | > 4,200 lb   |
| WRKB             | 14.38"    | 64.5°   | 0.6 lb | Knee brace (compression) | > 3,800 lb |
| Reinforced Side  | Multi     | 39°/42° | 3.4 lb | Lateral stability     | > 5,100 lb   |

**Bracing Rule**:
- Straight: 1 set per 2 bays (min 2)
- T/X/L: 1.5 sets per 2 bays (min 3–4)

### 1.3 Gable Sets (UGW + LGW)
- **Upper Gable (UGW)**: 61.97" sloped @ 39°/51°, 9.8 lbs
- **Lower Gable (LGW)**: 60" verticals, 22.25" horizontals, 11.2 lbs
- **Combined Weight**: 21 lbs per set
- **Holes**: Factory drilled for PC + hinges
- **T-Shape Requirement**: 3 sets total
- **X-Shape Requirement**: 4 sets total

### 1.4 Dormer Kit
- **Weight**: 18 lbs complete
- **Includes**: Valley, peak, hinges, extra PC
- **Mounting**: Bolts to WRW roof slope
- **Recommended**: Max 2 per 16–20 ft greenhouse

### 1.5 Junction Pieces (New for Branched Shapes)
- **Tee Junction**: 1 piece, ~8–10 lbs, heavily reinforced
- **Cross Junction**: 1 piece, ~12–14 lbs, extra bracing points
- **L Junction**: 1 piece, ~7–9 lbs

---

## 2. COMPLETE CONFIGURATION BOMS

### 2.1 Straight 16 ft (High Snow)
- WRW Bays: 4
- Gable Sets: 2
- Bracing Sets: 4
- Dormers: 0–2 (optional)
- Toggle Clamps: 40
- H-Bolts: 176
- **Total Weight: 165.7 lbs**

### 2.2 T-Shape 16 ft Main + 8 ft Branch (High Snow)
- WRW Bays: 6
- Gable Sets: 3
- Tee Junction: 1
- Bracing Sets: 5
- Dormers: 0–2
- Toggle Clamps: 60
- H-Bolts: 264
- **Total Weight: ~198 lbs**

### 2.3 X-Shape 12 ft Main + 8 ft Cross (Standard)
- WRW Bays: 5
- Gable Sets: 4
- Cross Junction: 1
- Bracing Sets: 4
- Dormers: 0–1
- Toggle Clamps: 50
- H-Bolts: 220
- **Total Weight: ~165 lbs**

---

## 3. INVENTORY MINIMUMS (Smart Stock)

| Item                    | Min Stock | Reorder Point | Notes |
|-------------------------|-----------|---------------|-------|
| Gable Sets              | 6         | 4             | Critical – longest lead time |
| WRW Bays                | 20        | 12            | Core repeatable unit |
| WRUB / WRKB / Side Brace| 15 each   | 10            | Small & fast to make |
| Tee Junctions           | 3         | 2             | For T-shape orders |
| Cross Junctions         | 2         | 1             | For X-shape orders |
| Dormer Kits             | 4         | 2             | Popular upgrade |
| Toggle Clamps           | 150       | 100           | High usage |
| H-Bolts + Washers       | 500       | 300           | Buy in bulk |

---

## 4. PRODUCTION SCHEDULING (8-Hour Blocks)

| Day       | Focus                     | Output Goal                  |
|-----------|---------------------------|------------------------------|
| Monday    | WRW Bays                  | 10–12 bays                   |
| Tuesday   | Gable Sets + Junctions    | 4–6 gables + 2–3 junctions   |
| Wednesday | Braces + Dormers          | 20 braces + 3 dormers        |
| Thursday  | Hardware Kitting + PC Cut | Full kits + panels           |
| Friday    | Final Assembly + Shipping | Same-day ship orders         |

---

## 5. INSTALLATION REFERENCES (Quick Guide)

**Standard Straight Greenhouse**:
1. Lay out gable ends
2. Insert WRW bays between gables
3. Install bracing (torque 15–18 ft-lbs)
4. Add polycarbonate
5. Install toggle clamps last

**T-Shape Specific**:
1. Build main body first (like straight)
2. Attach tee junction at chosen bay
3. Build branch outward from junction
4. Add extra bracing at tee
5. Install final gable on branch end

**Critical Notes**:
- All H-bolts: 15–18 ft-lbs
- PC screws: 5/32" at 13.5" spacing
- Anchor: Minimum 4× 3/8" epoxy anchors per gable

---

## 6. REFERENCES & FILES

- Full Engineering Manual v2.1 → `Engineering_Manual_v2.1_MultiShape.md`
- Configuration Engine → `Configuration_Engine.py`
- Self-Running System → `Josh_Self_Running_Greenhouse_System_v1.0.py`
- Submittal Drawings → `/submittal_drawings/`
- Daily Production Planner → `Daily_Production_Planner.py`
- Inventory Tracker → `Inventory_Tracker.py`

---

**This Master Reference Guide ties together every component, calculation, inventory rule, production schedule, and installation step for all shapes and options Josh offers.**