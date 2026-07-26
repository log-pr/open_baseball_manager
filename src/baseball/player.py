"""Player and the four scouting profiles that describe him.

Ratings are split into four small profile objects rather than one flat
attribute bag. That mirrors how real scouting reports are organized (by
tool) and means each profile can be generated, tested, and later trained
independently.

Grades use the industry-standard 20-80 scale, where 50 is major league
average and each 10 points is roughly one standard deviation.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import List, Optional

from .enums import (
    GRADE_AVG,
    GRADE_MAX,
    GRADE_MIN,
    AtBatResult,
    PitchType,
    Position,
    grade_to_z,
)

# Positions that take the field as a position player.
FIELDING_POSITIONS = [
    Position.C,
    Position.FIRST,
    Position.SECOND,
    Position.THIRD,
    Position.SS,
    Position.LF,
    Position.CF,
    Position.RF,
]

PITCHING_POSITIONS = [Position.SP, Position.RP, Position.CL]

# Baseline velocity (mph) and spin (rpm) per pitch type for a 50-grade arm.
PITCH_BASELINES = {
    PitchType.FOUR_SEAM: (93.5, 2300),
    PitchType.TWO_SEAM: (92.0, 2150),
    PitchType.CURVEBALL: (79.0, 2550),
    PitchType.SLIDER: (85.0, 2400),
    PitchType.CHANGEUP: (85.5, 1800),
}


def _clamp_grade(value: float) -> int:
    return int(max(GRADE_MIN, min(GRADE_MAX, round(value))))


def _roll_grade(rng: random.Random, center: float = GRADE_AVG, spread: float = 10.0) -> int:
    """Draw a grade from a normal distribution, clamped to the 20-80 scale."""
    return _clamp_grade(rng.gauss(center, spread))


@dataclass
class HittingProfile:
    """Offensive tools.

    hit_grade    - contact ability / bat-to-ball skill
    power_grade  - raw power, drives bat speed and therefore exit velocity
    eye_grade    - plate discipline; how well he lays off pitches out of the zone
    bat_speed    - mph at the sweet spot at contact
    attack_angle - vertical swing plane in degrees (MLB average is about 10,
                   with roughly 5-20 being the productive range)
    swing_length - feet the bat travels to contact; longer swings trade
                   contact for power
    pull_tendency- -1.0 (pulls everything) to +1.0 (all opposite field)
    """

    hit_grade: int = GRADE_AVG
    power_grade: int = GRADE_AVG
    eye_grade: int = GRADE_AVG
    bat_speed: float = 71.5
    attack_angle: float = 10.0
    swing_length: float = 7.3
    pull_tendency: float = 0.0

    @classmethod
    def generate(cls, rng: random.Random, level_offset: float = 0.0) -> "HittingProfile":
        power = _roll_grade(rng, GRADE_AVG + level_offset)
        # Bat speed is driven by the power tool: 50 power -> ~71.5 mph.
        bat_speed = 71.5 + grade_to_z(power) * 2.6 + rng.gauss(0, 0.8)
        return cls(
            hit_grade=_roll_grade(rng, GRADE_AVG + level_offset),
            power_grade=power,
            eye_grade=_roll_grade(rng, GRADE_AVG + level_offset),
            bat_speed=round(bat_speed, 1),
            attack_angle=round(rng.gauss(10.0, 4.0), 1),
            swing_length=round(rng.gauss(7.3, 0.6), 2),
            pull_tendency=round(rng.gauss(-0.15, 0.35), 2),
        )


@dataclass
class PitchArsenalEntry:
    """One pitch in a pitcher's repertoire."""

    pitch_type: PitchType
    velocity: float  # mph, this pitcher's average for this pitch
    spin_rate: float  # rpm
    grade: int = GRADE_AVG  # 20-80 quality of the offering

    def __str__(self) -> str:
        return f"{self.pitch_type} ({self.velocity:.1f} mph, {self.spin_rate:.0f} rpm, {self.grade} grade)"


