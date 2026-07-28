"""The stateless decision engines.

Each takes its configuration at construction and everything else as
explicit arguments, so a call can be reproduced without building a game.
None of them holds mutable state or can reach back and change the game:
what they get is an immutable Situation, and what they return is a value
object.

The seams between them are deliberate. "The shortstop didn't reach it"
(FieldingEngine), "the runner on second scored" (BaserunningEngine), and
"that's a hit, not an error" (OfficialScorer) are three independent
judgments, and in v0.1 all three were tangled in one method.
"""

from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING, List, Optional, Tuple

from .batted_ball import BattedBall
from .config import DEFAULT_CONFIG, DEFAULT_PARK, ParkConfig, SimulationConfig
from .decisions import Decision, DecisionContext, Option
from .enums import (
    INFIELD_DEPTH_FT,
    MPH_TO_FPS,
    OUTFIELD_DEPTH_FT,
    ZONE_BOTTOM_FT,
    ZONE_TOP_FT,
    Approach,
    AtBatResult,
    DecisionBoundary,
    DecisionKind,
    FieldingOutcome,
    PitchCall,
    Position,
    SwingOutcome,
    grade_to_z,
)
from .events import (
    Advancement,
    BaserunningResult,
    FieldingResult,
    Play,
    ScoringDecision,
)
from .pitch import Pitch
from .player import Player
from .state import BaseRunners, PlayerGameState, Situation

if TYPE_CHECKING:  # pragma: no cover
    from .team import Team


# Where each fielder stands: (spray angle in degrees, depth in feet).
# Spray angle is from the batter's view: negative = left field line,
# positive = right field line, 0 = straight up the middle.
FIELDER_POSITIONS = {
    Position.THIRD: (-27.0, INFIELD_DEPTH_FT - 25),
    Position.SS: (-12.0, INFIELD_DEPTH_FT),
    Position.SECOND: (12.0, INFIELD_DEPTH_FT),
    Position.FIRST: (27.0, INFIELD_DEPTH_FT - 25),
    Position.LF: (-27.0, OUTFIELD_DEPTH_FT),
    Position.CF: (0.0, OUTFIELD_DEPTH_FT + 20),
    Position.RF: (27.0, OUTFIELD_DEPTH_FT),
    Position.C: (0.0, 5.0),
}

NON_FIELDING_POSITIONS = (Position.DH, Position.SP, Position.RP, Position.CL)
OUTFIELD = (Position.LF, Position.CF, Position.RF)


