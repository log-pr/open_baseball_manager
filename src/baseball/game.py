"""Half-innings and full games.

HalfInning is where the engines get composed. It owns the base state and is
the only thing that mutates it; everything else hands it value objects.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field, replace
from typing import List, Optional

from .at_bat import AtBat
from .config import DEFAULT_CONFIG, DEFAULT_PARK, ParkConfig, SimulationConfig
from .engines import (
    BaserunningEngine,
    BattingEngine,
    FieldingEngine,
    OfficialScorer,
    PitchingEngine,
)
from .enums import PitchCall
from .events import BaserunningResult, Play
from .player import Player
from .state import BaseRunners, Situation
from .team import Team


@dataclass
class Engines:
    """The five engines, built once and shared across a game."""

    pitching: PitchingEngine
    batting: BattingEngine
    fielding: FieldingEngine
    baserunning: BaserunningEngine
    scorer: OfficialScorer

    @classmethod
    def build(
        cls,
        config: SimulationConfig = DEFAULT_CONFIG,
        park: ParkConfig = DEFAULT_PARK,
    ) -> "Engines":
        return cls(
            pitching=PitchingEngine(config),
            batting=BattingEngine(config),
            fielding=FieldingEngine(config, park),
            baserunning=BaserunningEngine(config),
            scorer=OfficialScorer(config),
        )


@dataclass
class GameResult:
    """Final score plus everything that happened."""

    home_team: Team
    away_team: Team
    home_score: int
    away_score: int
    innings_played: int
    plays: List[Play] = field(default_factory=list)

    @property
    def winner(self) -> Optional[Team]:
        if self.home_score > self.away_score:
            return self.home_team
        if self.away_score > self.home_score:
            return self.away_team
        return None

    def line_score(self) -> str:
        return (
            f"{self.away_team.name} {self.away_score} - "
            f"{self.home_score} {self.home_team.name} "
            f"({self.innings_played} innings)"
        )


@dataclass
class HalfInning:
    """One half-inning: bat until three outs.

    The composition sequence per plate appearance is:

      1. snapshot the Situation
      2. AtBat.simulate()            -> PlateAppearanceOutcome
      3. FieldingEngine.resolve()    -> FieldingResult  (did anyone catch it)
      4. BaserunningEngine.advance() -> advancements, runs, outs
      5. OfficialScorer.score()      -> AtBatResult, RBI
      6. assemble the Play, apply advancements, increment outs

    Each arrow is a testable seam: the failing stage tells you which engine
    broke.
    """

    batting_team: Team
    defending_team: Team
    rng: random.Random
    inning: int = 1
    half: str = "top"
    config: SimulationConfig = DEFAULT_CONFIG
    park: ParkConfig = DEFAULT_PARK
    engines: Optional[Engines] = None
    score_differential: int = 0

    outs: int = 0
    runs: int = 0
    base_runners: BaseRunners = field(default_factory=BaseRunners)
    plays: List[Play] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.engines is None:
            self.engines = Engines.build(self.config, self.park)

    def situation(self) -> Situation:
        """An immutable snapshot. Engines cannot mutate the game through it."""
        return Situation(
            inning=self.inning,
            half=self.half,
            outs=self.outs,
            base_runners=self.base_runners.snapshot(),
            score_differential=self.score_differential,
        )

    def play(self, max_runs: Optional[int] = None) -> int:
        """Play until three outs. Returns runs scored."""
        while self.outs < 3:
            self._attempt_steal()

            # Go to the bullpen if the current arm is gassed.
            if self.defending_team.needs_relief():
                self.defending_team.bring_in_reliever()

            batter = self.batting_team.next_batter()
            pitcher = self.defending_team.current_pitcher
            assert pitcher is not None

            self.plays.append(self._plate_appearance(batter, pitcher))

            # Walk-off: stop the moment the home team goes ahead.
            if max_runs is not None and self.runs >= max_runs:
                break

        return self.runs

    def _plate_appearance(self, batter: Player, pitcher: Player) -> Play:
        engines = self.engines
        assert engines is not None
        situation = self.situation()

        at_bat = AtBat(
            batter=batter,
            pitcher=pitcher,
            pitcher_state=self.defending_team.state_for(pitcher),
            rng=self.rng,
            config=self.config,
            pitching_engine=engines.pitching,
            batting_engine=engines.batting,
        )
        outcome = at_bat.simulate(situation)

        fielding_result = None
        if outcome.terminal_call is PitchCall.IN_PLAY:
            assert outcome.batted_ball is not None
            fielding_result = engines.fielding.resolve(
                outcome.batted_ball, self.defending_team, situation, self.rng
            )
            baserunning = engines.baserunning.advance(
                batter,
                fielding_result,
                outcome.batted_ball,
                self.base_runners,
                self.outs,
                self.rng,
            )
        elif outcome.terminal_call in (PitchCall.BALL, PitchCall.HIT_BY_PITCH):
            baserunning = engines.baserunning.force_advance(batter, self.base_runners)
        else:
            baserunning = BaserunningResult(outs_recorded=1)

        decision = engines.scorer.score(
            outcome.terminal_call,
            outcome.batted_ball,
            fielding_result,
            baserunning if fielding_result is not None else None,
            situation,
        )

        play = Play(
            batter=batter,
            pitcher=pitcher,
            pitch_history=outcome.pitch_history,
            batted_ball=outcome.batted_ball,
            fielding_result=fielding_result,
            official_result=decision.result,
            outs_recorded=baserunning.outs_recorded,
            runs_scored=baserunning.runs_scored,
            advancements=baserunning.advancements,
            rbi_credited=baserunning.runs_scored,
        )

        self._apply(baserunning)
        engines.scorer.apply_to_stats(play, self.batting_team, self.defending_team)

        # Play is frozen, so the play-by-play line is attached by rebuilding.
        return replace(play, description=self._describe(play))

    # --- Applying a result to the base state ------------------------------

    def _apply(self, result: BaserunningResult) -> None:
        """The only place BaseRunners is mutated."""
        self.base_runners.apply(result)
        self.outs += result.outs_recorded
        self.runs += result.runs_scored

    # --- Baserunning ------------------------------------------------------

    def _attempt_steal(self) -> None:
        assert self.engines is not None
        result = self.engines.baserunning.attempt_steal(
            self.base_runners, self.defending_team, self.rng
        )
        if result is not None:
            self._apply(result)

    # --- Description ------------------------------------------------------

    def _describe(self, play: Play) -> str:
        label = play.official_result.name.replace("_", " ").title()
        detail = ""
        if play.batted_ball is not None:
            bb = play.batted_ball
            detail = (
                f" [{bb.exit_velocity:.0f} mph, {bb.launch_angle:.0f} deg, "
                f"{bb.distance:.0f} ft]"
            )
        runs = play.runs_scored
        rbi = f" ({runs} run{'s' if runs != 1 else ''} score)" if runs else ""
        return (
            f"  {play.batter.name}: {label} on {play.pitches} pitches"
            f"{detail}{rbi} -- {self.outs} out, {self.base_runners}"
        )


@dataclass
class Game:
    """A full game between two teams."""

    home_team: Team
    away_team: Team
    rng: random.Random = field(default_factory=random.Random)
    config: SimulationConfig = DEFAULT_CONFIG
    park: ParkConfig = DEFAULT_PARK
    regulation_innings: int = 9

    home_score: int = 0
    away_score: int = 0
    inning_counter: int = 0  # half-innings elapsed; encodes inning and top/bottom
    engines: Optional[Engines] = None

    def __post_init__(self) -> None:
        if self.engines is None:
            self.engines = Engines.build(self.config, self.park)

    @property
    def inning(self) -> int:
        return self.inning_counter // 2 + 1

    @property
    def is_top(self) -> bool:
        return self.inning_counter % 2 == 0

    @classmethod
    def start(
        cls,
        home: Team,
        away: Team,
        rng: Optional[random.Random] = None,
        config: SimulationConfig = DEFAULT_CONFIG,
        park: ParkConfig = DEFAULT_PARK,
    ) -> "Game":
        home.validate()
        away.validate()
        # Everybody starts the game fresh.
        for team in (home, away):
            for player in list(team.fielding_positions) + team.bullpen:
                team.state_for(player).reset()
            if team.starting_pitcher is not None:
                team.current_pitcher = team.starting_pitcher
        return cls(
            home_team=home,
            away_team=away,
            rng=rng or random.Random(),
            config=config,
            park=park,
        )

    def simulate(self, verbose: bool = False) -> GameResult:
        """Play to completion, including extra innings if tied."""
        plays: List[Play] = []

        while True:
            inning = self.inning
            top = self.is_top
            batting = self.away_team if top else self.home_team
            defending = self.home_team if top else self.away_team

            # Home team doesn't bat in the bottom of the last inning if ahead.
            if (
                not top
                and inning >= self.regulation_innings
                and self.home_score > self.away_score
            ):
                break

            # Walk-off: stop as soon as the home team takes the lead.
            max_runs = None
            if not top and inning >= self.regulation_innings:
                max_runs = self.away_score - self.home_score + 1

            half = HalfInning(
                batting_team=batting,
                defending_team=defending,
                rng=self.rng,
                inning=inning,
                half="top" if top else "bottom",
                config=self.config,
                park=self.park,
                engines=self.engines,
                score_differential=(
                    self.away_score - self.home_score
                    if top
                    else self.home_score - self.away_score
                ),
            )
            runs = half.play(max_runs=max_runs)
            plays.extend(half.plays)

            if verbose:
                side = "Top" if top else "Bottom"
                print(f"\n{side} {inning} -- {batting.name}")
                for play in half.plays:
                    print(play)
                print(f"  {runs} run(s). Score: {self.away_score + (runs if top else 0)}"
                      f"-{self.home_score + (0 if top else runs)}")

            if top:
                self.away_score += runs
            else:
                self.home_score += runs

            self.inning_counter += 1

            # Game over after a completed bottom half at or past regulation.
            if (
                not top
                and inning >= self.regulation_innings
                and self.home_score != self.away_score
            ):
                break

            if self.inning_counter > 60:  # safety valve against runaway loops
                break

        return GameResult(
            home_team=self.home_team,
            away_team=self.away_team,
            home_score=self.home_score,
            away_score=self.away_score,
            innings_played=self.inning_counter // 2 + (self.inning_counter % 2),
            plays=plays,
        )
