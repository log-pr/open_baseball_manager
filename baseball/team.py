"""The nine players taking the field today, plus who's warming up.

Team is deliberately lean: it is "the roster playing this game," not a
persistent franchise. Season, standings, and trades get built on top.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .enums import Position
from .player import Player, PlayerStats
from .state import Lineup, PlayerGameState

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
    bullpen: List[Player] = field(default_factory=list)
    game_states: Dict[Player, PlayerGameState] = field(default_factory=dict)
    stats: Dict[Player, PlayerStats] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.name

    def __hash__(self) -> int:
        return id(self)

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
        return state.pitches_thrown > self.current_pitcher.pitching.stamina

    def bring_in_reliever(self) -> Optional[Player]:
        """Go to the pen. Returns the new pitcher, or None if it's empty.

        Not optional polish: without a bullpen one arm absorbs the whole
        game, fatigue snowballs, and starters throw 180 pitches and walk 10.
        """
        if not self.bullpen:
            return None
        reliever = self.bullpen.pop(0)
        self.state_for(reliever).reset()
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
            bullpen=bullpen,
        )
