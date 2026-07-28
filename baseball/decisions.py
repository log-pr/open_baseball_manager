"""The decision layer's value objects.

A `Decision` is a question put to a manager: what the choice is, what the
legal answers are, and what happens if nobody answers. `ManagerAgent`
implementations consume these; `StrategyEngine` produces them.

The constraint that shapes this module: `DecisionContext` exposes
`PlayerStats` and never a `*Profile`. The AI judges players on observed
results, which is exactly the constraint the human manager faces in v0.5.
If the AI could read `hit_grade` it would be playing a different, easier
game than the person it is meant to stand in for.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .enums import DecisionBoundary, DecisionKind
from .player import Player, PlayerStats
from .state import Situation


@dataclass(frozen=True)
class Option:
    """One legal answer to a decision."""

    label: str
    # Free-form payload the StrategyEngine understands: the reliever to
    # bring in, the base to steal, the alignment to shift to.
    payload: Any = None

    def __str__(self) -> str:
        return self.label


@dataclass(frozen=True)
class BullpenView:
    """Who is warming, and roughly how warm.

    Public information in a real game and a legitimate input to a manager's
    decisions, so both sides can see it. v0.5 shows this to the human and
    lets the AI read the human's bullpen in return.
    """

    warming: Dict[str, str] = field(default_factory=dict)  # name -> label

    def is_anyone_ready(self) -> bool:
        return any(label == "READY" for label in self.warming.values())


@dataclass(frozen=True)
class DecisionContext:
    """Everything an agent is allowed to see when deciding.

    Observed statistics only. No hidden ratings, for either side.
    """

    situation: Situation
    observed_stats: Dict[Player, PlayerStats] = field(default_factory=dict)
    opposing_bullpen: Optional[BullpenView] = None
    leverage: float = 0.0

    def stats_for(self, player: Player) -> PlayerStats:
        """Observed line for a player, empty if he has not appeared."""
        return self.observed_stats.get(player, PlayerStats())


@dataclass(frozen=True)
class Decision:
    """A question for a manager, with its legal answers."""

    kind: DecisionKind
    boundary: DecisionBoundary
    options: List[Option]
    default: Option
    context: Optional[DecisionContext] = None

    def __post_init__(self) -> None:
        if not self.options:
            raise ValueError(f"{self.kind.name} decision has no options")
        if self.default not in self.options:
            raise ValueError(
                f"{self.kind.name} default is not among its options"
            )

    def option_labeled(self, label: str) -> Option:
        for option in self.options:
            if option.label == label:
                return option
        raise KeyError(f"{self.kind.name} has no option {label!r}")


@dataclass(frozen=True)
class DecisionRecord:
    """One answered decision, in order."""

    boundary: DecisionBoundary
    kind: DecisionKind
    choice: str

    def __str__(self) -> str:
        return f"{self.boundary.name}/{self.kind.name}: {self.choice}"


@dataclass
class DecisionLog:
    """Every answer given during a game, in order.

    Seed plus decision log reproduces a game exactly. Built in v0.4 even
    though only the AI decides, because it is what lets v0.5 replay a
    human-played game without redesigning anything: the log records the
    answer, not who gave it.
    """

    records: List[DecisionRecord] = field(default_factory=list)

    def record(
        self, boundary: DecisionBoundary, kind: DecisionKind, choice: str
    ) -> None:
        self.records.append(DecisionRecord(boundary, kind, choice))

    def __len__(self) -> int:
        return len(self.records)

    def __iter__(self):
        return iter(self.records)

    def of_kind(self, kind: DecisionKind) -> List[DecisionRecord]:
        return [r for r in self.records if r.kind is kind]

    def count(self, kind: DecisionKind) -> int:
        return sum(1 for r in self.records if r.kind is kind)