class PitchingEngine:
    """Turns a pitcher plus a situation into one pitched ball.

    Two separate randomness sources shape where the ball ends up. Control
    decides how ambitious the target is (do you aim at the zone at all);
    command decides how tightly the pitch clusters around that target. That
    split is what makes accuracy and precision different things: a pitcher
    with good control but poor command throws strikes, just not the ones he
    wanted.
    """

    def __init__(self, config: SimulationConfig = DEFAULT_CONFIG) -> None:
        self.config = config

    def throw_pitch(
        self,
        pitcher: Player,
        pitcher_state: PlayerGameState,
        batter: Optional[Player],
        situation: Situation,
        rng: random.Random,
    ) -> Pitch:
        cfg = self.config
        profile = pitcher.pitching
        arsenal = profile.repertoire
        if not arsenal:
            raise ValueError(f"{pitcher.name} has no pitches in his repertoire")

        # Better offerings get thrown more often.
        weights = [
            max(cfg.pitch_selection_min_weight, entry.grade - cfg.pitch_selection_offset)
            for entry in arsenal
        ]
        entry = rng.choices(arsenal, weights=weights)[0]

        fatigue = pitcher_state.fatigue(cfg)

        # Control decides how aggressively he attacks the zone.
        control_z = (
            grade_to_z(profile.control_grade) - fatigue * cfg.fatigue_control_penalty
        )
        aim_at_zone = rng.random() < min(
            cfg.zone_target_max,
            cfg.zone_target_rate + control_z * cfg.control_grade_weight,
        )

        if aim_at_zone:
            target_x = rng.uniform(
                -cfg.zone_target_x_halfwidth, cfg.zone_target_x_halfwidth
            )
            target_z = rng.uniform(
                ZONE_BOTTOM_FT + cfg.zone_target_z_inset,
                ZONE_TOP_FT - cfg.zone_target_z_inset,
            )
        else:
            # Deliberately off the plate - chase pitch.
            target_x = rng.choice([-1.0, 1.0]) * rng.uniform(
                cfg.chase_target_x_min, cfg.chase_target_x_max
            )
            target_z = rng.uniform(
                ZONE_BOTTOM_FT - cfg.chase_target_z_below,
                ZONE_TOP_FT + cfg.chase_target_z_above,
            )

        # Command decides the scatter around that target.
        command_z = (
            grade_to_z(profile.command_grade) - fatigue * cfg.fatigue_command_penalty
        )
        sigma = max(
            cfg.command_sigma_min,
            cfg.command_sigma_base - command_z * cfg.command_grade_weight,
        )

        actual_x = target_x + rng.gauss(0, sigma)
        actual_z = target_z + rng.gauss(0, sigma)

        velocity = (
            entry.velocity
            + rng.gauss(0, cfg.velocity_noise)
            - fatigue * cfg.fatigue_velocity_penalty
        )
        spin = entry.spin_rate + rng.gauss(0, cfg.spin_noise)

        # Longer extension shortens the effective distance to the plate, so
        # the same velocity reaches the hitter sooner and plays up.
        effective = velocity + (
            profile.extension - cfg.extension_baseline
        ) * cfg.extension_velocity_weight

        return Pitch(
            pitcher=pitcher,
            batter=batter,
            pitch_type=entry.pitch_type,
            velocity=round(velocity, 1),
            spin_rate=round(spin),
            intended_location=(round(target_x, 2), round(target_z, 2)),
            actual_location=(round(actual_x, 2), round(actual_z, 2)),
            effective_velocity=round(effective, 1),
        )


