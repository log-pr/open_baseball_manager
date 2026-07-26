"""Team, base runners, and stat accumulation.

Team is deliberately lean here: it is "the nine guys playing today," not a
persistent franchise. When rosters and seasons get built, this splits into
Team + Roster + Lineup, which is an additive change rather than a rewrite.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .config import DEFAULT_CONFIG, SimulationConfig
from .enums import AtBatResult, Position
from .player import Player

DEFENSIVE_ALIGNMENT = [
    Position.C,
    Position.FIRST,
    Position.SECOND,
    Position.THIRD,
    Position.SS,
    Position.LF,
    Position.CF,
    Position.RF,
    Position.DH,
]


@dataclass
class PlayerStats:
    """Observed results, as opposed to the hidden ratings that drive them.

    This split is the whole point of a manager game: you judge players by
    what you see, and what you see is a noisy sample of their true talent.
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


@dataclass
class BaseRunners:
    """Who is standing on which base."""

    first: Optional[Player] = None
    second: Optional[Player] = None
    third: Optional[Player] = None

    def __str__(self) -> str:
        occupied = [
            name
            for name, runner in (("1st", self.first), ("2nd", self.second), ("3rd", self.third))
            if runner is not None
        ]
        return ", ".join(occupied) if occupied else "bases empty"

    @property
    def count(self) -> int:
        return sum(1 for r in (self.first, self.second, self.third) if r is not None)

    @property
    def is_empty(self) -> bool:
        return self.count == 0

    def clear(self) -> None:
        self.first = self.second = self.third = None

    def advance_all(
        self,
        bases: int,
        batter: Optional[Player] = None,
        rng: Optional[random.Random] = None,
        config: SimulationConfig = DEFAULT_CONFIG,
    ) -> List[Player]:
        """Move runners up on a hit, returning those who scored.

        Runners don't just advance the same number of bases as the hit.
        A runner on second usually scores on a single and a runner on
        first often takes third, and how often depends on his speed. That
        extra base is worth roughly a run a game, so it isn't optional.
        """
        rng = rng or random.Random()
        scored: List[Player] = []
        # Work from third backward so runners don't overwrite each other.
        lineup = [(3, self.third), (2, self.second), (1, self.first)]
        self.clear()

        for base, runner in lineup:
            if runner is None:
                continue
            new_base = base + bases

            # Chance at one extra base, weighted by the runner's speed.
            if bases < 4 and new_base < 4:
                speed_edge = (
                    runner.running.sprint_speed - config.baserunning_speed_baseline
                ) * config.speed_weight
                if base == 2 and bases == 1:
                    # Second scores on a single.
                    extra = config.score_from_second_on_single + speed_edge
                elif base == 1 and bases == 1:
                    # First to third on a single.
                    extra = config.first_to_third_on_single + speed_edge
                elif base == 1 and bases == 2:
                    # First scores on a double.
                    extra = config.score_from_first_on_double + speed_edge
                else:
                    extra = config.extra_base_default + speed_edge
                if rng.random() < max(0.0, min(config.extra_base_max, extra)):
                    new_base += 1

            if new_base >= 4:
                scored.append(runner)
            else:
                self._place(runner, new_base)

        if batter is not None:
            if bases >= 4:
                scored.append(batter)
            else:
                self._place(batter, bases)

        return scored

    def _place(self, runner: Player, base: int) -> None:
        if base == 1:
            self.first = runner
        elif base == 2:
            self.second = runner
        elif base == 3:
            self.third = runner

    def force_advance(self, batter: Player) -> List[Player]:
        """Walk or HBP: runners move up only if forced."""
        scored: List[Player] = []
        if self.first is not None:
            if self.second is not None:
                if self.third is not None:
                    scored.append(self.third)
                self.third = self.second
            self.second = self.first
        self.first = batter
        return scored


@dataclass
class Team:
    """The nine players on the field today, plus the pitcher."""

    name: str
    lineup: List[Player] = field(default_factory=list)
    fielding_positions: Dict[Player, Position] = field(default_factory=dict)
    starting_pitcher: Optional[Player] = None
    current_pitcher: Optional[Player] = None
    bullpen: List[Player] = field(default_factory=list)
    current_batter_index: int = 0
    stats: Dict[Player, PlayerStats] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.name

    def __hash__(self) -> int:
        return id(self)

    def next_batter(self) -> Player:
        batter = self.lineup[self.current_batter_index]
        self.current_batter_index = (self.current_batter_index + 1) % len(self.lineup)
        return batter

    def stats_for(self, player: Player) -> PlayerStats:
        return self.stats.setdefault(player, PlayerStats())

    def needs_relief(self) -> bool:
        """Has the current pitcher run past his stamina with arms left?"""
        if self.current_pitcher is None or not self.bullpen:
            return False
        return self.current_pitcher.pitches_thrown > self.current_pitcher.pitching.stamina

    def bring_in_reliever(self) -> Optional[Player]:
        """Go to the pen. Returns the new pitcher, or None if it's empty."""
        if not self.bullpen:
            return None
        reliever = self.bullpen.pop(0)
        reliever.rest()
        self.current_pitcher = reliever
        self.fielding_positions[reliever] = Position.RP
        return reliever

    def validate(self) -> None:
        """Raise if this isn't a legal lineup. Cheap insurance against typos."""
        if len(self.lineup) != 9:
            raise ValueError(f"{self.name}: lineup has {len(self.lineup)} players, need 9")
        if len(set(id(p) for p in self.lineup)) != 9:
            raise ValueError(f"{self.name}: the same player appears twice in the lineup")
        if self.starting_pitcher is None:
            raise ValueError(f"{self.name}: no starting pitcher")
        if not self.starting_pitcher.pitching.repertoire:
            raise ValueError(f"{self.name}: starting pitcher has no pitches")

    @classmethod
    def generate(
        cls,
        rng: random.Random,
        name: str,
        level_offset: float = 0.0,
        talent_bonus: float = 0.0,
    ) -> "Team":
        """Build a random nine plus a starting pitcher.

        talent_bonus shifts every grade, which makes it easy to build a
        deliberately good or bad opponent for testing.
        """
        offset = level_offset + talent_bonus
        lineup: List[Player] = []
        positions: Dict[Player, Position] = {}

        for i, position in enumerate(DEFENSIVE_ALIGNMENT):
            player = Player.generate(
                rng,
                name=f"{name} Batter {i + 1}",
                position=position,
                level_offset=offset,
            )
            lineup.append(player)
            positions[player] = position

        pitcher = Player.generate(
            rng,
            name=f"{name} Pitcher",
            position=Position.SP,
            level_offset=offset,
        )
        positions[pitcher] = Position.SP

        bullpen = [
            Player.generate(
                rng,
                name=f"{name} Reliever {i + 1}",
                position=Position.RP,
                level_offset=offset,
            )
            for i in range(4)
        ]

        return cls(
            name=name,
            lineup=lineup,
            fielding_positions=positions,
            starting_pitcher=pitcher,
            current_pitcher=pitcher,
            bullpen=bullpen,
        )