@dataclass
class PitchingProfile:
    """Pitching tools.

    control_grade - ability to throw strikes at all (accuracy)
    command_grade - ability to hit the specific intended spot (precision)
    extension     - release distance toward the plate in feet; longer
                    extension makes a given velocity play up
    stamina       - pitches thrown before velocity and command start to fade
    """

    repertoire: List[PitchArsenalEntry] = field(default_factory=list)
    control_grade: int = GRADE_AVG
    command_grade: int = GRADE_AVG
    extension: float = 6.4
    stamina: int = 95

    @classmethod
    def generate(
        cls,
        rng: random.Random,
        position: Position = Position.SP,
        level_offset: float = 0.0,
    ) -> "PitchingProfile":
        arm = _roll_grade(rng, GRADE_AVG + level_offset)
        # Relievers throw harder but carry fewer pitches and less stamina.
        is_reliever = position in (Position.RP, Position.CL)
        velo_bump = 1.5 if is_reliever else 0.0

        types = [PitchType.FOUR_SEAM]
        secondary = [
            PitchType.SLIDER,
            PitchType.CURVEBALL,
            PitchType.CHANGEUP,
            PitchType.TWO_SEAM,
        ]
        rng.shuffle(secondary)
        types += secondary[: (2 if is_reliever else 3)]

        repertoire = []
        for pitch_type in types:
            base_velo, base_spin = PITCH_BASELINES[pitch_type]
            repertoire.append(
                PitchArsenalEntry(
                    pitch_type=pitch_type,
                    velocity=round(base_velo + grade_to_z(arm) * 1.8 + velo_bump + rng.gauss(0, 0.7), 1),
                    spin_rate=round(base_spin + rng.gauss(0, 180)),
                    grade=_roll_grade(rng, GRADE_AVG + level_offset, spread=8.0),
                )
            )

        return cls(
            repertoire=repertoire,
            control_grade=_roll_grade(rng, GRADE_AVG + level_offset),
            command_grade=_roll_grade(rng, GRADE_AVG + level_offset),
            extension=round(rng.gauss(6.4, 0.4), 2),
            stamina=int(rng.gauss(55 if is_reliever else 95, 12)),
        )


@dataclass
class FieldingProfile:
    """Defensive tools.

    field_grade - range, hands, and instincts rolled into one grade, which
                  is the standard scouting convention
    arm_grade   - throwing strength and accuracy
    """

    field_grade: int = GRADE_AVG
    arm_grade: int = GRADE_AVG

    @property
    def error_rate(self) -> float:
        """Probability of botching a routine play.

        An average (50) fielder sits around 2%, an 80 near 0.5%, a 20 near 6%.
        """
        return max(0.004, 0.022 - grade_to_z(self.field_grade) * 0.007)

    @classmethod
    def generate(cls, rng: random.Random, level_offset: float = 0.0) -> "FieldingProfile":
        return cls(
            field_grade=_roll_grade(rng, GRADE_AVG + level_offset),
            arm_grade=_roll_grade(rng, GRADE_AVG + level_offset),
        )


@dataclass
class RunningProfile:
    """Baserunning tools.

    sprint_speed - feet per second in the fastest one-second window. The
                   real competitive range runs from about 23 (poor) to 30
                   (elite), with roughly 27 being average.
    """

    run_grade: int = GRADE_AVG
    sprint_speed: float = 27.0
    steal_aggression: float = 0.05
    steal_success_grade: int = GRADE_AVG

    @property
    def steal_success_rate(self) -> float:
        return max(0.35, min(0.95, 0.72 + grade_to_z(self.steal_success_grade) * 0.06))

    @classmethod
    def generate(cls, rng: random.Random, level_offset: float = 0.0) -> "RunningProfile":
        run = _roll_grade(rng, GRADE_AVG + level_offset)
        speed = 27.0 + grade_to_z(run) * 1.2 + rng.gauss(0, 0.3)
        # Faster players attempt more steals.
        aggression = max(0.0, min(0.30, 0.05 + grade_to_z(run) * 0.035 + rng.gauss(0, 0.02)))
        return cls(
            run_grade=run,
            sprint_speed=round(speed, 1),
            steal_aggression=round(aggression, 3),
            steal_success_grade=_roll_grade(rng, GRADE_AVG + grade_to_z(run) * 3),
        )


