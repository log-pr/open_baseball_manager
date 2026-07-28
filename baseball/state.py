"""Per-game mutable state, and the immutable snapshot handed to engines.

The split this module exists to enforce: a Player is persistent and carries
no per-game state, so the same Player can appear in two simulations at once
without interference. Anything that changes during a game lives here.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional, Set

from .config import DEFAULT_CONFIG, SimulationConfig
from .player import Player


@dataclass
class PlayerGameState:
    """One player's mutable state for one game.

    In v0.1 `pitches_thrown` lived on Player, so it drifted across at-bats
    and across games: a pitcher reused in a second simulation started
    already exhausted and walked everyone.

    **Two pitch counters, deliberately.** `game_pitches_thrown` drives the
    box score and counts only pitches thrown in the game.  `fatigue_load`
    drives the model and also absorbs bullpen warm-up throws at a discount.
    Merging them would report a reliever throwing 46 pitches when he threw
    16.
    """

    player: Player
    game_pitches_thrown: int = 0
    fatigue_load: float = 0.0
    # Clamped to 0..pitches_to_warm. COLD / WARMING / READY are derived from
    # this counter rather than stored, which is what makes a reliever pulled
    # from the slot at 22 and returned later resume at 19 with no re-entry
    # rule.
    warmth: int = 0
    # Warmth at the moment he entered the game. The cold-entry penalty locks
    # in here and holds through the end of the half-inning he entered.
    entry_warmth: int = 0

    def record_pitch(self) -> None:
        """A pitch thrown in the game: counts for both the box and the arm."""
        self.game_pitches_thrown += 1
        self.fatigue_load += 1.0

    def record_warmup_pitch(self, config: SimulationConfig = DEFAULT_CONFIG) -> None:
        """A pitch thrown in the bullpen: costs the arm, not the box score."""
        self.warmth = min(config.pitches_to_warm, self.warmth + 1)
        self.fatigue_load += config.warmup_fatigue_ratio

    def cool(self, config: SimulationConfig = DEFAULT_CONFIG) -> None:
        """Sitting down. Warmth bleeds off; no fatigue accrues."""
        self.warmth = max(0, self.warmth - 1)

    def reset(self, config: SimulationConfig = DEFAULT_CONFIG) -> None:
        self.game_pitches_thrown = 0
        self.fatigue_load = 0.0
        self.warmth = 0
        self.entry_warmth = 0

    def start_warm(self, config: SimulationConfig = DEFAULT_CONFIG) -> None:
        """The starting pitcher takes the mound ready, never using the slot."""
        self.warmth = config.pitches_to_warm
        self.entry_warmth = config.pitches_to_warm

    def is_ready(self, config: SimulationConfig = DEFAULT_CONFIG) -> bool:
        return self.warmth >= config.pitches_to_warm

    def warmth_label(self, config: SimulationConfig = DEFAULT_CONFIG) -> str:
        """Display only. The counter is the truth."""
        if self.warmth <= 0:
            return "COLD"
        if self.warmth >= config.pitches_to_warm:
            return "READY"
        return "WARMING"

    def cold_penalty_scale(self, config: SimulationConfig = DEFAULT_CONFIG) -> float:
        """0.0 for a fully warm entry, 1.0 for stone cold.

        Continuous rather than stepped, so there is no cliff between a
        reliever at 29 warmth and one at 30.
        """
        if config.pitches_to_warm <= 0:
            return 0.0
        unready = config.pitches_to_warm - self.entry_warmth
        return max(0.0, min(1.0, unready / config.pitches_to_warm))

    def fatigue(self, config: SimulationConfig = DEFAULT_CONFIG) -> float:
        """0.0 when fresh, rising once past the stamina limit.

        Capped: a gassed pitcher gets much worse but never becomes
        physically incapable of throwing a strike.
        """
        stamina = self.player.pitching.stamina
        if not stamina:
            return 0.0
        over = self.fatigue_load - stamina
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


@dataclass
class GameRoster:
    """Who is still available. Lineup handles order; this handles supply."""

    bench: List[Player] = field(default_factory=list)
    bullpen: List[Player] = field(default_factory=list)
    # A substituted player cannot re-enter. This is the rule that makes
    # bench depth a real constraint rather than a formality.
    used_players: Set[Player] = field(default_factory=set)

    def available_position_players(self) -> List[Player]:
        return [p for p in self.bench if p not in self.used_players]

    def available_pitchers(self) -> List[Player]:
        return [p for p in self.bullpen if p not in self.used_players]

    def mark_used(self, player: Player) -> None:
        self.used_players.add(player)

    def is_available(self, player: Player) -> bool:
        return player not in self.used_players


@dataclass
class BullpenSlot:
    """The bullpen mound. One pitcher at a time by default.

    Occupancy can change on any pitch. The slot frees the instant a
    reliever enters the game, so using your hot arm means starting the next
    one from zero -- which is what makes pitching changes self-limiting
    without a separate constraint.
    """

    capacity: int = 1
    occupants: List[Player] = field(default_factory=list)

    def is_occupied_by(self, player: Player) -> bool:
        return player in self.occupants

    def has_room(self) -> bool:
        return len(self.occupants) < self.capacity

    def assign(self, player: Player) -> None:
        if player in self.occupants:
            return
        if not self.has_room():
            raise ValueError(
                f"bullpen slot is full ({self.capacity}); vacate before assigning"
            )
        self.occupants.append(player)

    def vacate(self, player: Player) -> None:
        if player in self.occupants:
            self.occupants.remove(player)

    def clear(self) -> None:
        self.occupants.clear()

    def tick(
        self,
        states: Dict[Player, "PlayerGameState"],
        config: SimulationConfig = DEFAULT_CONFIG,
        active_pitcher: Optional[Player] = None,
    ) -> None:
        """One game pitch of the single clock that drives warming and cooling.

        Occupants gain warmth and fatigue load; everyone else cools. The
        pitcher currently on the mound is exempt -- he is neither warming
        nor going cold.
        """
        for player, state in states.items():
            if player is active_pitcher:
                continue
            if self.is_occupied_by(player):
                state.record_warmup_pitch(config)
            else:
                state.cool(config)


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
