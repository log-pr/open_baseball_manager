"""One plate appearance, resolved pitch by pitch.

AtBat produces a deliberately narrow outcome: the pitches thrown, how it
terminated, and the batted ball if there was one. No base state, no runs,
no outs.

That narrowness is the point. v0.2 asked this class to report runs,
advancements, and outs, which it structurally cannot know -- a ground ball
is only a double play given the force state, a fly ball is only a sacrifice
given a runner on third. Either it takes ownership of baserunning, or those
fields stay empty. Instead BaserunningEngine turns this outcome plus the
base state into advancements, and AtBat stays testable without constructing
a game.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List, Optional, Tuple

from .batted_ball import BattedBall
from .config import DEFAULT_CONFIG, SimulationConfig
from .engines import BattingEngine, PitchingEngine
from .enums import PitchCall, SwingOutcome
from .events import PlateAppearanceOutcome
from .pitch import Pitch
from .state import PlayerGameState, Situation

if TYPE_CHECKING:  # pragma: no cover
    from .player import Player


@dataclass
class AtBat:
    """A batter/pitcher confrontation."""

    batter: "Player"
    pitcher: "Player"
    pitcher_state: PlayerGameState = None  # type: ignore[assignment]
    rng: random.Random = field(default_factory=random.Random)
    config: SimulationConfig = DEFAULT_CONFIG
    pitching_engine: Optional[PitchingEngine] = None
    batting_engine: Optional[BattingEngine] = None

    balls: int = 0
    strikes: int = 0
    fouls: int = 0
    pitches: List[Pitch] = field(default_factory=list)
    batted_ball: Optional[BattedBall] = None

    def __post_init__(self) -> None:
        if self.pitcher_state is None:
            self.pitcher_state = PlayerGameState(player=self.pitcher)
        if self.pitching_engine is None:
            self.pitching_engine = PitchingEngine(self.config)
        if self.batting_engine is None:
            self.batting_engine = BattingEngine(self.config)

    @property
    def count(self) -> str:
        return f"{self.balls}-{self.strikes}"

    @property
    def is_complete(self) -> bool:
        return self.balls >= 4 or self.strikes >= 3

    # --- Pitch resolution ------------------------------------------------

    def throw_next_pitch(
        self, situation: Optional[Situation] = None
    ) -> Tuple[PitchCall, Pitch]:
        """Throw and resolve exactly one pitch. The smallest test unit."""
        if self.is_complete:
            raise RuntimeError("at-bat is already complete")

        situation = (situation or Situation()).with_count(self.balls, self.strikes)

        pitch = self.pitching_engine.throw_pitch(
            self.pitcher, self.pitcher_state, self.batter, situation, self.rng
        )
        self.pitches.append(pitch)
        self.pitcher_state.record_pitch()

        # Hit by pitch: only for pitches well inside and off the plate.
        if (
            not pitch.in_zone
            and pitch.distance_from_center > self.config.hbp_distance_threshold
        ):
            if self.rng.random() < self.config.hbp_rate:
                return PitchCall.HIT_BY_PITCH, pitch

        if not self.batting_engine.decide_swing(self.batter, pitch, situation, self.rng):
            if pitch.in_zone:
                self.strikes += 1
                return PitchCall.CALLED_STRIKE, pitch
            self.balls += 1
            return PitchCall.BALL, pitch

        outcome = self.batting_engine.resolve_swing(self.batter, pitch, self.rng)

        if outcome is SwingOutcome.WHIFF:
            self.strikes += 1
            return PitchCall.SWINGING_STRIKE, pitch

        if outcome is SwingOutcome.FOUL:
            self.fouls += 1
            # A foul with two strikes keeps the at-bat alive.
            if self.strikes < 2:
                self.strikes += 1
            return PitchCall.FOUL, pitch

        self.batted_ball = self.batting_engine.make_contact(self.batter, pitch, self.rng)
        return PitchCall.IN_PLAY, pitch

    # --- Full plate appearance -------------------------------------------

    def simulate(
        self, situation: Optional[Situation] = None
    ) -> PlateAppearanceOutcome:
        """Loop pitches until the plate appearance resolves.

        Terminates on a strikeout, a walk, a hit by pitch, or a ball in
        play. What happens to the ball in play is somebody else's job.
        """
        while True:
            call, pitch = self.throw_next_pitch(situation)

            if call is PitchCall.HIT_BY_PITCH:
                return PlateAppearanceOutcome(
                    pitch_history=list(self.pitches), terminal_call=call
                )

            if call is PitchCall.IN_PLAY:
                return PlateAppearanceOutcome(
                    pitch_history=list(self.pitches),
                    terminal_call=call,
                    batted_ball=self.batted_ball,
                )

            if self.balls >= 4:
                return PlateAppearanceOutcome(
                    pitch_history=list(self.pitches), terminal_call=PitchCall.BALL
                )
            if self.strikes >= 3:
                return PlateAppearanceOutcome(
                    pitch_history=list(self.pitches), terminal_call=call
                )
