"""Domain model: how a greenhouse layout is described.

A greenhouse is one or more straight RUNS joined at JUNCTIONS. Each run is a
linear sequence of 4' bays. The named shapes below are just convenient presets
that produce the right runs + junction.

Junction arity = how many run-ends meet at the junction:
    corner (L) = 2,  tee (T) = 3,  cross (X) = 4.

Open ends (each gets an end cap) = (2 * number_of_runs) - sum(junction arity).
That identity is what ties layout geometry to the bill of materials.
"""

from __future__ import annotations

from dataclasses import dataclass, field

JUNCTION_ARITY = {"corner": 2, "tee": 3, "cross": 4}


@dataclass(frozen=True)
class Run:
    """A straight linear segment, measured in feet."""

    length_ft: float

    def __post_init__(self) -> None:
        if self.length_ft <= 0:
            raise ValueError(f"Run length must be positive, got {self.length_ft}")


@dataclass(frozen=True)
class Junction:
    kind: str  # "corner" | "tee" | "cross"

    def __post_init__(self) -> None:
        if self.kind not in JUNCTION_ARITY:
            raise ValueError(
                f"Unknown junction kind '{self.kind}'. "
                f"Valid: {', '.join(JUNCTION_ARITY)}"
            )

    @property
    def arity(self) -> int:
        return JUNCTION_ARITY[self.kind]


@dataclass(frozen=True)
class Layout:
    """A complete greenhouse layout: runs joined by junctions."""

    shape: str
    runs: tuple[Run, ...]
    junctions: tuple[Junction, ...] = field(default_factory=tuple)

    @property
    def open_ends(self) -> int:
        consumed = sum(j.arity for j in self.junctions)
        ends = 2 * len(self.runs) - consumed
        if ends < 1:
            raise ValueError(
                "Layout is geometrically invalid: junctions consume more "
                "run-ends than exist. Check the runs/junctions you supplied."
            )
        return ends

    @property
    def total_linear_ft(self) -> float:
        return sum(r.length_ft for r in self.runs)

    @property
    def longest_run_ft(self) -> float:
        return max(r.length_ft for r in self.runs)


def straight(length_ft: float) -> Layout:
    return Layout("straight", (Run(length_ft),))


def l_shape(length_a_ft: float, length_b_ft: float) -> Layout:
    return Layout("L", (Run(length_a_ft), Run(length_b_ft)), (Junction("corner"),))


def t_shape(main_a_ft: float, main_b_ft: float, branch_ft: float) -> Layout:
    """A tee: the main run split into two arms (a, b) plus one branch arm."""
    return Layout(
        "T",
        (Run(main_a_ft), Run(main_b_ft), Run(branch_ft)),
        (Junction("tee"),),
    )


def x_shape(arm_a_ft: float, arm_b_ft: float, arm_c_ft: float, arm_d_ft: float) -> Layout:
    return Layout(
        "X",
        (Run(arm_a_ft), Run(arm_b_ft), Run(arm_c_ft), Run(arm_d_ft)),
        (Junction("cross"),),
    )


# Single source of truth for shape presentation: how many run lengths each
# shape needs, plus customer-facing label, description, and per-arm labels.
SHAPE_INFO = {
    "straight": {
        "label": "Straight",
        "runs": 1,
        "description": "A single run — extend it to any length.",
        "arm_labels": ["Length"],
    },
    "L": {
        "label": "L-shape",
        "runs": 2,
        "description": "Two arms meeting at a 90° corner.",
        "arm_labels": ["First arm", "Second arm"],
    },
    "T": {
        "label": "T-shape",
        "runs": 3,
        "description": "A main run with a branch off the middle.",
        "arm_labels": ["Main run — side A", "Main run — side B", "Branch"],
    },
    "X": {
        "label": "X / cross",
        "runs": 4,
        "description": "Four arms meeting at a central hub.",
        "arm_labels": ["Arm 1", "Arm 2", "Arm 3", "Arm 4"],
    },
}

# Maps a shape name to the number of run lengths the caller must supply.
SHAPE_RUN_COUNTS = {name: info["runs"] for name, info in SHAPE_INFO.items()}


def shape_options() -> list[dict]:
    """Serializable shape metadata for APIs/UIs (single source of truth)."""
    return [
        {
            "name": name,
            "label": info["label"],
            "runs": info["runs"],
            "description": info["description"],
            "arm_labels": info["arm_labels"],
        }
        for name, info in SHAPE_INFO.items()
    ]


SHAPE_BUILDERS = {
    "straight": straight,
    "L": l_shape,
    "T": t_shape,
    "X": x_shape,
}


def build_layout(shape: str, run_lengths: list[float]) -> Layout:
    """Build a Layout from a shape name and the list of run lengths."""
    if shape not in SHAPE_BUILDERS:
        raise ValueError(
            f"Unknown shape '{shape}'. Valid: {', '.join(SHAPE_BUILDERS)}"
        )
    expected = SHAPE_RUN_COUNTS[shape]
    if len(run_lengths) != expected:
        raise ValueError(
            f"Shape '{shape}' needs {expected} run length(s), "
            f"got {len(run_lengths)}: {run_lengths}"
        )
    return SHAPE_BUILDERS[shape](*run_lengths)
