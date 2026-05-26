#!/usr/bin/env python3
"""
CONFIGURATION ENGINE v1.0
Supports: Straight, T-Shape, X-Shape, L-Shape, and future layouts
For Josh – Modular Greenhouses
"""

from dataclasses import dataclass
from typing import List, Dict

@dataclass
class GreenhouseConfig:
    shape: str          # "straight", "t", "x", "l"
    main_length_ft: float
    branch_length_ft: float = 0.0   # for T/X/L
    load_package: str = "standard_reno"
    dormers: int = 0
    doors: int = 0

def calculate_bom(config: GreenhouseConfig) -> Dict:
    """Calculate complete BOM based on shape and size"""
    
    bom = {
        "shape": config.shape,
        "main_length_ft": config.main_length_ft,
        "total_bays": int(config.main_length_ft / 4),
        "parts": {},
        "weight_lbs": 0
    }
    
    # Base parts for main body
    main_bays = int(config.main_length_ft / 4)
    bom["parts"]["WRW_Bays"] = main_bays
    bom["parts"]["Gable_Sets"] = 2          # Always 2 for main body
    
    # Shape-specific logic
    if config.shape == "straight":
        bom["parts"]["Bracing_Sets"] = max(2, (main_bays + 1) // 2)
        bom["total_bays"] = main_bays
        
    elif config.shape == "t":
        branch_bays = int(config.branch_length_ft / 4)
        bom["parts"]["WRW_Bays"] += branch_bays
        bom["parts"]["Gable_Sets"] += 1      # Extra gable for tee end
        bom["parts"]["Tee_Junction_Pieces"] = 1
        bom["parts"]["Bracing_Sets"] = max(3, (main_bays + branch_bays + 2) // 2)
        bom["total_bays"] = main_bays + branch_bays
        
    elif config.shape == "x":
        branch_bays = int(config.branch_length_ft / 4)
        bom["parts"]["WRW_Bays"] += branch_bays * 2   # Two branches
        bom["parts"]["Gable_Sets"] += 2
        bom["parts"]["Cross_Junction_Pieces"] = 1
        bom["parts"]["Bracing_Sets"] = max(4, (main_bays + branch_bays * 2 + 3) // 2)
        bom["total_bays"] = main_bays + branch_bays * 2
        
    elif config.shape == "l":
        branch_bays = int(config.branch_length_ft / 4)
        bom["parts"]["WRW_Bays"] += branch_bays
        bom["parts"]["Gable_Sets"] += 1
        bom["parts"]["L_Junction_Pieces"] = 1
        bom["parts"]["Bracing_Sets"] = max(3, (main_bays + branch_bays + 2) // 2)
        bom["total_bays"] = main_bays + branch_bays
    
    # Hardware (scales with total bays)
    total_bays = bom["total_bays"]
    bom["parts"]["Toggle_Clamps"] = 10 * total_bays
    bom["parts"]["H_Bolts"] = 44 * total_bays
    
    # Weight estimate
    bom["weight_lbs"] = (
        total_bays * 12.5 +                    # WRW
        bom["parts"]["Gable_Sets"] * 21 +      # Gables
        bom["parts"]["Bracing_Sets"] * 5.8 +   # Braces
        (config.dormers * 18) +
        (config.doors * 12)
    )
    
    return bom

# Example usage
if __name__ == "__main__":
    print("=== CONFIGURATION ENGINE TEST ===\n")
    
    # Straight 16 ft
    straight = GreenhouseConfig(shape="straight", main_length_ft=16)
    print("Straight 16 ft:", calculate_bom(straight))
    
    # T-Shape: 16 ft main + 8 ft branch
    t_shape = GreenhouseConfig(shape="t", main_length_ft=16, branch_length_ft=8)
    print("\nT-Shape 16+8 ft:", calculate_bom(t_shape))
    
    # X-Shape: 12 ft main + 8 ft cross
    x_shape = GreenhouseConfig(shape="x", main_length_ft=12, branch_length_ft=8)
    print("\nX-Shape 12+8 ft:", calculate_bom(x_shape))