class BattingEngine:
    """Swing or take, and what happens if he swings."""

    def __init__(self, config: SimulationConfig = DEFAULT_CONFIG) -> None:
        self.config = config

    def swing_probability(
        self, batter: Player, pitch: Pitch, situation: Situation
    ) -> float:
        """How likely the batter is to offer at this pitch.

        Good plate discipline shows up mostly as laying off pitches out of
        the zone, not as swinging more at strikes, which is why the eye
        weight is far larger on the chase side.
        """
        cfg = self.config
        eye_z = grade_to_z(batter.hitting.eye_grade)

        if pitch.in_zone:
            base = cfg.zone_swing_rate
            # With two strikes he has to protect.
            if situation.strikes == 2:
                base = cfg.two_strike_zone_swing_rate
            return max(
                cfg.zone_swing_min,
                min(cfg.zone_swing_max, base + eye_z * cfg.zone_swing_eye_weight),
            )

        # Chase rate: better eyes chase less.
        base = cfg.chase_rate_base - eye_z * cfg.eye_grade_weight
        # Pitches just off the plate are more tempting than way outside.
        nearness = max(
            0.0,
            1.0
            - (pitch.distance_from_center - cfg.chase_nearness_offset)
            / cfg.chase_nearness_scale,
        )
        base *= max(cfg.chase_nearness_floor, nearness)
        if situation.strikes == 2:
            base += cfg.two_strike_chase_bonus
        return max(cfg.chase_min, min(cfg.chase_max, base))

    def whiff_probability(self, batter: Player, pitch: Pitch) -> float:
        """How likely a swing misses entirely."""
        cfg = self.config
        hit_z = grade_to_z(batter.hitting.hit_grade)
        base = cfg.whiff_base - hit_z * cfg.whiff_hit_grade_weight

        # Velocity, spin, and location all make contact harder.
        base += (
            pitch.effective_velocity - cfg.whiff_velocity_baseline
        ) * cfg.whiff_velocity_weight
        base += (pitch.spin_rate - cfg.whiff_spin_baseline) * cfg.whiff_spin_weight
        base += (
            max(0.0, pitch.distance_from_center - cfg.whiff_location_offset)
            * cfg.whiff_location_weight
        )

        # Longer swings are more susceptible to missing.
        base += (
            batter.hitting.swing_length - cfg.whiff_swing_length_baseline
        ) * cfg.whiff_swing_length_weight

        return max(cfg.whiff_min, min(cfg.whiff_max, base))

    def foul_probability(self, batter: Player, pitch: Pitch) -> float:
        """Given contact, how often it goes foul.

        Coupled to strikeout rate: more fouls means deeper counts, which
        means more chances to whiff.
        """
        cfg = self.config
        hit_z = grade_to_z(batter.hitting.hit_grade)
        base = cfg.foul_rate_base - hit_z * cfg.foul_hit_grade_weight
        base += (
            max(0.0, pitch.distance_from_center - cfg.foul_location_offset)
            * cfg.foul_location_weight
        )
        return max(cfg.foul_min, min(cfg.foul_max, base))

    def decide_approach(
        self,
        batter: Player,
        pitch: Pitch,
        situation: Situation,
        rng: random.Random,
        bunt_sign: bool = False,
    ) -> Approach:
        """TAKE, SWING, or BUNT.

        Replaces v0.3's boolean swing decision. A bunt bypasses the contact
        model entirely -- bat speed is irrelevant to it -- so it cannot be
        expressed as "swung, but differently".

        The bunt sign comes from the manager, not from this engine, which is
        why it arrives as an argument rather than being rolled for here.
        """
        if bunt_sign:
            return Approach.BUNT
        if rng.random() < self.swing_probability(batter, pitch, situation):
            return Approach.SWING
        return Approach.TAKE

    def resolve_swing(
        self, batter: Player, pitch: Pitch, rng: random.Random
    ) -> SwingOutcome:
        if rng.random() < self.whiff_probability(batter, pitch):
            return SwingOutcome.WHIFF
        if rng.random() < self.foul_probability(batter, pitch):
            return SwingOutcome.FOUL
        return SwingOutcome.CONTACT

    def make_contact(
        self, batter: Player, pitch: Pitch, rng: random.Random
    ) -> BattedBall:
        return BattedBall.from_contact(batter, pitch, rng, self.config)


