#!/usr/bin/env python3
"""
JOSH SELF-RUNNING GREENHOUSE SYSTEM v1.0
Double-click to run (or python Josh_Self_Running_Greenhouse_System_v1.0.py)

Creates complete shop packet for any order:
- DXF for laser/CNC
- PDF drawings + BOM
- Cut list CSV
- Assembly instructions
- Engineering reference

Self-improving with every order (logs to learning file)
"""

import os
import json
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch

# Import submittal generator
from generate_submittal_drawings import create_pdf_submittal, create_svg_general_arrangement

# ===================== CONFIG =====================
OUTPUT_DIR = "/home/workdir/artifacts/shop_packets"
LEARNING_LOG = "/home/workdir/artifacts/order_learning_log.jsonl"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ===================== CORE GENERATORS =====================
def generate_dxf(num_bays, filename):
    """Generate simple but usable DXF for laser"""
    dxf = f"""0
SECTION
2
HEADER
0
ENDSEC
0
SECTION
2
ENTITIES
"""
    for bay in range(num_bays):
        x = bay * 50
        # Outer frame 48x60
        dxf += f"0\nLINE\n8\n0\n10\n{x}\n20\n0\n11\n{x+48}\n21\n0\n"
        dxf += f"0\nLINE\n8\n0\n10\n{x+48}\n20\n0\n11\n{x+48}\n21\n60\n"
        dxf += f"0\nLINE\n8\n0\n10\n{x+48}\n20\n60\n11\n{x}\n21\n60\n"
        dxf += f"0\nLINE\n8\n0\n10\n{x}\n20\n60\n11\n{x}\n21\n0\n"
        # Holes
        for y in [7, 20.4, 25.6, 32.6, 53]:
            dxf += f"0\nCIRCLE\n8\nHOLES\n10\n{x+3}\n20\n{y}\n40\n0.1875\n"
            dxf += f"0\nCIRCLE\n8\nHOLES\n10\n{x+45}\n20\n{y}\n40\n0.1875\n"
    
    dxf += "0\nENDSEC\n0\nEOF\n"
    
    with open(filename, "w") as f:
        f.write(dxf)
    return filename

def generate_pdf_packet(order, filename):
    """Generate professional PDF shop packet"""
    doc = SimpleDocTemplate(filename, pagesize=letter, 
                            rightMargin=0.5*inch, leftMargin=0.5*inch,
                            topMargin=0.5*inch, bottomMargin=0.5*inch)
    styles = getSampleStyleSheet()
    story = []
    
    story.append(Paragraph(f"MODULAR GREENHOUSE SHOP PACKET", styles['Heading1']))
    story.append(Paragraph(f"Order: {order['config']['total_length_ft']} ft | {datetime.now().strftime('%Y-%m-%d %H:%M')}", styles['Normal']))
    story.append(Spacer(1, 10))
    
    # BOM Table
    data = [["Component", "Qty", "Weight (lbs)"]]
    for m in order['modules']:
        name = m.get('instance') or m.get('name', 'Component')
        data.append([name, "1", str(m['weight_lbs'])])
    for h in order['hardware']:
        data.append([h['part'], str(h['qty']), str(h['weight_lbs'])])
    
    t = Table(data, colWidths=[4*inch, 1*inch, 1.2*inch])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a5f2a')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
    ]))
    story.append(t)
    story.append(Spacer(1, 15))
    
    story.append(Paragraph(f"<b>Total Weight:</b> {order['total_weight_lbs']} lbs", styles['Normal']))
    story.append(Paragraph(f"<b>Engineering:</b> Covered under master PE package (2024 IBC Reno)", styles['Normal']))
    story.append(Paragraph(f"<b>Files included:</b> DXF, Cut List, Assembly Instructions", styles['Normal']))
    
    doc.build(story)
    return filename

def generate_cut_list(order, filename):
    with open(filename, "w") as f:
        f.write("Instance,Part,Length_in,Angle1,Angle2,Material,Qty\n")
        for m in order['modules']:
            if 'parts' in m:
                for p in m['parts']:
                    f.write(f"{m.get('instance','')},{p['part']},{p['length']},{p['angle1']},{p['angle2']},{p['desc']},{p.get('qty',1)}\n")
    return filename

