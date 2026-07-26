"""Shared enums and constants for the baseball simulation.

Everything in here is deliberately dependency-free so it can be imported
from any layer without circular imports.
"""

from enum import Enum, auto


class Position(Enum):
    C = "C"
    FIRST = "1B"
    SECOND = "2B"
    THIRD = "3B"
    SS = "SS"
    LF = "LF"
    CF = "CF"
    RF = "RF"
    DH = "DH"
    SP = "SP"
    RP = "RP"
    CL = "CL"

    def __str__(self) -> str:
        return self.value


class PitchType(Enum):
    FOUR_SEAM = "4-Seam Fastball"
    TWO_SEAM = "2-Seam Fastball"
    CURVEBALL = "Curveball"
    SLIDER = "Slider"
    CHANGEUP = "Changeup"

    def __str__(self) -> str:
        return self.value


class PitchCall(Enum):
    """The result of a single pitch."""

    BALL = auto()
    CALLED_STRIKE = auto()
    SWINGING_STRIKE = auto()
    FOUL = auto()
    HIT_BY_PITCH = auto()
    IN_PLAY = auto()


class SwingOutcome(Enum):
    """What happened when the batter offered at the pitch."""

    WHIFF = auto()
    FOUL = auto()
    CONTACT = auto()


class FieldingOutcome(Enum):
    """What the defense physically did.

    Deliberately not "hit" or "error" -- those are scoring judgments, made
    by OfficialScorer from one of these plus the base state.
    """

    CAUGHT = auto()
    FIELDED_CLEANLY = auto()
    MISPLAYED = auto()  # got to it and botched it
    THROUGH_INFIELD = auto()  # grounder got past everyone
    DROPPED_IN = auto()  # air ball landed safely
    OVER_THE_FENCE = auto()
    FOUL = auto()


class AtBatResult(Enum):
    """The result of a completed plate appearance."""

    STRIKEOUT = auto()
    WALK = auto()
    HIT_BY_PITCH = auto()
    SINGLE = auto()
    DOUBLE = auto()
    TRIPLE = auto()
    HOME_RUN = auto()
    GROUND_OUT = auto()
    FLY_OUT = auto()
    LINE_OUT = auto()
    POP_OUT = auto()
    ERROR = auto()
    FIELDERS_CHOICE = auto()
    # NOT PRODUCED. A runner tagging from third scores, but the play is
    # recorded as FLY_OUT, so it wrongly counts as an official at-bat.
    # Known defect carried forward from v0.1; see README "Known limitations".
    SAC_FLY = auto()

    @property
    def is_hit(self) -> bool:
        return self in _HITS

    @property
    def is_out(self) -> bool:
        return self in _OUTS

    @property
    def is_at_bat(self) -> bool:
        """Walks, HBP and sacrifices don't count as official at-bats."""
        return self not in (
            AtBatResult.WALK,
            AtBatResult.HIT_BY_PITCH,
            AtBatResult.SAC_FLY,
        )

    @property
    def bases(self) -> int:
        """Total bases for a hit (0 for anything else)."""
        return _BASES.get(self, 0)


_HITS = frozenset(
    {
        AtBatResult.SINGLE,
        AtBatResult.DOUBLE,
        AtBatResult.TRIPLE,
        AtBatResult.HOME_RUN,
    }
)

_OUTS = frozenset(
    {
        AtBatResult.STRIKEOUT,
        AtBatResult.GROUND_OUT,
        AtBatResult.FLY_OUT,
        AtBatResult.LINE_OUT,
        AtBatResult.POP_OUT,
        AtBatResult.FIELDERS_CHOICE,
        AtBatResult.SAC_FLY,
    }
)

_BASES = {
    AtBatResult.SINGLE: 1,
    AtBatResult.DOUBLE: 2,
    AtBatResult.TRIPLE: 3,
    AtBatResult.HOME_RUN: 4,
}


# --- Field geometry / physics constants (feet, seconds, mph) ---

PLATE_HALF_WIDTH_FT = 0.83  # 17" plate plus a ball's width of forgiveness
ZONE_BOTTOM_FT = 1.55
ZONE_TOP_FT = 3.45
GRAVITY_FT_S2 = 32.174
MPH_TO_FPS = 1.467

INFIELD_DEPTH_FT = 145.0  # typical fielding depth for infielders
OUTFIELD_DEPTH_FT = 290.0  # typical fielding depth for outfielders
WALL_DISTANCE_FT = 385.0  # simplified uniform outfield wall


# --- Scouting scale helpers ---

GRADE_MIN = 20
GRADE_MAX = 80
GRADE_AVG = 50


def grade_to_unit(grade: float) -> float:
    """Map a 20-80 scouting grade onto a 0.0-1.0 scale.

    50 (major league average) lands at 0.5.
    """
    return max(0.0, min(1.0, (grade - GRADE_MIN) / (GRADE_MAX - GRADE_MIN)))


def grade_to_z(grade: float) -> float:
    """Map a 20-80 grade to standard deviations from average.

    The scale is built so each 10-point step is roughly one standard
    deviation, so a 70 grade is +2 and a 30 grade is -2.
    """
    return (grade - GRADE_AVG) / 10.0