class FieldingEngine:
    """Did anybody get to it, and did he hold on?

    Answers only the physical question. Hit-versus-error is a scoring
    judgment and lives in OfficialScorer.
    """

    def __init__(
        self,
        config: SimulationConfig = DEFAULT_CONFIG,
        park: ParkConfig = DEFAULT_PARK,
    ) -> None:
        self.config = config
        self.park = park

    def resolve(
        self,
        batted_ball: BattedBall,
        defense: "Team",
        situation: Situation,
        rng: random.Random,
    ) -> FieldingResult:
        cfg = self.config
        wall = self.park.wall_distance(batted_ball.spray_angle)

        if (
            batted_ball.distance >= wall
            and cfg.home_run_min_angle
            <= batted_ball.launch_angle
            <= cfg.home_run_max_angle
        ):
            return FieldingResult(
                outcome=FieldingOutcome.OVER_THE_FENCE, wall_distance=wall
            )

        if abs(batted_ball.spray_angle) > cfg.spray_max:
            return FieldingResult(outcome=FieldingOutcome.FOUL, wall_distance=wall)

        fielder, gap = self._closest_fielder(batted_ball, defense)
        if fielder is None:
            # Nobody is responsible, so it falls in.
            return FieldingResult(
                outcome=FieldingOutcome.DROPPED_IN, wall_distance=wall
            )

        if batted_ball.batted_ball_type == "ground ball":
            return self._resolve_ground_ball(batted_ball, defense, wall, rng)
        return self._resolve_air_ball(batted_ball, fielder, gap, wall, rng)

    # --- Geometry ---------------------------------------------------------

    def _landing_point(self, batted_ball: BattedBall) -> Tuple[float, float]:
        rad = math.radians(batted_ball.spray_angle)
        return (
            batted_ball.distance * math.sin(rad),
            batted_ball.distance * math.cos(rad),
        )

    def _closest_fielder(
        self, batted_ball: BattedBall, defense: "Team"
    ) -> Tuple[Optional[Player], float]:
        landing = self._landing_point(batted_ball)
        best, best_dist = None, float("inf")
        for player, position in defense.fielding_positions.items():
            if position in NON_FIELDING_POSITIONS:
                continue
            spot = FIELDER_POSITIONS.get(position)
            if spot is None:
                continue
            fx = spot[1] * math.sin(math.radians(spot[0]))
            fy = spot[1] * math.cos(math.radians(spot[0]))
            dist = math.hypot(landing[0] - fx, landing[1] - fy)
            if dist < best_dist:
                best, best_dist = player, dist
        return best, best_dist

    def _ground_ball_fielder(
        self, batted_ball: BattedBall, defense: "Team"
    ) -> Tuple[Optional[Player], float, float]:
        """Ground balls roll, so they get fielded along their path.

        Using a landing point here would be wrong: a grounder first touches
        the grass 60-80 feet from the plate, well in front of the
        infielders, but it keeps going. What matters is where it crosses
        infield depth and how long the fielder has to get there. Treating
        the first bounce as the landing point made essentially every ground
        ball a hit -- the single largest calibration bug in v0.1.
        """
        rad = math.radians(batted_ball.spray_angle)
        bx = INFIELD_DEPTH_FT * math.sin(rad)
        by = INFIELD_DEPTH_FT * math.cos(rad)

        best, best_dist = None, float("inf")
        for player, position in defense.fielding_positions.items():
            spot = FIELDER_POSITIONS.get(position)
            if spot is None or position in (Position.C,) + OUTFIELD:
                continue
            fx = spot[1] * math.sin(math.radians(spot[0]))
            fy = spot[1] * math.cos(math.radians(spot[0]))
            dist = math.hypot(bx - fx, by - fy)
            if dist < best_dist:
                best, best_dist = player, dist

        horizontal = max(
            self.config.ground_ball_speed_min,
            batted_ball.exit_velocity
            * MPH_TO_FPS
            * self.config.ground_ball_speed_retention,
        )
        travel_time = INFIELD_DEPTH_FT / horizontal
        return best, best_dist, travel_time

    # --- Resolution -------------------------------------------------------

    def _resolve_ground_ball(
        self,
        batted_ball: BattedBall,
        defense: "Team",
        wall: float,
        rng: random.Random,
    ) -> FieldingResult:
        cfg = self.config
        fielder, gap, travel_time = self._ground_ball_fielder(batted_ball, defense)
        if fielder is None:
            return FieldingResult(
                outcome=FieldingOutcome.THROUGH_INFIELD, wall_distance=wall
            )

        react = (
            cfg.infield_reaction_time
            - grade_to_z(fielder.fielding.field_grade) * cfg.infield_reaction_grade_weight
        )
        usable = max(0.0, travel_time - react)
        reach = usable * fielder.running.sprint_speed * cfg.infield_reach_factor

        if gap > reach:
            return FieldingResult(
                outcome=FieldingOutcome.THROUGH_INFIELD,
                fielder=fielder,
                landing_zone="infield",
                distance_traveled=gap,
                time_available=usable,
                wall_distance=wall,
            )

        outcome = (
            FieldingOutcome.MISPLAYED
            if rng.random() < fielder.fielding.error_rate
            else FieldingOutcome.FIELDED_CLEANLY
        )
        return FieldingResult(
            outcome=outcome,
            fielder=fielder,
            landing_zone="infield",
            distance_traveled=gap,
            time_available=usable,
            wall_distance=wall,
        )

    def _resolve_air_ball(
        self,
        batted_ball: BattedBall,
        fielder: Player,
        gap: float,
        wall: float,
        rng: random.Random,
    ) -> FieldingResult:
        cfg = self.config
        react = (
            cfg.reaction_time_base
            - grade_to_z(fielder.fielding.field_grade) * cfg.outfield_reaction_grade_weight
        )
        usable = max(0.0, batted_ball.hang_time - react)
        range_ft = usable * fielder.running.sprint_speed * cfg.outfield_reach_factor

        if range_ft <= 0:
            catchable = False
        else:
            margin = (range_ft - gap) / cfg.catch_probability_slope
            catch_prob = 1.0 / (1.0 + math.exp(-margin))
            catchable = rng.random() < catch_prob

        zone = "outfield" if batted_ball.distance >= INFIELD_DEPTH_FT else "infield"

        if catchable:
            outcome = (
                FieldingOutcome.MISPLAYED
                if rng.random() < fielder.fielding.error_rate * cfg.air_error_multiplier
                else FieldingOutcome.CAUGHT
            )
        else:
            outcome = FieldingOutcome.DROPPED_IN

        return FieldingResult(
            outcome=outcome,
            fielder=fielder,
            landing_zone=zone,
            distance_traveled=gap,
            time_available=usable,
            wall_distance=wall,
        )


