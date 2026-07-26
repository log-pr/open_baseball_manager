"""One plate appearance, resolved pitch by pitch.

This module holds the two smallest testable units in the whole simulation:

  throw_next_pitch() - one pitch, start to finish
  simulate()         - loop pitches until the at-bat resolves

Everything above this (innings, games, seasons) is just loops over these.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List, Optional, Tuple

from .batted_ball import BattedBall
from .config import DEFAULT_CONFIG, DEFAULT_PARK, ParkConfig, SimulationConfig
from .enums import AtBatResult, PitchCall, SwingOutcome, grade_to_z
from .pitch import Pitch

if TYPE_CHECKING:  # pragma: no cover
    from .player import Player
    from .team import Team


@dataclass
class AtBat:
    """A batter/pitcher confrontation."""

    batter: "Player"
    pitcher: "Player"
    defense: Optional["Team"] = None
    rng: random.Random = field(default_factory=random.Random)
    config: SimulationConfig = DEFAULT_CONFIG
    park: ParkConfig = DEFAULT_PARK

    balls: int = 0
    strikes: int = 0
    fouls: int = 0
    pitches: List[Pitch] = field(default_factory=list)
    batted_ball: Optional[BattedBall] = None

    @property
    def count(self) -> str:
        return f"{self.balls}-{self.strikes}"

    @property
    def is_complete(self) -> bool:
        return self.balls >= 4 or self.strikes >= 3

    # --- Batter decisions ------------------------------------------------

    def _swing_probability(self, pitch: Pitch) -> float:
        """How likely the batter is to offer at this pitch.

        Good plate discipline (eye grade) mostly shows up as laying off
        pitches out of the zone rather than swinging more at strikes.
        """
        cfg = self.config
        eye_z = grade_to_z(self.batter.hitting.eye_grade)

        if pitch.in_zone:
            base = cfg.zone_swing_rate
            # With two strikes he has to protect.
            if self.strikes == 2:
                base = cfg.two_strike_zone_swing_rate
            return max(
                cfg.zone_swing_min,
                min(cfg.zone_swing_max, base + eye_z * cfg.zone_swing_eye_weight),
            )

        # Chase rate: better eyes chase less.
        base = cfg.chase_rate_base - eye_z * cfg.eye_grade_weight
        # Pitches just off the plate are more tempting than way outside.
        nearness = max(
            0.0,
            1.0
            - (pitch.distance_from_center - cfg.chase_nearness_offset)
            / cfg.chase_nearness_scale,
        )
        base *= max(cfg.chase_nearness_floor, nearness)
        if self.strikes == 2:
            base += cfg.two_strike_chase_bonus
        return max(cfg.chase_min, min(cfg.chase_max, base))

    def _whiff_probability(self, pitch: Pitch) -> float:
        """How likely a swing misses entirely."""
        cfg = self.config
        hit_z = grade_to_z(self.batter.hitting.hit_grade)
        base = cfg.whiff_base - hit_z * cfg.whiff_hit_grade_weight

        # Velocity, spin, and location all make contact harder.
        base += (
            pitch.effective_velocity - cfg.whiff_velocity_baseline
        ) * cfg.whiff_velocity_weight
        base += (pitch.spin_rate - cfg.whiff_spin_baseline) * cfg.whiff_spin_weight
        base += (
            max(0.0, pitch.distance_from_center - cfg.whiff_location_offset)
            * cfg.whiff_location_weight
        )

        # Longer swings are more susceptible to missing.
        base += (
            self.batter.hitting.swing_length - cfg.whiff_swing_length_baseline
        ) * cfg.whiff_swing_length_weight

        return max(cfg.whiff_min, min(cfg.whiff_max, base))

    def _foul_probability(self, pitch: Pitch) -> float:
        """Given contact, how often it goes foul."""
        cfg = self.config
        hit_z = grade_to_z(self.batter.hitting.hit_grade)
        base = cfg.foul_rate_base - hit_z * cfg.foul_hit_grade_weight
        base += (
            max(0.0, pitch.distance_from_center - cfg.foul_location_offset)
            * cfg.foul_location_weight
        )
        return max(cfg.foul_min, min(cfg.foul_max, base))

    # --- Pitch resolution ------------------------------------------------

    def throw_next_pitch(self) -> Tuple[PitchCall, Pitch]:
        """Throw and resolve exactly one pitch. The smallest test unit."""
        if self.is_complete:
            raise RuntimeError("at-bat is already complete")

        pitch = Pitch.thrown(self.pitcher, self.rng, self.config)
        self.pitches.append(pitch)
        self.pitcher.pitches_thrown += 1

        # Hit by pitch: only for pitches well inside and off the plate.
        if (
            not pitch.in_zone
            and pitch.distance_from_center > self.config.hbp_distance_threshold
        ):
            if self.rng.random() < self.config.hbp_rate:
                return PitchCall.HIT_BY_PITCH, pitch

        swings = self.rng.random() < self._swing_probability(pitch)

        if not swings:
            if pitch.in_zone:
                self.strikes += 1
                return PitchCall.CALLED_STRIKE, pitch
            self.balls += 1
            return PitchCall.BALL, pitch

        outcome = self._resolve_swing(pitch)

        if outcome is SwingOutcome.WHIFF:
            self.strikes += 1
            return PitchCall.SWINGING_STRIKE, pitch

        if outcome is SwingOutcome.FOUL:
            self.fouls += 1
            # A foul with two strikes keeps the at-bat alive.
            if self.strikes < 2:
                self.strikes += 1
            return PitchCall.FOUL, pitch

        self.batted_ball = BattedBall.from_contact(
            self.batter, pitch, self.rng, self.config
        )
        return PitchCall.IN_PLAY, pitch

    def _resolve_swing(self, pitch: Pitch) -> SwingOutcome:
        if self.rng.random() < self._whiff_probability(pitch):
            return SwingOutcome.WHIFF
        if self.rng.random() < self._foul_probability(pitch):
            return SwingOutcome.FOUL
        return SwingOutcome.CONTACT

    # --- Full plate appearance -------------------------------------------

    def simulate(self) -> AtBatResult:
        """Loop pitches until the plate appearance resolves."""
        while True:
            call, _pitch = self.throw_next_pitch()

            if call is PitchCall.HIT_BY_PITCH:
                return AtBatResult.HIT_BY_PITCH

            if call is PitchCall.IN_PLAY:
                assert self.batted_ball is not None
                if self.defense is None:
                    # No defense supplied: useful for isolated physics tests.
                    return AtBatResult.SINGLE
                return self.batted_ball.resolve(
                    self.defense, self.rng, self.config, self.park
                )

            if self.balls >= 4:
                return AtBatResult.WALK
            if self.strikes >= 3:
                return AtBatResult.STRIKEOUT
