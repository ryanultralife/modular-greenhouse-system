"""Engineering triage for a configuration.

IMPORTANT — what this module is and is not:

  * It is a TRIAGE tool. It compares a layout against limits stored in the
    catalog and tells Josh whether a build is a standard, already-engineered
    case or a non-standard one that needs an engineer to sign off.

  * It is NOT a structural analysis and it does NOT certify anything. It never
    computes wind/snow capacity from scratch. The published 130 mph / 6 ft
    ratings apply to standard straight runs; this module will not extend those
    claims to a non-standard layout on its own.

Status values returned:
  STANDARD                 - matches a base/straight case; published rating applies.
  PRELIMINARY_OK           - within Josh's *verified* configuration limits.
  REQUIRES_ENGINEER_SIGNOFF- exceeds limits, OR limits are still placeholders.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .catalog import Catalog
from .configurator import Configuration, footprint_sqft

STANDARD = "STANDARD"
PRELIMINARY_OK = "PRELIMINARY_OK"
REQUIRES_SIGNOFF = "REQUIRES_ENGINEER_SIGNOFF"

DISCLAIMER = (
    "This is an automated triage, not a structural certification. Published "
    "130 mph wind / 6 ft snow ratings apply to standard straight-run builds. "
    "Any non-standard configuration must be verified and signed off by a "
    "qualified engineer before those ratings are advertised for it."
)


@dataclass
class EngineeringCheck:
    status: str
    reasons: list[str] = field(default_factory=list)
    used_placeholder_limits: bool = False
    disclaimer: str = DISCLAIMER

    @property
    def ok_without_signoff(self) -> bool:
        return self.status in (STANDARD, PRELIMINARY_OK)


def _limit(limits: dict, key: str):
    """Return (value, verified) for a configuration limit, or (None, False)."""
    entry = limits.get(key)
    if not isinstance(entry, dict):
        return None, False
    return entry.get("value"), bool(entry.get("verified", False))


def assess(catalog: Catalog, config: Configuration) -> EngineeringCheck:
    layout = config.layout
    limits = catalog.configuration_limits

    # Standard case: a single straight run, no junctions. The published rating
    # is designed for exactly this, so it passes without further sign-off.
    if layout.shape == "straight" and not layout.junctions:
        return EngineeringCheck(status=STANDARD, reasons=["Standard straight run."])

    reasons: list[str] = []
    used_placeholder = False
    needs_signoff = False

    max_run, run_verified = _limit(limits, "max_straight_run_ft")
    max_fp, fp_verified = _limit(limits, "max_total_footprint_sqft")
    max_j, j_verified = _limit(limits, "max_junctions")

    longest = layout.longest_run_ft
    fp = footprint_sqft(catalog, config)
    n_junctions = len(layout.junctions)

    # Longest run vs limit
    if max_run is None or not run_verified:
        used_placeholder = used_placeholder or (max_run is not None)
        needs_signoff = True
        reasons.append(
            f"Longest run is {longest:g} ft; max-run limit is not verified "
            "(needs Josh's engineering input)."
        )
    elif longest > max_run:
        needs_signoff = True
        reasons.append(f"Longest run {longest:g} ft exceeds verified limit {max_run:g} ft.")
    else:
        reasons.append(f"Longest run {longest:g} ft within verified limit {max_run:g} ft.")

    # Footprint vs limit
    if max_fp is None or not fp_verified:
        used_placeholder = used_placeholder or (max_fp is not None)
        needs_signoff = True
        reasons.append(
            f"Footprint ~{fp:g} sqft; footprint limit is not verified."
        )
    elif fp > max_fp:
        needs_signoff = True
        reasons.append(f"Footprint ~{fp:g} sqft exceeds verified limit {max_fp:g} sqft.")
    else:
        reasons.append(f"Footprint ~{fp:g} sqft within verified limit {max_fp:g} sqft.")

    # Junction count vs limit
    if max_j is None or not j_verified:
        used_placeholder = used_placeholder or (max_j is not None)
        needs_signoff = True
        reasons.append(f"{n_junctions} junction(s); junction limit is not verified.")
    elif n_junctions > max_j:
        needs_signoff = True
        reasons.append(f"{n_junctions} junction(s) exceed verified limit {max_j}.")
    else:
        reasons.append(f"{n_junctions} junction(s) within verified limit {max_j}.")

    status = REQUIRES_SIGNOFF if needs_signoff else PRELIMINARY_OK
    return EngineeringCheck(
        status=status,
        reasons=reasons,
        used_placeholder_limits=used_placeholder,
    )