class BaserunningEngine:
    """Everything AtBat structurally cannot know.

    Whether a ground ball is a double play, whether a fly ball is a
    sacrifice, whether a fielded grounder is a fielder's choice -- all of
    these need the base state and the out count, which is exactly what a
    plate appearance doesn't have.
    """

    def __init__(self, config: SimulationConfig = DEFAULT_CONFIG) -> None:
        self.config = config

    # --- Batter's own advance ---------------------------------------------

    def _batter_bases(
        self,
        fielding_result: FieldingResult,
        batted_ball: BattedBall,
        rng: random.Random,
    ) -> Tuple[int, bool]:
        """How far the batter got, and whether he was safe.

        Returns (bases, safe). Bases of 0 with safe=False is an out.
        """
        cfg = self.config
        outcome = fielding_result.outcome

        if outcome is FieldingOutcome.OVER_THE_FENCE:
            return 4, True

        if outcome in (FieldingOutcome.CAUGHT, FieldingOutcome.FOUL):
            return 0, False

        if outcome is FieldingOutcome.MISPLAYED:
            # Reached on a misplay; always one base in this model.
            return 1, True

        if fielding_result.fielder is None:
            # Nobody was responsible for it. A single, and deliberately no
            # RNG draw: spending one here would desynchronize every
            # downstream result against v0.1.
            return 1, True

        if outcome is FieldingOutcome.THROUGH_INFIELD:
            double_chance = (
                cfg.ground_double_corner_rate
                if abs(batted_ball.spray_angle) > cfg.corner_spray_angle
                else cfg.ground_double_base_rate
            )
            return (2, True) if rng.random() < double_chance else (1, True)

        if outcome is FieldingOutcome.FIELDED_CLEANLY:
            # Fielded, but a fast runner can still beat the throw.
            speed_z = (
                batted_ball.exit_velocity - cfg.infield_hit_velocity_baseline
            ) / cfg.infield_hit_velocity_scale
            infield_hit = max(
                cfg.infield_hit_min,
                cfg.infield_hit_base - speed_z * cfg.infield_hit_velocity_weight,
            )
            return (1, True) if rng.random() < infield_hit else (0, False)

        # DROPPED_IN: how far it landed, and how close to the line.
        corner_bonus = (
            cfg.corner_bonus
            if abs(batted_ball.spray_angle) > cfg.corner_spray_angle
            else 0.0
        )
        if batted_ball.distance >= fielding_result.wall_distance - cfg.wall_margin:
            return (3, True) if rng.random() < cfg.off_wall_triple_rate else (2, True)
        if batted_ball.distance >= cfg.deep_distance:
            roll = rng.random()
            if roll < cfg.deep_triple_rate + corner_bonus * cfg.deep_triple_corner_weight:
                return 3, True
            if roll < cfg.deep_double_rate + corner_bonus:
                return 2, True
            return 1, True
        if batted_ball.distance >= cfg.medium_distance:
            return (
                (2, True)
                if rng.random() < cfg.medium_double_rate + corner_bonus
                else (1, True)
            )
        return 1, True

    # --- Runners -----------------------------------------------------------

    def advance(
        self,
        batter: Player,
        fielding_result: FieldingResult,
        batted_ball: BattedBall,
        base_runners: BaseRunners,
        outs: int,
        rng: random.Random,
    ) -> BaserunningResult:
        """Turn a fielded ball plus a base state into advancements."""
        bases, safe = self._batter_bases(fielding_result, batted_ball, rng)

        if safe and bases >= 1:
            return self.advance_on_reach(batter, bases, base_runners, rng)
        return self._advance_on_out(batted_ball, fielding_result, base_runners, outs, rng)

    def advance_on_reach(
        self,
        batter: Player,
        bases: int,
        base_runners: BaseRunners,
        rng: random.Random,
    ) -> BaserunningResult:
        """The batter reached. Runners move up, sometimes an extra base.

        Runners don't just advance the same number of bases as the hit. A
        runner on second usually scores on a single and a runner on first
        often takes third, and how often depends on his speed. That extra
        base is worth roughly a run a game, so it isn't optional.
        """
        cfg = self.config
        advancements: List[Advancement] = []
        runs = 0

        # Work from third backward so runners don't overwrite each other.
        for base, runner in ((3, base_runners.third), (2, base_runners.second), (1, base_runners.first)):
            if runner is None:
                continue
            new_base = base + bases

            if bases < 4 and new_base < 4:
                speed_edge = (
                    runner.running.sprint_speed - cfg.baserunning_speed_baseline
                ) * cfg.speed_weight
                if base == 2 and bases == 1:
                    extra = cfg.score_from_second_on_single + speed_edge
                elif base == 1 and bases == 1:
                    extra = cfg.first_to_third_on_single + speed_edge
                elif base == 1 and bases == 2:
                    extra = cfg.score_from_first_on_double + speed_edge
                else:
                    extra = cfg.extra_base_default + speed_edge
                if rng.random() < max(0.0, min(cfg.extra_base_max, extra)):
                    new_base += 1

            advancements.append(Advancement(runner=runner, from_base=base, to_base=new_base))
            if new_base >= 4:
                runs += 1

        advancements.append(
            Advancement(runner=batter, from_base=0, to_base=min(bases, 4))
        )
        if bases >= 4:
            runs += 1

        return BaserunningResult(
            advancements=advancements,
            runs_scored=runs,
            outs_recorded=0,
            batter_bases=bases,
            batter_safe=True,
        )

    def _advance_on_out(
        self,
        batted_ball: BattedBall,
        fielding_result: FieldingResult,
        base_runners: BaseRunners,
        outs: int,
        rng: random.Random,
    ) -> BaserunningResult:
        """The batter was retired. A runner on third may still score."""
        cfg = self.config
        advancements: List[Advancement] = []
        runs = 0
        outs_after = outs + 1

        third = base_runners.third
        is_ground = fielding_result.outcome is FieldingOutcome.FIELDED_CLEANLY
        # A foul out counts as a fly ball for tagging purposes, which is how
        # v0.1 behaved: it produced FLY_OUT and took the same branch.
        is_fly = (
            fielding_result.outcome is FieldingOutcome.FOUL
            or (
                fielding_result.outcome is FieldingOutcome.CAUGHT
                and batted_ball.batted_ball_type not in ("line drive", "pop up")
            )
        )

        if is_ground:
            # A runner on third usually scores on an infield out with fewer
            # than two outs.
            if outs_after < 3 and third is not None:
                if rng.random() < cfg.score_from_third_on_ground_out:
                    advancements.append(Advancement(runner=third, from_base=3, to_base=4))
                    runs += 1
        elif is_fly:
            # Runner tags from third and the run scores -- but OfficialScorer
            # rules this FLY_OUT, never SAC_FLY, so the batter is charged an
            # at-bat he shouldn't be. Known defect; fixing it moves batting
            # average, so it was left alone through the v0.3 restructure.
            if outs_after < 3 and third is not None:
                if rng.random() < cfg.tag_from_third_rate:
                    advancements.append(Advancement(runner=third, from_base=3, to_base=4))
                    runs += 1

        return BaserunningResult(
            advancements=advancements,
            runs_scored=runs,
            outs_recorded=1,
            batter_bases=0,
            batter_safe=False,
        )

    # --- Walks and steals ---------------------------------------------------

    def force_advance(self, batter: Player, base_runners: BaseRunners) -> BaserunningResult:
        """Walk or hit by pitch: runners move up only if forced."""
        advancements: List[Advancement] = []
        runs = 0

        if base_runners.first is not None:
            if base_runners.second is not None:
                if base_runners.third is not None:
                    advancements.append(
                        Advancement(runner=base_runners.third, from_base=3, to_base=4)
                    )
                    runs += 1
                advancements.append(
                    Advancement(runner=base_runners.second, from_base=2, to_base=3)
                )
            advancements.append(
                Advancement(runner=base_runners.first, from_base=1, to_base=2)
            )
        advancements.append(Advancement(runner=batter, from_base=0, to_base=1))

        return BaserunningResult(
            advancements=advancements,
            runs_scored=runs,
            outs_recorded=0,
            batter_bases=1,
            batter_safe=True,
        )

    def attempt_steal(
        self,
        base_runners: BaseRunners,
        defense: "Team",
        rng: random.Random,
    ) -> Optional[BaserunningResult]:
        """Runner on first, second open, may try to take second."""
        runner = base_runners.first
        if runner is None or base_runners.second is not None:
            return None
        if rng.random() >= runner.running.steal_aggression:
            return None

        catcher_arm = 50
        for player, position in defense.fielding_positions.items():
            if position is Position.C:
                catcher_arm = player.fielding.arm_grade
                break

        success = (
            runner.running.steal_success_rate
            - grade_to_z(catcher_arm) * self.config.steal_catcher_arm_weight
        )
        if rng.random() < success:
            return BaserunningResult(
                advancements=[Advancement(runner=runner, from_base=1, to_base=2)],
                outs_recorded=0,
            )
        return BaserunningResult(
            advancements=[Advancement(runner=runner, from_base=1, to_base=2, out=True)],
            outs_recorded=1,
        )


