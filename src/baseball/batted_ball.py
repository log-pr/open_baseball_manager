"""Contact physics: what the bat did to the ball.

Physics only. Whether anybody caught it is FieldingEngine's problem, and
whether it counts as a hit is OfficialScorer's. Keeping them apart matters
because the physics is objective and testable against published Statcast
ranges, while the fielding model is a tuning knob.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Tuple

from .config import DEFAULT_CONFIG, SimulationConfig
from .enums import GRAVITY_FT_S2, MPH_TO_FPS, grade_to_z

if TYPE_CHECKING:  # pragma: no cover
    from .pitch import Pitch
    from .player import Player


@dataclass(frozen=True)
class BattedBall:
    """A ball in play, described the way Statcast would describe it."""

    exit_velocity: float  # mph off the bat
    launch_angle: float  # degrees, vertical
    spray_angle: float  # degrees, negative = pull for a righty
    distance: float  # feet to landing point
    hang_time: float  # seconds in the air

    def __str__(self) -> str:
        return (
            f"{self.exit_velocity:.1f} mph, {self.launch_angle:.1f} deg launch, "
            f"{self.distance:.0f} ft"
        )

    # --- Classification -------------------------------------------------

    @property
    def is_barrel(self) -> bool:
        """Statcast's barrel definition.

        A batted ball needs at least 98 mph exit velocity. At 98 the
        qualifying launch angle window is 26-30 degrees, and the window
        widens by roughly a degree on each end per additional mph, until at
        116 mph anything from 8 to 50 degrees qualifies.
        """
        if self.exit_velocity < 98.0:
            return False
        over = self.exit_velocity - 98.0
        low = max(8.0, 26.0 - over * 1.0)
        high = min(50.0, 30.0 + over * 1.11)
        return low <= self.launch_angle <= high

    @property
    def is_hard_hit(self) -> bool:
        """Statcast counts anything at 95 mph or better as hard hit."""
        return self.exit_velocity >= 95.0

    @property
    def is_sweet_spot(self) -> bool:
        """Launch angle between 8 and 32 degrees."""
        return 8.0 <= self.launch_angle <= 32.0

    @property
    def batted_ball_type(self) -> str:
        if self.launch_angle < 10:
            return "ground ball"
        if self.launch_angle < 25:
            return "line drive"
        if self.launch_angle < 50:
            return "fly ball"
        return "pop up"

    # --- Physics --------------------------------------------------------

    @classmethod
    def from_contact(
        cls,
        batter: "Player",
        pitch: "Pitch",
        rng: random.Random,
        config: SimulationConfig = DEFAULT_CONFIG,
    ) -> "BattedBall":
        """Turn a swing on a pitch into a trajectory."""
        h = batter.hitting
        cfg = config

        # Ball-bat collision. The classic approximation is that exit
        # velocity ceiling scales with bat speed plus a smaller share of the
        # incoming pitch speed.
        max_ev = (
            cfg.bat_speed_coefficient * h.bat_speed
            + cfg.pitch_speed_coefficient * pitch.velocity
        )

        # Squared-up rate: the share of that ceiling actually achieved.
        # Good contact hitters square up more often; pitches away from the
        # middle of the zone are harder to square up.
        hit_z = grade_to_z(h.hit_grade)
        center_penalty = (
            max(0.0, pitch.distance_from_center - cfg.squared_up_location_offset)
            * cfg.squared_up_location_weight
        )
        spread = max(
            cfg.squared_up_spread_min,
            cfg.squared_up_spread - hit_z * cfg.squared_up_hit_grade_weight + center_penalty,
        )
        squared_up = 1.0 - abs(rng.gauss(0, spread))
        squared_up = max(cfg.squared_up_min, min(1.0, squared_up))

        exit_velocity = max(cfg.exit_velocity_min, max_ev * squared_up)

        # Launch angle keys off the swing plane, adjusted for pitch height
        # (low pitches get hit at a steeper angle) plus per-swing noise.
        height_adjust = (cfg.launch_height_baseline - pitch.z) * cfg.launch_height_weight
        launch_angle = (
            h.attack_angle
            + height_adjust
            + rng.gauss(cfg.launch_angle_offset, cfg.launch_angle_sigma)
        )
        launch_angle = max(cfg.launch_angle_min, min(cfg.launch_angle_max, launch_angle))

        # Spray angle follows pull tendency, with inside pitches pulled more.
        pull_bias = h.pull_tendency * cfg.pull_weight
        inside_effect = (
            -pitch.x * cfg.spray_inside_weight
            if batter.bats == "R"
            else pitch.x * cfg.spray_inside_weight
        )
        spray_angle = pull_bias + inside_effect + rng.gauss(0, cfg.spray_sigma)
        spray_angle = max(-cfg.spray_max, min(cfg.spray_max, spray_angle))

        distance, hang_time = cls._trajectory(exit_velocity, launch_angle, cfg)

        return cls(
            exit_velocity=round(exit_velocity, 1),
            launch_angle=round(launch_angle, 1),
            spray_angle=round(spray_angle, 1),
            distance=round(distance, 1),
            hang_time=round(hang_time, 2),
        )

    @staticmethod
    def _trajectory(
        exit_velocity: float,
        launch_angle: float,
        config: SimulationConfig = DEFAULT_CONFIG,
    ) -> Tuple[float, float]:
        """Projectile motion with a flat drag correction.

        Full aerodynamics (spin-dependent lift, altitude, air density) is
        overkill here. This is tuned so the exit velocity / launch angle /
        distance combinations land in realistic territory.
        """
        cfg = config

        if launch_angle <= 0:
            # Grounder: it skips along the ground rather than flying.
            speed = exit_velocity * MPH_TO_FPS
            distance = max(
                cfg.ground_distance_min,
                speed * cfg.ground_roll_factor * (1.0 + launch_angle / cfg.ground_angle_scale),
            )
            return distance, 0.0

        v = exit_velocity * MPH_TO_FPS
        theta = math.radians(launch_angle)

        # Steeper launch angles mean a longer, higher flight, and drag has
        # more time to bleed off distance. A flat drag factor overstates
        # towering fly balls badly, so it scales with launch angle.
        drag = (
            cfg.drag_factor
            - max(0.0, launch_angle - cfg.drag_angle_threshold) * cfg.drag_angle_penalty
        )
        drag = max(cfg.drag_factor_min, drag)

        vacuum_range = (v**2) * math.sin(2 * theta) / GRAVITY_FT_S2
        distance = max(cfg.air_distance_min, vacuum_range * drag)

        hang_time = 2.0 * v * math.sin(theta) / GRAVITY_FT_S2 * cfg.hang_time_factor
        return distance, max(0.0, hang_time)
