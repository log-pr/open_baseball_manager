"""Immutable records of what happened.

Every object here is a fact about a play that already occurred. Nothing
mutates one after the fact, which is what makes a Play safe to hand to the
scorer, the play-by-play, and later a season log without defensive copying.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .batted_ball import BattedBall
from .enums import AtBatResult, FieldingOutcome, PitchCall
from .pitch import Pitch
from .player import Player


@dataclass(frozen=True)
class PlateAppearanceOutcome:
    """What AtBat can know on its own.

    Deliberately narrow: no base state, no runs, no outs. AtBat cannot
    determine any of those -- a ground ball is only a double play given the
    force state, a fly ball is only a sacrifice given a runner on third --
    so it doesn't pretend to.
    """

    pitch_history: List[Pitch]
    terminal_call: PitchCall
    batted_ball: Optional[BattedBall] = None

    @property
    def pitches(self) -> int:
        return len(self.pitch_history)


@dataclass(frozen=True)
class FieldingResult:
    """What the defense physically did, before anyone judges it."""

    outcome: FieldingOutcome
    fielder: Optional[Player] = None
    landing_zone: str = ""
    distance_traveled: float = 0.0
    time_available: float = 0.0
    # Was a force play available to the fielder? Set in Phase 2; this is
    # what separates a fielder's choice from a single, and what makes a
    # double play possible at all.
    force_available: bool = False
    lead_runner_retired: bool = False
    throw_error: bool = False
    # The fence distance at this ball's spray angle. Carried here because
    # the engine already computed it and BaserunningEngine needs it to tell
    # an off-the-wall double from a routine one.
    wall_distance: float = 0.0

    @property
    def is_out(self) -> bool:
        return self.outcome in (FieldingOutcome.CAUGHT, FieldingOutcome.FOUL)


@dataclass(frozen=True)
class Advancement:
    """One runner moving. to_base 4 means he scored."""

    runner: Player
    from_base: int
    to_base: int
    out: bool = False

    @property
    def scored(self) -> bool:
        return self.to_base >= 4 and not self.out


@dataclass(frozen=True)
class BaserunningResult:
    """Everything the base state produced on one batted ball."""

    advancements: List[Advancement] = field(default_factory=list)
    runs_scored: int = 0
    outs_recorded: int = 0
    batter_bases: int = 0
    batter_safe: bool = False


@dataclass(frozen=True)
class ScoringDecision:
    """The official scorer's ruling."""

    result: AtBatResult
    rbi_credited: int = 0


@dataclass(frozen=True)
class Play:
    """The complete record of one plate appearance."""

    batter: Player
    pitcher: Player
    pitch_history: List[Pitch] = field(default_factory=list)
    batted_ball: Optional[BattedBall] = None
    fielding_result: Optional[FieldingResult] = None
    official_result: AtBatResult = AtBatResult.GROUND_OUT
    # An int, not a bool. This is what makes double plays representable.
    outs_recorded: int = 0
    runs_scored: int = 0
    # Runs the pitcher is charged with. Every run charged the pitcher in
    # v0.3, which left ERA systematically high; Phase 3 makes this differ
    # from runs_scored.
    earned_runs: int = 0
    advancements: List[Advancement] = field(default_factory=list)
    rbi_credited: int = 0
    description: str = ""

    # Scoring classifications, set by OfficialScorer.
    is_sacrifice_fly: bool = False
    is_sacrifice_hit: bool = False
    is_double_play: bool = False
    is_triple_play: bool = False
    is_fielders_choice: bool = False

    @property
    def pitches(self) -> int:
        return len(self.pitch_history)

    # v0.1 play-by-play compatibility.
    @property
    def result(self) -> AtBatResult:
        return self.official_result

    def __str__(self) -> str:
        return self.description
