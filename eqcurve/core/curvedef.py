"""CurveDef: the complete, re-editable definition of an equation curve.

This is the data that the add-in stores (as a JSON attribute) so the curve can
be re-opened and edited losslessly, and re-evaluated when referenced design
parameters change. It is adsk-free and pytest-friendly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field, fields
from typing import Dict, Optional

# Supported modes / coordinate systems (see spec FR-1, FR-2)
MODES = ("parametric", "explicit")
COORDS_2D = ("cartesian", "polar")
COORDS_3D = ("cartesian", "cylindrical", "spherical")


@dataclass
class CurveDef:
    # --- input model ---
    mode: str = "parametric"          # 'parametric' | 'explicit'
    coord: str = "cartesian"          # see COORDS_2D / COORDS_3D
    dim: int = 2                      # 2 or 3
    angle: str = "rad"                # 'rad' | 'deg'

    # Expressions. For parametric: keys depend on coord/dim, e.g.
    #   cartesian2d: {'x':..,'y':..}; polar2d: {'r':..,'theta':..}
    #   cartesian3d: {'x':..,'y':..,'z':..}; cylindrical: {'r':..,'theta':..,'z':..}
    #   spherical:   {'r':..,'phi':..,'theta':..}
    # For explicit: {'y': f(x)}  (cartesian) or {'r': f(a)} (polar)
    exprs: Dict[str, str] = field(default_factory=dict)

    # --- domain ---
    var: str = "t"                    # independent variable name
    t_min: str = "0"                  # expressions allowed (may use params)
    t_max: str = "1"
    samples: int = 200                # number of points (deterministic)
    closed: bool = False              # force-close start==end
    adaptive: bool = False            # deterministic curvature-adaptive sampling (FR-10.2)

    # --- placement (applied after evaluation, in model units = mm) ---
    origin: Dict[str, str] = field(default_factory=lambda: {"x": "0", "y": "0", "z": "0"})

    # free-text note for the user
    note: Optional[str] = None

    # ---- serialization (lossless round-trip for re-edit) ----
    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> "CurveDef":
        data = json.loads(text)
        # Tolerate unknown keys (forward/backward-compatible re-edit): a JSON
        # written by a newer/older version still loads with defaults for the rest.
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def validate(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        if self.dim not in (2, 3):
            raise ValueError("dim must be 2 or 3")
        valid_coords = COORDS_2D if self.dim == 2 else COORDS_3D
        if self.coord not in valid_coords:
            raise ValueError(f"coord for dim {self.dim} must be one of {valid_coords}")
        if self.angle not in ("rad", "deg"):
            raise ValueError("angle must be 'rad' or 'deg'")
        if self.samples < 2:
            raise ValueError("samples must be >= 2")
        if not self.exprs:
            raise ValueError("exprs must not be empty")
