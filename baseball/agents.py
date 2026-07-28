"""Manager agents: the things that answer a Decision.

Every team in v0.4 is managed by an `AIManager`. v0.5 adds `HumanManager`
against this same interface, which is the whole reason the contract exists
now rather than later -- if it is right, adding a human is purely additive
and touches no engine code.

`RandomManager` is not a toy. It is the control arm for `DecisionsMatter`:
if a competent manager cannot beat random choices with identical rosters,
manager decisions are cosmetic and the entire layer is decoration.
"""

from __future__ import annotations

import random
from typing import Callable, Dict, Optional

from .decisions import Decision, Option
from .enums import DecisionKind


class ManagerAgent:
    """Interface. Given a decision, pick one of its options."""

    name: str = "manager"

    def decide(self, decision: Decision) -> Option:  # pragma: no cover
        raise NotImplementedError

    def __str__(self) -> str:
        return self.name


class AIManager(ManagerAgent):
    """Heuristic manager. Every team in v0.4 uses one.

    Phase 1 is deliberately a skeleton: it answers every decision with the
    default. The heuristics arrive in Phase 5, one vertical slice per
    mechanic, each with a calibration row that polices it -- a manager who
    bunts constantly or burns his bullpen fails calibration immediately, so
    no separate evaluation harness is needed.
    """

    name = "ai"

    def __init__(self, rng: Optional[random.Random] = None) -> None:
        self.rng = rng or random.Random()
        # Per-kind heuristics, registered in Phase 5. Anything absent falls
        # through to the decision's own default.
        self._heuristics: Dict[DecisionKind, Callable[[Decision], Option]] = {}

    def register(
        self, kind: DecisionKind, heuristic: Callable[[Decision], Option]
    ) -> None:
        self._heuristics[kind] = heuristic

    def decide(self, decision: Decision) -> Option:
        heuristic = self._heuristics.get(decision.kind)
        if heuristic is None:
            return decision.default
        return heuristic(decision)


class ScriptedManager(ManagerAgent):
    """Test double. Answers by kind from a fixed script.

    Used to force situations that are rare in ordinary play -- bunt every
    plate appearance, steal on every pitch -- and confirm the result is
    still a legal game.
    """

    name = "scripted"

    def __init__(self, answers: Optional[Dict[DecisionKind, str]] = None) -> None:
        self.answers = answers or {}

    def decide(self, decision: Decision) -> Option:
        label = self.answers.get(decision.kind)
        if label is None:
            return decision.default
        return decision.option_labeled(label)


class RandomManager(ManagerAgent):
    """Uniform choice among legal options. The control arm."""

    name = "random"

    def __init__(self, rng: Optional[random.Random] = None) -> None:
        self.rng = rng or random.Random()

    def decide(self, decision: Decision) -> Option:
        return self.rng.choice(decision.options)