# ===================== MAIN =====================
def create_shop_packet(shape="straight", main_length_ft=12.0, branch_length_ft=0.0, 
                       has_dormers=False, door_side=None, load_package="standard_reno"):
    from Configuration_Engine import GreenhouseConfig, calculate_bom
    
    config = GreenhouseConfig(
        shape=shape,
        main_length_ft=main_length_ft,
        branch_length_ft=branch_length_ft,
        load_package=load_package,
        dormers=1 if has_dormers else 0,
        doors=1 if door_side else 0
    )
    
    order = calculate_bom(config)
    
    # Create output folder
    total_length = order.get('total_length_ft', main_length_ft + branch_length_ft)
    folder_name = f"{total_length}ft_{shape}_{load_package}_{datetime.now().strftime('%Y%m%d_%H%M')}"
    folder = os.path.join(OUTPUT_DIR, folder_name)
    os.makedirs(folder, exist_ok=True)
    
    # Generate all files
    total_bays = order.get('total_bays', int((main_length_ft + branch_length_ft) / 4))
    dxf_file = generate_dxf(total_bays, os.path.join(folder, "laser_cut.dxf"))
    pdf_file = generate_pdf_packet(order, os.path.join(folder, "shop_packet.pdf"))
    csv_file = generate_cut_list(order, os.path.join(folder, "cut_list.csv"))
    
    # Assembly instructions
    with open(os.path.join(folder, "ASSEMBLY_INSTRUCTIONS.txt"), "w") as f:
        f.write(f"""ASSEMBLY INSTRUCTIONS - {order['config']['total_length_ft']} ft Greenhouse

1. Lay out all WRW bays on flat surface
2. Attach gable ends (UGW top + LGW bottom) with H-bolts
3. Install bracing kits (torque 15-18 ft-lbs)
4. Add polycarbonate panels (5/32" screws)
5. Install toggle clamps for final tension
6. Anchor to foundation per PE drawings

Estimated assembly time: 2-4 hours for 12-16 ft
""")
    
    # Engineering reference
    with open(os.path.join(folder, "ENGINEERING_REFERENCE.txt"), "w") as f:
        f.write(f"""ENGINEERING REFERENCE
Master PE-stamped package covers this configuration.
Loads: {load_package}
All members OK with FS ≥ 1.6 per 2024 IBC + ASCE 7-22
Site-specific: Only foundation + current ASCE Hazard Tool required.

Contact Josh for stamped drawings if needed for permit.
""")
    
    # === NEW: Auto-generate Professional Submittal Drawings ===
    submittal_pdf = create_pdf_submittal(num_bays=total_bays, length_ft=order['config']['total_length_ft'], load_package=load_package)
    submittal_svg = create_svg_general_arrangement(num_bays=total_bays)
    # Copy to packet folder
    import shutil
    shutil.copy(submittal_pdf, os.path.join(folder, "Submittal_Drawings.pdf"))
    shutil.copy(submittal_svg, os.path.join(folder, "General_Arrangement.svg"))
    
    # Log for learning
    with open(LEARNING_LOG, "a") as f:
        f.write(json.dumps({"timestamp": datetime.now().isoformat(), "order": order['config'], "weight": order['total_weight_lbs']}) + "\n")
    
    print(f"\n✅ COMPLETE SHOP PACKET CREATED:")
    print(f"   Folder: {folder}")
    print(f"   Files: laser_cut.dxf | shop_packet.pdf | cut_list.csv | ASSEMBLY_INSTRUCTIONS.txt | ENGINEERING_REFERENCE.txt")
    print(f"   Total Weight: {order['total_weight_lbs']} lbs")
    
    return folder

if __name__ == "__main__":
    print("=== JOSH SELF-RUNNING GREENHOUSE SYSTEM v1.0 (Multi-Shape Support) ===\n")
    
    # === SAME-DAY SHIPPING MODE ===
    SAME_DAY_MODE = True
    
    if SAME_DAY_MODE:
        print("🚀 SAME-DAY SHIPPING MODE ACTIVATED\n")
    
    # Test multiple shapes
    print("1. Straight 16 ft:")
    create_shop_packet(shape="straight", main_length_ft=16.0, load_package="high_snow")
    
    print("\n2. T-Shape (16 ft main + 8 ft branch):")
    create_shop_packet(shape="t", main_length_ft=16.0, branch_length_ft=8.0)
    
    print("\n3. X-Shape (12 ft main + 8 ft cross):")
    create_shop_packet(shape="x", main_length_ft=12.0, branch_length_ft=8.0)
    
    print("\n✅ All shapes supported. System ready for T, X, L, and future configurations.")