class OfficialScorer:
    """Rules on what the play goes down as.

    Separating this from FieldingEngine is what lets "the shortstop didn't
    reach it" and "that's a hit, not an error" be independent decisions.
    """

    def __init__(self, config: SimulationConfig = DEFAULT_CONFIG) -> None:
        self.config = config

    def score(
        self,
        terminal_call: PitchCall,
        batted_ball: Optional[BattedBall],
        fielding_result: Optional[FieldingResult],
        baserunning_result: Optional[BaserunningResult],
        situation: Situation,
    ) -> ScoringDecision:
        if terminal_call is PitchCall.HIT_BY_PITCH:
            return ScoringDecision(result=AtBatResult.HIT_BY_PITCH)
        if terminal_call is PitchCall.BALL:
            return ScoringDecision(result=AtBatResult.WALK)
        if terminal_call in (PitchCall.CALLED_STRIKE, PitchCall.SWINGING_STRIKE):
            return ScoringDecision(result=AtBatResult.STRIKEOUT)

        assert fielding_result is not None and baserunning_result is not None
        assert batted_ball is not None

        runs = baserunning_result.runs_scored
        result = self._rule(batted_ball, fielding_result, baserunning_result)
        return ScoringDecision(result=result, rbi_credited=runs)

    def _rule(
        self,
        batted_ball: BattedBall,
        fielding_result: FieldingResult,
        baserunning_result: BaserunningResult,
    ) -> AtBatResult:
        outcome = fielding_result.outcome

        if outcome is FieldingOutcome.OVER_THE_FENCE:
            return AtBatResult.HOME_RUN
        if outcome is FieldingOutcome.FOUL:
            return AtBatResult.FLY_OUT
        if outcome is FieldingOutcome.MISPLAYED:
            return AtBatResult.ERROR
        if outcome is FieldingOutcome.CAUGHT:
            ball_type = batted_ball.batted_ball_type
            if ball_type == "line drive":
                return AtBatResult.LINE_OUT
            if ball_type == "pop up":
                return AtBatResult.POP_OUT
            return AtBatResult.FLY_OUT
        if outcome is FieldingOutcome.FIELDED_CLEANLY:
            return (
                AtBatResult.SINGLE
                if baserunning_result.batter_safe
                else AtBatResult.GROUND_OUT
            )

        # THROUGH_INFIELD or DROPPED_IN: a hit, sized by how far he got.
        return {
            1: AtBatResult.SINGLE,
            2: AtBatResult.DOUBLE,
            3: AtBatResult.TRIPLE,
            4: AtBatResult.HOME_RUN,
        }.get(baserunning_result.batter_bases, AtBatResult.SINGLE)

    def apply_to_stats(
        self, play: Play, batting_team: "Team", defending_team: "Team"
    ) -> None:
        """Write the play into both teams' stat lines."""
        batting_team.stats_for(play.batter).record_result(play.official_result)

        for advancement in play.advancements:
            if advancement.scored:
                batting_team.stats_for(advancement.runner).runs += 1
        if play.rbi_credited:
            batting_team.stats_for(play.batter).rbi += play.rbi_credited

        stats = defending_team.stats_for(play.pitcher)
        result = play.official_result
        if result.is_out:
            stats.outs_recorded += 1
        if result is AtBatResult.STRIKEOUT:
            stats.strikeouts_pitched += 1
        elif result is AtBatResult.WALK:
            stats.walks_allowed += 1
        elif result.is_hit:
            stats.hits_allowed += 1
        stats.earned_runs += play.runs_scored

        fielding = play.fielding_result
        if fielding is not None and fielding.fielder is not None:
            if fielding.outcome is FieldingOutcome.MISPLAYED:
                defending_team.stats_for(fielding.fielder).errors += 1
            elif fielding.outcome is FieldingOutcome.CAUGHT:
                defending_team.stats_for(fielding.fielder).putouts += 1
            elif fielding.outcome is FieldingOutcome.FIELDED_CLEANLY and result.is_out:
                defending_team.stats_for(fielding.fielder).assists += 1


