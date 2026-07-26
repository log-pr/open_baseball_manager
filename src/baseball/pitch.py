"""A single pitched ball.

The interesting logic here is in generation, not in methods on the object.
Two separate randomness sources shape where the ball ends up:

  control_grade -> how ambitious the target is (do you aim at the zone at all)
  command_grade -> how tightly the actual pitch clusters around that target

That split is what makes "accuracy" and "precision" different things: a
pitcher with good control but poor command throws strikes, just not the
strikes he wanted.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Tuple

from .config import DEFAULT_CONFIG, SimulationConfig
from .enums import (
    PLATE_HALF_WIDTH_FT,
    ZONE_BOTTOM_FT,
    ZONE_TOP_FT,
    PitchType,
    grade_to_z,
)

if TYPE_CHECKING:  # pragma: no cover
    from .player import Player


ZONE_CENTER_Z = (ZONE_TOP_FT + ZONE_BOTTOM_FT) / 2.0


@dataclass
class Pitch:
    """One pitch, from release to crossing the plate."""

    pitch_type: PitchType
    velocity: float  # mph, actual for this pitch
    spin_rate: float  # rpm
    intended_location: Tuple[float, float]  # (x, z) in feet, where he aimed
    actual_location: Tuple[float, float]  # (x, z) in feet, where it went
    effective_velocity: float  # velocity adjusted for release extension

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

    @classmethod
    def thrown(
        cls,
        pitcher: "Player",
        rng: random.Random,
        config: SimulationConfig = DEFAULT_CONFIG,
    ) -> "Pitch":
        """Have the pitcher throw one pitch."""
        profile = pitcher.pitching
        arsenal = profile.repertoire
        if not arsenal:
            raise ValueError(f"{pitcher.name} has no pitches in his repertoire")

        # Better pitches get thrown more often.
        weights = [
            max(config.pitch_selection_min_weight, entry.grade - config.pitch_selection_offset)
            for entry in arsenal
        ]
        entry = rng.choices(arsenal, weights=weights)[0]

        fatigue = pitcher.fatigue

        # Control decides how aggressively he attacks the zone.
        control_z = (
            grade_to_z(profile.control_grade) - fatigue * config.fatigue_control_penalty
        )
        aim_at_zone = rng.random() < min(
            config.zone_target_max,
            config.zone_target_rate + control_z * config.control_grade_weight,
        )

        if aim_at_zone:
            target_x = rng.uniform(
                -config.zone_target_x_halfwidth, config.zone_target_x_halfwidth
            )
            target_z = rng.uniform(
                ZONE_BOTTOM_FT + config.zone_target_z_inset,
                ZONE_TOP_FT - config.zone_target_z_inset,
            )
        else:
            # Deliberately off the plate - chase pitch.
            target_x = rng.choice([-1.0, 1.0]) * rng.uniform(
                config.chase_target_x_min, config.chase_target_x_max
            )
            target_z = rng.uniform(
                ZONE_BOTTOM_FT - config.chase_target_z_below,
                ZONE_TOP_FT + config.chase_target_z_above,
            )

        # Command decides the scatter around that target.
        command_z = (
            grade_to_z(profile.command_grade) - fatigue * config.fatigue_command_penalty
        )
        sigma = max(
            config.command_sigma_min,
            config.command_sigma_base - command_z * config.command_grade_weight,
        )

        actual_x = target_x + rng.gauss(0, sigma)
        actual_z = target_z + rng.gauss(0, sigma)

        velocity = (
            entry.velocity
            + rng.gauss(0, config.velocity_noise)
            - fatigue * config.fatigue_velocity_penalty
        )
        spin = entry.spin_rate + rng.gauss(0, config.spin_noise)

        # Longer extension shortens the effective distance to the plate, so
        # the same velocity reaches the hitter sooner and plays up.
        effective = velocity + (
            profile.extension - config.extension_baseline
        ) * config.extension_velocity_weight

        return cls(
            pitch_type=entry.pitch_type,
            velocity=round(velocity, 1),
            spin_rate=round(spin),
            intended_location=(round(target_x, 2), round(target_z, 2)),
            actual_location=(round(actual_x, 2), round(actual_z, 2)),
            effective_velocity=round(effective, 1),
        )
