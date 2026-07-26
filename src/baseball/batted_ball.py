"""What happens after the bat hits the ball.

Two separate jobs live here:

  from_contact() - the physics. Turn a swing and a pitch into a real
                   trajectory (exit velocity, launch angle, spray, distance).
  resolve()      - the defense. Decide whether somebody caught it.

Keeping them apart matters because the physics is objective and testable
against real Statcast ranges, while the fielding model is a tuning knob.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, List, Optional, Tuple

from .config import (
    DEFAULT_CONFIG,
    DEFAULT_PARK,
    ParkConfig,
    SimulationConfig,
)
from .enums import (
    GRAVITY_FT_S2,
    INFIELD_DEPTH_FT,
    MPH_TO_FPS,
    OUTFIELD_DEPTH_FT,
    WALL_DISTANCE_FT,
    AtBatResult,
    Position,
    grade_to_z,
)

if TYPE_CHECKING:  # pragma: no cover
    from .pitch import Pitch
    from .player import Player
    from .team import Team


# Where each fielder stands: (spray angle in degrees, depth in feet).
# Spray angle is from the batter's view: negative = left field line,
# positive = right field line, 0 = straight up the middle.
FIELDER_POSITIONS = {
    Position.THIRD: (-27.0, INFIELD_DEPTH_FT - 25),
    Position.SS: (-12.0, INFIELD_DEPTH_FT),
    Position.SECOND: (12.0, INFIELD_DEPTH_FT),
    Position.FIRST: (27.0, INFIELD_DEPTH_FT - 25),
    Position.LF: (-27.0, OUTFIELD_DEPTH_FT),
    Position.CF: (0.0, OUTFIELD_DEPTH_FT + 20),
    Position.RF: (27.0, OUTFIELD_DEPTH_FT),
    Position.C: (0.0, 5.0),
}


@dataclass
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
    def wall_distance(self) -> float:
        """Distance to the fence at this ball's spray angle, default park.

        Convenience for the standard park. `resolve()` uses whichever
        ParkConfig it was handed instead.
        """
        return DEFAULT_PARK.wall_distance(self.spray_angle)

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

    # --- Fielding -------------------------------------------------------

    def responsible_fielder(self, defense: "Team") -> Optional["Player"]:
        """Find whoever is closest to where this ball is going."""
        return self._fielder_gap(defense)[0]

    def _landing_point(self) -> Tuple[float, float]:
        rad = math.radians(self.spray_angle)
        return (self.distance * math.sin(rad), self.distance * math.cos(rad))

    def _fielder_gap(self, defense: "Team") -> Tuple[Optional["Player"], float]:
        """Return the responsible fielder and how far he has to travel."""
        landing = self._landing_point()
        best, best_dist = None, float("inf")
        for player, position in defense.fielding_positions.items():
            if position in (Position.DH, Position.SP, Position.RP, Position.CL):
                continue
            spot = FIELDER_POSITIONS.get(position)
            if spot is None:
                continue
            fx = spot[1] * math.sin(math.radians(spot[0]))
            fy = spot[1] * math.cos(math.radians(spot[0]))
            dist = math.hypot(landing[0] - fx, landing[1] - fy)
            if dist < best_dist:
                best, best_dist = player, dist
        return best, best_dist

    def resolve(
        self,
        defense: "Team",
        rng: random.Random,
        config: SimulationConfig = DEFAULT_CONFIG,
        park: ParkConfig = DEFAULT_PARK,
    ) -> AtBatResult:
        """Decide what this batted ball actually becomes."""
        wall = park.wall_distance(self.spray_angle)

        # Out of the park. The fence is closer down the lines than in center.
        if (
            self.distance >= wall
            and config.home_run_min_angle <= self.launch_angle <= config.home_run_max_angle
        ):
            return AtBatResult.HOME_RUN

        # Foul out of play.
        if abs(self.spray_angle) > config.spray_max:
            return AtBatResult.FLY_OUT

        fielder, gap = self._fielder_gap(defense)
        if fielder is None:
            return AtBatResult.SINGLE

        ball_type = self.batted_ball_type

        if ball_type == "ground ball":
            return self._resolve_ground_ball(defense, rng, config)
        return self._resolve_air_ball(fielder, gap, ball_type, rng, config, wall)

    def _ground_ball_fielder(
        self, defense: "Team", config: SimulationConfig = DEFAULT_CONFIG
    ) -> Tuple[Optional["Player"], float, float]:
        """Ground balls roll, so they get fielded along their path.

        Using a landing point here would be wrong: a grounder first touches
        the grass 60-80 feet from the plate, well in front of the infielders,
        but it keeps going. What matters is where it crosses infield depth
        and how long the fielder has to get there.
        """
        rad = math.radians(self.spray_angle)
        bx = INFIELD_DEPTH_FT * math.sin(rad)
        by = INFIELD_DEPTH_FT * math.cos(rad)

        best, best_dist = None, float("inf")
        for player, position in defense.fielding_positions.items():
            spot = FIELDER_POSITIONS.get(position)
            if spot is None or position in (Position.C, Position.LF, Position.CF, Position.RF):
                continue
            fx = spot[1] * math.sin(math.radians(spot[0]))
            fy = spot[1] * math.cos(math.radians(spot[0]))
            dist = math.hypot(bx - fx, by - fy)
            if dist < best_dist:
                best, best_dist = player, dist

        # How long the ball takes to travel out to the infielders. Friction
        # and the bounce bleed off a good chunk of the exit velocity.
        horizontal = max(
            config.ground_ball_speed_min,
            self.exit_velocity * MPH_TO_FPS * config.ground_ball_speed_retention,
        )
        travel_time = INFIELD_DEPTH_FT / horizontal
        return best, best_dist, travel_time

    def _resolve_ground_ball(
        self,
        defense: "Team",
        rng: random.Random,
        config: SimulationConfig = DEFAULT_CONFIG,
    ) -> AtBatResult:
        cfg = config
        fielder, gap, travel_time = self._ground_ball_fielder(defense, cfg)
        if fielder is None:
            return AtBatResult.SINGLE

        # Reaction eats into the time available; lateral movement on a
        # grounder is slower than an open-field sprint.
        react = (
            cfg.infield_reaction_time
            - grade_to_z(fielder.fielding.field_grade) * cfg.infield_reaction_grade_weight
        )
        usable = max(0.0, travel_time - react)
        reach = usable * fielder.running.sprint_speed * cfg.infield_reach_factor

        if gap > reach:
            double_chance = (
                cfg.ground_double_corner_rate
                if abs(self.spray_angle) > cfg.corner_spray_angle
                else cfg.ground_double_base_rate
            )
            return AtBatResult.DOUBLE if rng.random() < double_chance else AtBatResult.SINGLE

        if rng.random() < fielder.fielding.error_rate:
            return AtBatResult.ERROR

        # Fielded cleanly, but a fast runner can still beat the throw.
        speed_z = (
            self.exit_velocity - cfg.infield_hit_velocity_baseline
        ) / cfg.infield_hit_velocity_scale
        infield_hit = max(
            cfg.infield_hit_min,
            cfg.infield_hit_base - speed_z * cfg.infield_hit_velocity_weight,
        )
        if rng.random() < infield_hit:
            return AtBatResult.SINGLE
        return AtBatResult.GROUND_OUT

    def _resolve_air_ball(
        self,
        fielder: "Player",
        gap: float,
        ball_type: str,
        rng: random.Random,
        config: SimulationConfig = DEFAULT_CONFIG,
        wall: Optional[float] = None,
    ) -> AtBatResult:
        cfg = config
        if wall is None:
            wall = self.wall_distance

        # How far the fielder can travel while the ball is in the air.
        # Real fielders lose about half a second to reaction before moving.
        react = (
            cfg.reaction_time_base
            - grade_to_z(fielder.fielding.field_grade) * cfg.outfield_reaction_grade_weight
        )
        usable = max(0.0, self.hang_time - react)
        range_ft = usable * fielder.running.sprint_speed * cfg.outfield_reach_factor

        if range_ft <= 0:
            catchable = False
        else:
            # Smooth catch probability instead of a hard cutoff, so close
            # plays go either way.
            margin = (range_ft - gap) / cfg.catch_probability_slope
            catch_prob = 1.0 / (1.0 + math.exp(-margin))
            catchable = rng.random() < catch_prob

        if catchable:
            if rng.random() < fielder.fielding.error_rate * cfg.air_error_multiplier:
                return AtBatResult.ERROR
            if ball_type == "line drive":
                return AtBatResult.LINE_OUT
            if ball_type == "pop up":
                return AtBatResult.POP_OUT
            return AtBatResult.FLY_OUT

        # It dropped. How far it landed, and how close to the line, decides
        # how many bases. Balls down the line and into the gaps take longer
        # to run down than balls hit right at somebody.
        corner_bonus = (
            cfg.corner_bonus if abs(self.spray_angle) > cfg.corner_spray_angle else 0.0
        )

        if self.distance >= wall - cfg.wall_margin:
            return (
                AtBatResult.TRIPLE
                if rng.random() < cfg.off_wall_triple_rate
                else AtBatResult.DOUBLE
            )
        if self.distance >= cfg.deep_distance:
            roll = rng.random()
            if roll < cfg.deep_triple_rate + corner_bonus * cfg.deep_triple_corner_weight:
                return AtBatResult.TRIPLE
            if roll < cfg.deep_double_rate + corner_bonus:
                return AtBatResult.DOUBLE
            return AtBatResult.SINGLE
        if self.distance >= cfg.medium_distance:
            return (
                AtBatResult.DOUBLE
                if rng.random() < cfg.medium_double_rate + corner_bonus
                else AtBatResult.SINGLE
            )
        return AtBatResult.SINGLE