@dataclass
class PlayerStats:
    """Observed results, as opposed to the hidden ratings that drive them.

    This split is the whole point of a manager game: you judge players by
    what you see, and what you see is a noisy sample of their true talent.

    Written by OfficialScorer, which is the natural producer -- scoring
    decisions are exactly what stats are made of.
    """

    at_bats: int = 0
    hits: int = 0
    doubles: int = 0
    triples: int = 0
    home_runs: int = 0
    walks: int = 0
    strikeouts: int = 0
    hit_by_pitch: int = 0
    rbi: int = 0
    runs: int = 0
    plate_appearances: int = 0

    # Pitching
    outs_recorded: int = 0
    earned_runs: int = 0
    strikeouts_pitched: int = 0
    walks_allowed: int = 0
    hits_allowed: int = 0

    # Fielding
    putouts: int = 0
    assists: int = 0
    errors: int = 0

    @property
    def batting_average(self) -> float:
        return self.hits / self.at_bats if self.at_bats else 0.0

    @property
    def on_base_percentage(self) -> float:
        denom = self.at_bats + self.walks + self.hit_by_pitch
        if not denom:
            return 0.0
        return (self.hits + self.walks + self.hit_by_pitch) / denom

    @property
    def slugging(self) -> float:
        if not self.at_bats:
            return 0.0
        singles = self.hits - self.doubles - self.triples - self.home_runs
        total = singles + 2 * self.doubles + 3 * self.triples + 4 * self.home_runs
        return total / self.at_bats

    @property
    def ops(self) -> float:
        return self.on_base_percentage + self.slugging

    @property
    def innings_pitched(self) -> float:
        return self.outs_recorded / 3.0

    @property
    def era(self) -> float:
        ip = self.innings_pitched
        return (self.earned_runs * 9.0 / ip) if ip else 0.0

    def record_result(self, result: AtBatResult) -> None:
        self.plate_appearances += 1
        if result.is_at_bat:
            self.at_bats += 1
        if result.is_hit:
            self.hits += 1
        if result is AtBatResult.DOUBLE:
            self.doubles += 1
        elif result is AtBatResult.TRIPLE:
            self.triples += 1
        elif result is AtBatResult.HOME_RUN:
            self.home_runs += 1
        elif result is AtBatResult.WALK:
            self.walks += 1
        elif result is AtBatResult.STRIKEOUT:
            self.strikeouts += 1
        elif result is AtBatResult.HIT_BY_PITCH:
            self.hit_by_pitch += 1


@dataclass(eq=False)  # identity-based equality so Players work as dict keys
class Player:
    """A single player: an identity plus four tool profiles."""

    name: str
    age: int = 27
    bats: str = "R"  # 'L', 'R', or 'S'
    throws: str = "R"  # 'L' or 'R'
    primary_position: Position = Position.CF
    hitting: HittingProfile = field(default_factory=HittingProfile)
    pitching: PitchingProfile = field(default_factory=PitchingProfile)
    fielding: FieldingProfile = field(default_factory=FieldingProfile)
    running: RunningProfile = field(default_factory=RunningProfile)

    def __str__(self) -> str:
        return f"{self.name} ({self.primary_position})"

    @property
    def is_pitcher(self) -> bool:
        return self.primary_position in PITCHING_POSITIONS

    def best_pitch(self) -> Optional[PitchArsenalEntry]:
        if not self.pitching.repertoire:
            return None
        return max(self.pitching.repertoire, key=lambda p: p.grade)

    @classmethod
    def generate(
        cls,
        rng: random.Random,
        name: str,
        position: Optional[Position] = None,
        level_offset: float = 0.0,
    ) -> "Player":
        """Create a random player.

        level_offset shifts the center of every grade distribution, which is
        the hook for different levels of play (tee ball through the majors).
        """
        position = position or rng.choice(FIELDING_POSITIONS)
        bats = rng.choices(["R", "L", "S"], weights=[0.60, 0.32, 0.08])[0]
        throws = "L" if (bats == "L" and rng.random() < 0.6) else "R"

        return cls(
            name=name,
            age=int(rng.gauss(27, 3.5)),
            bats=bats,
            throws=throws,
            primary_position=position,
            hitting=HittingProfile.generate(rng, level_offset),
            pitching=PitchingProfile.generate(rng, position, level_offset),
            fielding=FieldingProfile.generate(rng, level_offset),
            running=RunningProfile.generate(rng, level_offset),
        )

    def scouting_report(self) -> str:
        """A human-readable 20-80 scouting line."""
        h, f, r = self.hitting, self.fielding, self.running
        if self.is_pitcher:
            p = self.pitching
            arsenal = "\n    ".join(str(x) for x in p.repertoire)
            return (
                f"{self.name}  |  {self.primary_position}  |  Age {self.age}  |  Throws {self.throws}\n"
                f"  Control {p.control_grade}  Command {p.command_grade}  "
                f"Stamina {p.stamina} pitches  Extension {p.extension} ft\n"
                f"  Arsenal:\n    {arsenal}"
            )
        return (
            f"{self.name}  |  {self.primary_position}  |  Age {self.age}  |  Bats {self.bats}\n"
            f"  Hit {h.hit_grade}  Power {h.power_grade}  Eye {h.eye_grade}  "
            f"Run {r.run_grade}  Field {f.field_grade}  Arm {f.arm_grade}\n"
            f"  Bat speed {h.bat_speed} mph  Attack angle {h.attack_angle} deg  "
            f"Sprint {r.sprint_speed} ft/s"
        )
