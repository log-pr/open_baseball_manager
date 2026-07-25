"""Half-innings and full games.

Once AtBat works, these layers are mostly bookkeeping: loop until three
outs, loop until nine innings, keep score.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .at_bat import AtBat
from .enums import AtBatResult, grade_to_z
from .player import Player
from .team import BaseRunners, Team


@dataclass
class PlayEvent:
    """One line of play-by-play."""

    inning: int
    half: str  # "top" or "bottom"
    batter: str
    pitcher: str
    result: AtBatResult
    pitches: int
    runs_scored: int
    description: str

    def __str__(self) -> str:
        return self.description


@dataclass
class GameResult:
    """Final score plus everything that happened."""

    home_team: Team
    away_team: Team
    home_score: int
    away_score: int
    innings_played: int
    play_by_play: List[PlayEvent] = field(default_factory=list)

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
    """One half-inning: bat until three outs."""

    batting_team: Team
    defending_team: Team
    rng: random.Random
    inning: int = 1
    half: str = "top"

    outs: int = 0
    runs: int = 0
    baserunners: BaseRunners = field(default_factory=BaseRunners)
    events: List[PlayEvent] = field(default_factory=list)

    def play(self, max_runs: Optional[int] = None) -> int:
        """Play until three outs. Returns runs scored."""
        while self.outs < 3:
            self._attempt_steal()

            # Go to the bullpen if the current arm is gassed. Without this
            # one pitcher absorbs the whole game and fatigue snowballs.
            if self.defending_team.needs_relief():
                self.defending_team.bring_in_reliever()

            batter = self.batting_team.next_batter()
            pitcher = self.defending_team.current_pitcher
            assert pitcher is not None

            at_bat = AtBat(
                batter=batter,
                pitcher=pitcher,
                defense=self.defending_team,
                rng=self.rng,
            )
            result = at_bat.simulate()
            runs_on_play = self._apply_result(batter, result)

            self.batting_team.stats_for(batter).record_result(result)
            self._record_pitching(pitcher, result, runs_on_play)

            self.events.append(
                PlayEvent(
                    inning=self.inning,
                    half=self.half,
                    batter=batter.name,
                    pitcher=pitcher.name,
                    result=result,
                    pitches=len(at_bat.pitches),
                    runs_scored=runs_on_play,
                    description=self._describe(batter, at_bat, result, runs_on_play),
                )
            )

            # Walk-off: stop the moment the home team goes ahead.
            if max_runs is not None and self.runs >= max_runs:
                break

        return self.runs

    # --- Result application ----------------------------------------------

    def _apply_result(self, batter: Player, result: AtBatResult) -> int:
        before = self.runs

        if result in (AtBatResult.WALK, AtBatResult.HIT_BY_PITCH):
            scored = self.baserunners.force_advance(batter)
            self._score(scored, batter)

        elif result is AtBatResult.STRIKEOUT:
            self.outs += 1

        elif result.is_hit:
            scored = self.baserunners.advance_all(result.bases, batter, self.rng)
            self._score(scored, batter)

        elif result is AtBatResult.ERROR:
            scored = self.baserunners.advance_all(1, batter, self.rng)
            self._score(scored, batter)

        elif result is AtBatResult.SAC_FLY:
            self.outs += 1
            if self.baserunners.third is not None:
                self._score([self.baserunners.third], batter)
                self.baserunners.third = None

        elif result is AtBatResult.GROUND_OUT:
            self.outs += 1
            # A runner on third usually scores on an infield out with
            # fewer than two outs.
            if self.outs < 3 and self.baserunners.third is not None:
                if self.rng.random() < 0.55:
                    self._score([self.baserunners.third], batter)
                    self.baserunners.third = None

        elif result in (AtBatResult.FLY_OUT, AtBatResult.LINE_OUT, AtBatResult.POP_OUT):
            self.outs += 1
            # Sacrifice fly: runner tags from third on a fly ball.
            if (
                result is AtBatResult.FLY_OUT
                and self.outs < 3
                and self.baserunners.third is not None
                and self.rng.random() < 0.50
            ):
                self._score([self.baserunners.third], batter)
                self.baserunners.third = None

        else:
            self.outs += 1

        return self.runs - before

    def _score(self, runners: List[Player], batter: Player) -> None:
        for runner in runners:
            self.runs += 1
            self.batting_team.stats_for(runner).runs += 1
        if runners:
            self.batting_team.stats_for(batter).rbi += len(runners)

    def _record_pitching(self, pitcher: Player, result: AtBatResult, runs: int) -> None:
        stats = self.defending_team.stats_for(pitcher)
        if result.is_out:
            stats.outs_recorded += 1
        if result is AtBatResult.STRIKEOUT:
            stats.strikeouts_pitched += 1
        elif result is AtBatResult.WALK:
            stats.walks_allowed += 1
        elif result.is_hit:
            stats.hits_allowed += 1
        stats.earned_runs += runs

    # --- Baserunning ------------------------------------------------------

    def _attempt_steal(self) -> None:
        """Runner on first (and second open) may try to take second."""
        runner = self.baserunners.first
        if runner is None or self.baserunners.second is not None:
            return
        if self.rng.random() >= runner.running.steal_aggression:
            return

        catcher_arm = 50
        for player, position in self.defending_team.fielding_positions.items():
            if position.value == "C":
                catcher_arm = player.fielding.arm_grade
                break

        success = runner.running.steal_success_rate - grade_to_z(catcher_arm) * 0.04
        if self.rng.random() < success:
            self.baserunners.first = None
            self.baserunners.second = runner
        else:
            self.baserunners.first = None
            self.outs += 1

    # --- Description ------------------------------------------------------

    def _describe(
        self, batter: Player, at_bat: AtBat, result: AtBatResult, runs: int
    ) -> str:
        label = result.name.replace("_", " ").title()
        detail = ""
        if at_bat.batted_ball is not None:
            bb = at_bat.batted_ball
            detail = (
                f" [{bb.exit_velocity:.0f} mph, {bb.launch_angle:.0f} deg, "
                f"{bb.distance:.0f} ft]"
            )
        rbi = f" ({runs} run{'s' if runs != 1 else ''} score)" if runs else ""
        return (
            f"  {batter.name}: {label} on {len(at_bat.pitches)} pitches"
            f"{detail}{rbi} -- {self.outs} out, {self.baserunners}"
        )


@dataclass
class Game:
    """A full game between two teams."""

    home_team: Team
    away_team: Team
    rng: random.Random = field(default_factory=random.Random)
    regulation_innings: int = 9

    home_score: int = 0
    away_score: int = 0
    inning_counter: int = 0  # half-innings elapsed; encodes inning and top/bottom

    @property
    def inning(self) -> int:
        return self.inning_counter // 2 + 1

    @property
    def is_top(self) -> bool:
        return self.inning_counter % 2 == 0

    @classmethod
    def start(
        cls, home: Team, away: Team, rng: Optional[random.Random] = None
    ) -> "Game":
        home.validate()
        away.validate()
        # Everybody starts the game fresh.
        for team in (home, away):
            for player in list(team.fielding_positions) + team.bullpen:
                player.rest()
            if team.starting_pitcher is not None:
                team.current_pitcher = team.starting_pitcher
        return cls(home_team=home, away_team=away, rng=rng or random.Random())

    def simulate(self, verbose: bool = False) -> GameResult:
        """Play to completion, including extra innings if tied."""
        play_by_play: List[PlayEvent] = []

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
            )
            runs = half.play(max_runs=max_runs)
            play_by_play.extend(half.events)

            if verbose:
                side = "Top" if top else "Bottom"
                print(f"\n{side} {inning} -- {batting.name}")
                for event in half.events:
                    print(event)
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
            play_by_play=play_by_play,
        )