class StrategyEngine:
    """Produces the decisions a manager is asked to make, and applies them.

    Stateless like the rest: config at construction, an immutable Situation
    per call, value objects out. It knows what is *legal* and what the
    options are; which one to pick is the agent's job.

    Phase 1 is the contract only -- it offers no decisions yet, so behavior
    is unchanged. Phase 5 fills it in one mechanic at a time.
    """

    def __init__(self, config: SimulationConfig = DEFAULT_CONFIG) -> None:
        self.config = config

    def leverage(self, situation: Situation) -> float:
        """How much the next decision matters, roughly 0.0 to 1.0.

        Used by AI heuristics in v0.4. v0.5 reuses it to decide which
        prompts are worth surfacing to a human, which is what keeps ~290
        pitches a game from becoming ~290 prompts.

        Three things drive it: how close the score is, how late it is, and
        how many runners are at stake.
        """
        margin = abs(situation.score_differential)
        # A four-run game is nearly decided for tactical purposes.
        closeness = max(0.0, 1.0 - margin / 4.0)
        lateness = min(1.0, situation.inning / 9.0)
        runners = situation.base_runners.count / 3.0
        # Outs matter, but less than the rest.
        urgency = situation.outs / 3.0 * 0.25

        return round(
            min(1.0, closeness * (0.35 + 0.45 * lateness) + 0.3 * runners + urgency),
            3,
        )

    def pending_decisions(
        self,
        boundary: DecisionBoundary,
        situation: Situation,
        team: "Team",
        context: Optional[DecisionContext] = None,
    ) -> List[Decision]:
        """Every decision legally available at this boundary.

        Empty in Phase 1. Each Phase 5 slice adds one kind here alongside
        the mechanic it drives, so a decision never exists without something
        that acts on it.
        """
        return []

    def apply(self, decision: Decision, choice: Option, game_state) -> None:
        """Carry out a chosen option.

        No-op in Phase 1; nothing produces decisions yet.
        """
        return None
