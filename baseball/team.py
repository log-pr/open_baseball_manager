"""The nine players taking the field today, plus who's warming up.

Team is deliberately lean: it is "the roster playing this game," not a
persistent franchise. Season, standings, and trades get built on top.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .config import DEFAULT_CONFIG, SimulationConfig
from .enums import DefensiveAlignment, OutfieldDepth, Position
from .player import Player, PlayerStats
from .state import BullpenSlot, GameRoster, Lineup, PlayerGameState

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
class Team:
    """A team as it exists for one game."""

    name: str
    lineup: Lineup = field(default_factory=Lineup)
    fielding_positions: Dict[Player, Position] = field(default_factory=dict)
    starting_pitcher: Optional[Player] = None
    current_pitcher: Optional[Player] = None
    roster: GameRoster = field(default_factory=GameRoster)
    bullpen_slot: BullpenSlot = field(default_factory=BullpenSlot)
    game_states: Dict[Player, PlayerGameState] = field(default_factory=dict)
    stats: Dict[Player, PlayerStats] = field(default_factory=dict)

    # Defensive posture. Infield is changeable between pitches; outfield at
    # the plate-appearance boundary.
    infield_alignment: DefensiveAlignment = DefensiveAlignment.NORMAL
    outfield_depth: OutfieldDepth = OutfieldDepth.NORMAL
    mound_visits_remaining: int = 5

    def __str__(self) -> str:
        return self.name

    def __hash__(self) -> int:
        return id(self)

    @property
    def bullpen(self) -> List[Player]:
        """Availability lives on the roster; this is the reading of it."""
        return self.roster.bullpen

    @property
    def bench(self) -> List[Player]:
        return self.roster.bench

    def next_batter(self) -> Player:
        return self.lineup.next_batter()

    def state_for(self, player: Player) -> PlayerGameState:
        return self.game_states.setdefault(player, PlayerGameState(player=player))

    def stats_for(self, player: Player) -> PlayerStats:
        return self.stats.setdefault(player, PlayerStats())

    def needs_relief(self) -> bool:
        """Has the current pitcher run past his stamina with arms left?"""
        if self.current_pitcher is None or not self.bullpen:
            return False
        state = self.state_for(self.current_pitcher)
        # fatigue_load, not the box-score count: warm-up throws tire an arm
        # even though they never appear in a pitch line.
        return state.fatigue_load > self.current_pitcher.pitching.stamina

    def bring_in_reliever(self) -> Optional[Player]:
        """Go to the pen. Returns the new pitcher, or None if it's empty.

        Not optional polish: without a bullpen one arm absorbs the whole
        game, fatigue snowballs, and starters throw 180 pitches and walk 10.
        """
        available = self.roster.available_pitchers()
        if not available:
            return None
        reliever = available[0]
        self.roster.bullpen.remove(reliever)
        # The slot frees the instant he enters: using the hot arm means the
        # next one starts from zero.
        self.bullpen_slot.vacate(reliever)
        state = self.state_for(reliever)
        state.reset()
        # Locked in at entry and held through the half-inning he entered.
        state.entry_warmth = state.warmth
        if self.current_pitcher is not None:
            self.roster.mark_used(self.current_pitcher)
        self.current_pitcher = reliever
        self.fielding_positions[reliever] = Position.RP
        return reliever

    def validate(self) -> None:
        """Raise if this isn't a legal lineup. Cheap insurance against typos."""
        try:
            self.lineup.validate()
        except ValueError as exc:
            raise ValueError(f"{self.name}: {exc}") from exc
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
        """Build a random nine plus a starting pitcher and a bullpen.

        talent_bonus shifts every grade, which makes it easy to build a
        deliberately good or bad opponent for testing.
        """
        offset = level_offset + talent_bonus
        batting_order: List[Player] = []
        positions: Dict[Player, Position] = {}

        for i, position in enumerate(DEFENSIVE_ALIGNMENT):
            player = Player.generate(
                rng,
                name=f"{name} Batter {i + 1}",
                position=position,
                level_offset=offset,
            )
            batting_order.append(player)
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
            lineup=Lineup(batting_order=batting_order),
            fielding_positions=positions,
            starting_pitcher=pitcher,
            current_pitcher=pitcher,
            roster=GameRoster(bullpen=bullpen),
        )
