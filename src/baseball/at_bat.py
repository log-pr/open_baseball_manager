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
        eye_z = grade_to_z(self.batter.hitting.eye_grade)

        if pitch.in_zone:
            base = 0.67
            # With two strikes he has to protect.
            if self.strikes == 2:
                base = 0.88
            return max(0.15, min(0.97, base + eye_z * 0.015))

        # Chase rate: better eyes chase less.
        base = 0.475 - eye_z * 0.055
        # Pitches just off the plate are more tempting than way outside.
        nearness = max(0.0, 1.0 - (pitch.distance_from_center - 0.85) / 1.9)
        base *= max(0.12, nearness)
        if self.strikes == 2:
            base += 0.20
        return max(0.02, min(0.92, base))

    def _whiff_probability(self, pitch: Pitch) -> float:
        """How likely a swing misses entirely."""
        hit_z = grade_to_z(self.batter.hitting.hit_grade)
        base = 0.170 - hit_z * 0.035

        # Velocity, spin, and location all make contact harder.
        base += (pitch.effective_velocity - 92.0) * 0.0055
        base += (pitch.spin_rate - 2250) * 0.000022
        base += max(0.0, pitch.distance_from_center - 0.75) * 0.16

        # Longer swings are more susceptible to missing.
        base += (self.batter.hitting.swing_length - 7.3) * 0.022

        return max(0.03, min(0.85, base))

    def _foul_probability(self, pitch: Pitch) -> float:
        """Given contact, how often it goes foul."""
        hit_z = grade_to_z(self.batter.hitting.hit_grade)
        base = 0.575 - hit_z * 0.012
        base += max(0.0, pitch.distance_from_center - 0.75) * 0.10
        return max(0.15, min(0.70, base))

    # --- Pitch resolution ------------------------------------------------

    def throw_next_pitch(self) -> Tuple[PitchCall, Pitch]:
        """Throw and resolve exactly one pitch. The smallest test unit."""
        if self.is_complete:
            raise RuntimeError("at-bat is already complete")

        pitch = Pitch.thrown(self.pitcher, self.rng)
        self.pitches.append(pitch)
        self.pitcher.pitches_thrown += 1

        # Hit by pitch: only for pitches well inside and off the plate.
        if not pitch.in_zone and pitch.distance_from_center > 1.5:
            if self.rng.random() < 0.011:
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

        self.batted_ball = BattedBall.from_contact(self.batter, pitch, self.rng)
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
                return self.batted_ball.resolve(self.defense, self.rng)

            if self.balls >= 4:
                return AtBatResult.WALK
            if self.strikes >= 3:
                return AtBatResult.STRIKEOUT
