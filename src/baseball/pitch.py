"""A single pitched ball.

An immutable record: a pitch is a historical fact, and nothing should
mutate one after it crosses the plate. It holds references to the pitcher
and batter so a pitch stays meaningful outside the at-bat that produced it.

Created only by PitchingEngine.throw_pitch() -- the interesting logic is in
generation, not in methods here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional, Tuple

from .enums import (
    PLATE_HALF_WIDTH_FT,
    ZONE_BOTTOM_FT,
    ZONE_TOP_FT,
    PitchType,
)

if TYPE_CHECKING:  # pragma: no cover
    from .player import Player


ZONE_CENTER_Z = (ZONE_TOP_FT + ZONE_BOTTOM_FT) / 2.0


@dataclass(frozen=True)
class Pitch:
    """One pitch, from release to crossing the plate."""

    pitch_type: PitchType
    velocity: float  # mph, actual for this pitch
    spin_rate: float  # rpm
    intended_location: Tuple[float, float]  # (x, z) in feet, where he aimed
    actual_location: Tuple[float, float]  # (x, z) in feet, where it went
    effective_velocity: float  # velocity adjusted for release extension
    pitcher: Optional["Player"] = None
    batter: Optional["Player"] = None

    @property
    def x(self) -> float:
        return self.actual_location[0]

    @property
    def z(self) -> float:
        return self.actual_location[1]

    @property
    def in_zone(self) -> bool:
        return (
            abs(self.x) <= PLATE_HALF_WIDTH_FT
            and ZONE_BOTTOM_FT <= self.z <= ZONE_TOP_FT
        )

    @property
    def distance_from_center(self) -> float:
        """Feet from the middle of the zone. Bigger = harder to square up."""
        return ((self.x**2) + ((self.z - ZONE_CENTER_Z) ** 2)) ** 0.5

    @property
    def miss_distance(self) -> float:
        """How far the pitch landed from where it was aimed, in feet."""
        dx = self.x - self.intended_location[0]
        dz = self.z - self.intended_location[1]
        return ((dx**2) + (dz**2)) ** 0.5

    def __str__(self) -> str:
        loc = "in zone" if self.in_zone else "out of zone"
        return f"{self.pitch_type} {self.velocity:.1f} mph ({loc})"
