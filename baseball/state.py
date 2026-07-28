"""Per-game mutable state, and the immutable snapshot handed to engines.

The split this module exists to enforce: a Player is persistent and carries
no per-game state, so the same Player can appear in two simulations at once
without interference. Anything that changes during a game lives here.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import List, Optional

from .config import DEFAULT_CONFIG, SimulationConfig
from .player import Player


@dataclass
class PlayerGameState:
    """One player's mutable state for one game.

    In v0.1 `pitches_thrown` lived on Player, so it drifted across at-bats
    and across games: a pitcher reused in a second simulation started
    already exhausted and walked everyone.
    """

    player: Player
    pitches_thrown: int = 0

    def record_pitch(self) -> None:
        self.pitches_thrown += 1

    def reset(self) -> None:
        self.pitches_thrown = 0

    def fatigue(self, config: SimulationConfig = DEFAULT_CONFIG) -> float:
        """0.0 when fresh, rising once past the stamina limit.

        Capped: a gassed pitcher gets much worse but never becomes
        physically incapable of throwing a strike.
        """
        stamina = self.player.pitching.stamina
        if not stamina:
            return 0.0
        over = self.pitches_thrown - stamina
        return max(0.0, min(config.fatigue_cap, over / config.fatigue_pitches_scale))


@dataclass
class Lineup:
    """The batting order, and whose turn it is."""

    batting_order: List[Player] = field(default_factory=list)
    current_index: int = 0

    def __len__(self) -> int:
        return len(self.batting_order)

    def __iter__(self):
        return iter(self.batting_order)

    def __getitem__(self, index):
        return self.batting_order[index]

    def __setitem__(self, index, value) -> None:
        self.batting_order[index] = value

    def current_batter(self) -> Player:
        return self.batting_order[self.current_index]

    def next_batter(self) -> Player:
        batter = self.batting_order[self.current_index]
        self.current_index = (self.current_index + 1) % len(self.batting_order)
        return batter

    def substitute(self, player_out: Player, player_in: Player) -> None:
        for i, player in enumerate(self.batting_order):
            if player is player_out:
                self.batting_order[i] = player_in
                return
        raise ValueError(f"{player_out.name} is not in the batting order")

    def validate(self) -> None:
        if len(self.batting_order) != 9:
            raise ValueError(f"lineup has {len(self.batting_order)} players, need 9")
        if len({id(p) for p in self.batting_order}) != 9:
            raise ValueError("the same player appears twice in the lineup")


@dataclass(frozen=True)
class ForceState:
    """Which runners are forced to advance.

    Needed by BaserunningEngine and OfficialScorer: whether a fielded
    grounder is a fielder's choice, and whether a double play is even
    available, both depend on this rather than on the batted ball.
    """

    first: bool = False
    second: bool = False
    third: bool = False

    @property
    def lead_forced_base(self) -> Optional[int]:
        """The furthest base a forced runner is being pushed to."""
        if self.third:
            return 4
        if self.second:
            return 3
        if self.first:
            return 2
        return None


@dataclass
class BaseRunners:
    """Who is standing on which base.

    Mutated only by HalfInning, applying a BaserunningEngine result.
    """

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

    def occupied(self, base: int) -> bool:
        return self.runner_on(base) is not None

    def runner_on(self, base: int) -> Optional[Player]:
        return {1: self.first, 2: self.second, 3: self.third}.get(base)

    def force_state(self) -> ForceState:
        """A runner is forced only if every base behind him is occupied."""
        return ForceState(
            first=True,  # the batter always forces the runner on first
            second=self.first is not None,
            third=self.first is not None and self.second is not None,
        )

    def place(self, runner: Player, base: int) -> None:
        if base == 1:
            self.first = runner
        elif base == 2:
            self.second = runner
        elif base == 3:
            self.third = runner

    def remove(self, base: int) -> None:
        if base == 1:
            self.first = None
        elif base == 2:
            self.second = None
        elif base == 3:
            self.third = None

    def clear(self) -> None:
        self.first = self.second = self.third = None

    def apply(self, result) -> None:
        """Apply a BaserunningResult. The only path that moves runners.

        Vacate every origin base first, then fill destinations, so two
        runners moving up in the same play can't overwrite each other.
        """
        for advancement in result.advancements:
            if advancement.from_base > 0:
                self.remove(advancement.from_base)
        for advancement in result.advancements:
            if advancement.out or advancement.to_base >= 4:
                continue
            self.place(advancement.runner, advancement.to_base)

    def snapshot(self) -> "BaseRunners":
        """A copy, so a Situation can't be used to reach back into the game."""
        return BaseRunners(first=self.first, second=self.second, third=self.third)


@dataclass(frozen=True)
class Situation:
    """The immutable snapshot passed to engines.

    This is what replaces the v0.2 GameContext proposal. An engine gets what
    it needs to make a decision and cannot mutate the game through it.
    """

    inning: int = 1
    half: str = "top"
    outs: int = 0
    balls: int = 0
    strikes: int = 0
    base_runners: BaseRunners = field(default_factory=BaseRunners)
    score_differential: int = 0

    def with_count(self, balls: int, strikes: int) -> "Situation":
        return replace(self, balls=balls, strikes=strikes)
