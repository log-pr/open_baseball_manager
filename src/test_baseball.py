"""Test suite for the baseball simulation.

Run with:   python3 -m unittest test_baseball -v
Or just:    python3 test_baseball.py

The tests are organized bottom-up, matching the build order: a single
pitch, then an at-bat, then contact physics, then a half-inning, then a
full game. Each layer only depends on the one below it, so when something
breaks, the lowest failing test tells you where.
"""

import random
import statistics
import unittest

from baseball import (
    AtBat,
    AtBatResult,
    BaseRunners,
    BaserunningEngine,
    BattedBall,
    BattingEngine,
    DEFAULT_PARK,
    FieldingEngine,
    FieldingOutcome,
    FieldingResult,
    Game,
    HalfInning,
    Lineup,
    OfficialScorer,
    PitchCall,
    PitchingEngine,
    Player,
    PlayerGameState,
    PlayerStats,
    Position,
    Situation,
    Team,
)
from baseball.enums import PLATE_HALF_WIDTH_FT, ZONE_BOTTOM_FT, ZONE_TOP_FT
from baseball.rngs import derive

PITCHING = PitchingEngine()
BATTING = BattingEngine()
BASERUNNING = BaserunningEngine()
SCORER = OfficialScorer()


def make_rng(seed=1234):
    return random.Random(seed)


def throw(pitcher, rng, state=None, situation=None):
    """One pitch, the way PitchingEngine is meant to be called."""
    return PITCHING.throw_pitch(
        pitcher,
        state or PlayerGameState(player=pitcher),
        None,
        situation or Situation(),
        rng,
    )


def scored_runners(result):
    return [a.runner for a in result.advancements if a.scored]


def hit_advance(runners, bases, batter, rng):
    """Advance runners on a hit and apply it, the way HalfInning would."""
    result = BASERUNNING.advance_on_reach(batter, bases, runners, rng)
    runners.apply(result)
    return result


def average_player(name="Test Player", position=Position.CF):
    """A dead-average 50-grade player, for deterministic comparisons."""
    return Player(name=name, primary_position=position)


# ---------------------------------------------------------------------------
# Layer 1: a single pitch
# ---------------------------------------------------------------------------


class TestPitch(unittest.TestCase):
    def setUp(self):
        self.rng = make_rng()
        self.pitcher = Player.generate(self.rng, "Pitcher", Position.SP)

    def test_pitch_has_sane_velocity(self):
        for _ in range(500):
            pitch = throw(self.pitcher, self.rng)
            self.assertGreater(pitch.velocity, 60.0)
            self.assertLess(pitch.velocity, 110.0)

    def test_pitch_comes_from_repertoire(self):
        types = {e.pitch_type for e in self.pitcher.pitching.repertoire}
        for _ in range(200):
            self.assertIn(throw(self.pitcher, self.rng).pitch_type, types)

    def test_in_zone_matches_geometry(self):
        for _ in range(500):
            pitch = throw(self.pitcher, self.rng)
            expected = (
                abs(pitch.x) <= PLATE_HALF_WIDTH_FT
                and ZONE_BOTTOM_FT <= pitch.z <= ZONE_TOP_FT
            )
            self.assertEqual(pitch.in_zone, expected)

    def test_zone_rate_is_realistic(self):
        in_zone = sum(throw(self.pitcher, self.rng).in_zone for _ in range(4000))
        rate = in_zone / 4000
        self.assertGreater(rate, 0.40, f"zone rate {rate:.3f} too low")
        self.assertLess(rate, 0.60, f"zone rate {rate:.3f} too high")

    def test_better_command_means_tighter_grouping(self):
        """Command is precision: how close pitches land to the target."""
        elite = Player.generate(make_rng(1), "Elite", Position.SP)
        elite.pitching.command_grade = 80
        wild = Player.generate(make_rng(1), "Wild", Position.SP)
        wild.pitching.command_grade = 20

        rng_a, rng_b = make_rng(9), make_rng(9)
        elite_miss = statistics.mean(
            throw(elite, rng_a).miss_distance for _ in range(3000)
        )
        wild_miss = statistics.mean(
            throw(wild, rng_b).miss_distance for _ in range(3000)
        )
        self.assertLess(elite_miss, wild_miss)

    def test_better_control_means_more_strikes(self):
        """Control is accuracy: how often the ball ends up in the zone."""
        elite = Player.generate(make_rng(2), "Elite", Position.SP)
        elite.pitching.control_grade = 80
        wild = Player.generate(make_rng(2), "Wild", Position.SP)
        wild.pitching.control_grade = 20

        rng_a, rng_b = make_rng(11), make_rng(11)
        elite_zone = sum(throw(elite, rng_a).in_zone for _ in range(3000))
        wild_zone = sum(throw(wild, rng_b).in_zone for _ in range(3000))
        self.assertGreater(elite_zone, wild_zone)

    def test_fatigue_saps_velocity(self):
        fresh = Player.generate(make_rng(3), "Arm", Position.SP)
        fresh.pitching.stamina = 90
        rng = make_rng(5)
        state = PlayerGameState(player=fresh)
        fresh_velo = statistics.mean(
            throw(fresh, rng, state).velocity for _ in range(400)
        )

        state.pitches_thrown = 160  # well past his stamina
        tired_velo = statistics.mean(
            throw(fresh, rng, state).velocity for _ in range(400)
        )
        self.assertLess(tired_velo, fresh_velo)

    def test_pitch_count_no_longer_lives_on_player(self):
        """v0.1 bug: pitches_thrown on Player drifted across games."""
        arm = Player.generate(make_rng(3), "Arm", Position.SP)
        self.assertFalse(hasattr(arm, "pitches_thrown"))
        a, b = PlayerGameState(player=arm), PlayerGameState(player=arm)
        a.record_pitch()
        self.assertEqual(b.pitches_thrown, 0, "two games shared one pitch count")


# ---------------------------------------------------------------------------
# Layer 2: contact physics
# ---------------------------------------------------------------------------


class TestBattedBall(unittest.TestCase):
    def setUp(self):
        self.rng = make_rng()
        self.batter = average_player()
        self.pitcher = Player.generate(self.rng, "Pitcher", Position.SP)

    def test_exit_velocity_in_realistic_range(self):
        for _ in range(2000):
            pitch = throw(self.pitcher, self.rng)
            bb = BattedBall.from_contact(self.batter, pitch, self.rng)
            self.assertGreater(bb.exit_velocity, 20.0)
            self.assertLess(bb.exit_velocity, 125.0)

    def test_average_exit_velocity_matches_mlb(self):
        evs = []
        for _ in range(5000):
            pitch = throw(self.pitcher, self.rng)
            evs.append(BattedBall.from_contact(self.batter, pitch, self.rng).exit_velocity)
        avg = statistics.mean(evs)
        self.assertGreater(avg, 85.0, f"avg EV {avg:.1f} too low")
        self.assertLess(avg, 93.0, f"avg EV {avg:.1f} too high")

    def test_power_hitters_hit_the_ball_harder(self):
        slugger = average_player("Slugger")
        slugger.hitting.bat_speed = 78.0
        slap = average_player("Slap Hitter")
        slap.hitting.bat_speed = 65.0

        rng_a, rng_b = make_rng(21), make_rng(21)
        pitches = [throw(self.pitcher, make_rng(31)) for _ in range(1500)]
        slug_ev = statistics.mean(
            BattedBall.from_contact(slugger, p, rng_a).exit_velocity for p in pitches
        )
        slap_ev = statistics.mean(
            BattedBall.from_contact(slap, p, rng_b).exit_velocity for p in pitches
        )
        self.assertGreater(slug_ev, slap_ev + 8.0)

    def test_attack_angle_drives_launch_angle(self):
        uppercut = average_player("Uppercut")
        uppercut.hitting.attack_angle = 20.0
        chopper = average_player("Chopper")
        chopper.hitting.attack_angle = 0.0

        pitches = [throw(self.pitcher, make_rng(41)) for _ in range(2000)]
        rng_a, rng_b = make_rng(51), make_rng(51)
        up_la = statistics.mean(
            BattedBall.from_contact(uppercut, p, rng_a).launch_angle for p in pitches
        )
        chop_la = statistics.mean(
            BattedBall.from_contact(chopper, p, rng_b).launch_angle for p in pitches
        )
        self.assertGreater(up_la, chop_la + 10.0)

    def test_barrel_definition_matches_statcast(self):
        """Statcast: 98 mph needs 26-30 degrees; the window widens with velocity."""
        # Below the velocity floor, nothing is a barrel.
        self.assertFalse(BattedBall(97.9, 28.0, 0, 380, 4.5).is_barrel)
        # At exactly 98, only the narrow window qualifies.
        self.assertTrue(BattedBall(98.0, 28.0, 0, 380, 4.5).is_barrel)
        self.assertFalse(BattedBall(98.0, 20.0, 0, 380, 4.5).is_barrel)
        self.assertFalse(BattedBall(98.0, 35.0, 0, 380, 4.5).is_barrel)
        # At 116 the window is wide open from 8 to 50.
        self.assertTrue(BattedBall(116.0, 10.0, 0, 400, 4.5).is_barrel)
        self.assertTrue(BattedBall(116.0, 45.0, 0, 400, 4.5).is_barrel)
        self.assertFalse(BattedBall(116.0, 60.0, 0, 400, 4.5).is_barrel)

    def test_hard_hit_threshold(self):
        self.assertTrue(BattedBall(95.0, 15, 0, 300, 3.0).is_hard_hit)
        self.assertFalse(BattedBall(94.9, 15, 0, 300, 3.0).is_hard_hit)

    def test_batted_ball_classification(self):
        self.assertEqual(BattedBall(90, 2, 0, 100, 0).batted_ball_type, "ground ball")
        self.assertEqual(BattedBall(90, 15, 0, 200, 2).batted_ball_type, "line drive")
        self.assertEqual(BattedBall(90, 35, 0, 300, 5).batted_ball_type, "fly ball")
        self.assertEqual(BattedBall(90, 60, 0, 120, 5).batted_ball_type, "pop up")

    def test_distance_is_physically_plausible(self):
        """A well-struck ball should carry roughly as far as a real one."""
        distance, hang = BattedBall._trajectory(103.0, 28.0)
        self.assertGreater(distance, 350, f"{distance:.0f} ft is too short")
        self.assertLess(distance, 440, f"{distance:.0f} ft is too far")
        self.assertGreater(hang, 3.5)
        self.assertLess(hang, 7.0)

    def test_harder_hit_balls_travel_farther(self):
        short, _ = BattedBall._trajectory(85.0, 28.0)
        far, _ = BattedBall._trajectory(105.0, 28.0)
        self.assertGreater(far, short)

    def test_wall_is_closer_down_the_lines(self):
        center = DEFAULT_PARK.wall_distance(0.0)
        line = DEFAULT_PARK.wall_distance(45.0)
        self.assertGreater(center, line)
        self.assertAlmostEqual(center, 400.0, delta=1.0)
        self.assertAlmostEqual(line, 330.0, delta=1.0)


# ---------------------------------------------------------------------------
# Layer 3: the at-bat
# ---------------------------------------------------------------------------


class TestAtBat(unittest.TestCase):
    def setUp(self):
        self.rng = make_rng()
        self.batter = average_player()
        self.pitcher = Player.generate(self.rng, "Pitcher", Position.SP)
        self.defense = Team.generate(self.rng, "Defense")

    def test_single_pitch_advances_the_count(self):
        ab = AtBat(batter=self.batter, pitcher=self.pitcher, rng=self.rng)
        before = ab.balls + ab.strikes
        call, pitch = ab.throw_next_pitch()
        self.assertIsInstance(call, PitchCall)
        self.assertEqual(len(ab.pitches), 1)
        if call in (PitchCall.BALL, PitchCall.CALLED_STRIKE, PitchCall.SWINGING_STRIKE):
            self.assertEqual(ab.balls + ab.strikes, before + 1)

    def test_foul_never_makes_the_third_strike(self):
        ab = AtBat(batter=self.batter, pitcher=self.pitcher, rng=self.rng)
        ab.strikes = 2
        for _ in range(200):
            if ab.is_complete:
                break
            call, _ = ab.throw_next_pitch()
            if call is PitchCall.FOUL:
                self.assertEqual(ab.strikes, 2, "a foul ended the at-bat")

    def test_at_bat_always_terminates(self):
        for seed in range(300):
            ab = AtBat(batter=self.batter, pitcher=self.pitcher, rng=make_rng(seed))
            outcome = ab.simulate()
            self.assertIn(
                outcome.terminal_call,
                (
                    PitchCall.BALL,
                    PitchCall.CALLED_STRIKE,
                    PitchCall.SWINGING_STRIKE,
                    PitchCall.HIT_BY_PITCH,
                    PitchCall.IN_PLAY,
                ),
            )
            self.assertLess(len(ab.pitches), 60, "at-bat ran away")

    def test_outcome_carries_no_base_state(self):
        """The v0.2 contradiction: AtBat cannot know runs, outs, or advances."""
        ab = AtBat(batter=self.batter, pitcher=self.pitcher, rng=make_rng(1))
        outcome = ab.simulate()
        for forbidden in ("runs_scored", "outs_recorded", "advancements"):
            self.assertFalse(
                hasattr(outcome, forbidden),
                f"PlateAppearanceOutcome should not carry {forbidden}",
            )

    def test_walk_requires_four_balls(self):
        for seed in range(400):
            ab = AtBat(batter=self.batter, pitcher=self.pitcher, rng=make_rng(seed))
            outcome = ab.simulate()
            if outcome.terminal_call is PitchCall.BALL:
                self.assertEqual(ab.balls, 4)

    def test_strikeout_requires_three_strikes(self):
        for seed in range(400):
            ab = AtBat(batter=self.batter, pitcher=self.pitcher, rng=make_rng(seed))
            outcome = ab.simulate()
            if outcome.terminal_call in (
                PitchCall.CALLED_STRIKE,
                PitchCall.SWINGING_STRIKE,
            ):
                self.assertEqual(ab.strikes, 3)

    def test_good_eye_draws_more_walks(self):
        patient = average_player("Patient")
        patient.hitting.eye_grade = 80
        hacker = average_player("Hacker")
        hacker.hitting.eye_grade = 20

        def walk_rate(batter, seed):
            rng = make_rng(seed)
            state = PlayerGameState(player=self.pitcher)
            walks = 0
            for _ in range(3000):
                state.reset()  # isolate the batter, no fatigue drift
                ab = AtBat(
                    batter=batter,
                    pitcher=self.pitcher,
                    pitcher_state=state,
                    rng=rng,
                )
                if ab.simulate().terminal_call is PitchCall.BALL:
                    walks += 1
            return walks / 3000

        self.assertGreater(walk_rate(patient, 77), walk_rate(hacker, 77) + 0.03)

    def test_good_contact_hitter_strikes_out_less(self):
        contact = average_player("Contact")
        contact.hitting.hit_grade = 80
        swinger = average_player("Swing And Miss")
        swinger.hitting.hit_grade = 20

        def k_rate(batter, seed):
            rng = make_rng(seed)
            state = PlayerGameState(player=self.pitcher)
            ks = 0
            for _ in range(3000):
                state.reset()  # isolate the batter, no fatigue drift
                ab = AtBat(
                    batter=batter,
                    pitcher=self.pitcher,
                    pitcher_state=state,
                    rng=rng,
                )
                if ab.simulate().terminal_call in (
                    PitchCall.CALLED_STRIKE,
                    PitchCall.SWINGING_STRIKE,
                ):
                    ks += 1
            return ks / 3000

        self.assertLess(k_rate(contact, 88), k_rate(swinger, 88) - 0.05)

    def test_no_pitches_after_completion(self):
        ab = AtBat(batter=self.batter, pitcher=self.pitcher, rng=self.rng)
        ab.balls = 4
        with self.assertRaises(RuntimeError):
            ab.throw_next_pitch()


# ---------------------------------------------------------------------------
# Layer 4: baserunning and the half-inning
# ---------------------------------------------------------------------------


class TestBaseRunners(unittest.TestCase):
    def setUp(self):
        self.a = average_player("A")
        self.b = average_player("B")
        self.c = average_player("C")
        self.d = average_player("D")

    def test_empty_bases(self):
        runners = BaseRunners()
        self.assertTrue(runners.is_empty)
        self.assertEqual(runners.count, 0)

    def test_home_run_clears_the_bases(self):
        runners = BaseRunners(first=self.a, second=self.b, third=self.c)
        result = hit_advance(runners, 4, self.d, make_rng())
        self.assertEqual(len(scored_runners(result)), 4)
        self.assertEqual(result.runs_scored, 4)
        self.assertTrue(runners.is_empty)

    def test_walk_with_bases_loaded_forces_in_a_run(self):
        runners = BaseRunners(first=self.a, second=self.b, third=self.c)
        result = BASERUNNING.force_advance(self.d, runners)
        runners.apply(result)
        self.assertEqual(scored_runners(result), [self.c])
        self.assertIs(runners.first, self.d)
        self.assertIs(runners.second, self.a)
        self.assertIs(runners.third, self.b)

    def test_walk_with_runner_on_second_only_does_not_force(self):
        runners = BaseRunners(second=self.b)
        result = BASERUNNING.force_advance(self.d, runners)
        runners.apply(result)
        self.assertEqual(scored_runners(result), [])
        self.assertIs(runners.second, self.b, "runner on second should hold")
        self.assertIs(runners.first, self.d)

    def test_runner_on_third_scores_on_a_single(self):
        runners = BaseRunners(third=self.c)
        result = hit_advance(runners, 1, self.d, make_rng())
        self.assertIn(self.c, scored_runners(result))
        self.assertIs(runners.first, self.d)

    def test_runners_never_pass_each_other(self):
        for seed in range(200):
            runners = BaseRunners(first=self.a, second=self.b, third=self.c)
            hit_advance(runners, 1, self.d, make_rng(seed))
            occupied = [r for r in (runners.first, runners.second, runners.third) if r]
            self.assertEqual(len(occupied), len(set(id(r) for r in occupied)))

    def test_faster_runners_take_more_extra_bases(self):
        fast = average_player("Fast")
        fast.running.sprint_speed = 30.0
        slow = average_player("Slow")
        slow.running.sprint_speed = 24.0

        def scores_from_second(runner, seed):
            rng = make_rng(seed)
            count = 0
            for _ in range(3000):
                runners = BaseRunners(second=runner)
                result = BASERUNNING.advance_on_reach(self.d, 1, runners, rng)
                if runner in scored_runners(result):
                    count += 1
            return count / 3000

        self.assertGreater(scores_from_second(fast, 5), scores_from_second(slow, 5))

    def test_force_state_tracks_who_must_run(self):
        empty = BaseRunners().force_state()
        self.assertTrue(empty.first, "the batter always forces the runner on first")
        self.assertFalse(empty.second)

        loaded = BaseRunners(first=self.a, second=self.b, third=self.c).force_state()
        self.assertTrue(loaded.second)
        self.assertTrue(loaded.third)
        self.assertEqual(loaded.lead_forced_base, 4)

        corners = BaseRunners(third=self.c).force_state()
        self.assertFalse(corners.second, "a runner on third alone is not forced")


class TestHalfInning(unittest.TestCase):
    def test_half_inning_ends_at_three_outs(self):
        for seed in range(60):
            rng = make_rng(seed)
            offense = Team.generate(rng, "Offense")
            defense = Team.generate(rng, "Defense")
            half = HalfInning(offense, defense, rng)
            runs = half.play()
            self.assertGreaterEqual(half.outs, 3)
            self.assertGreaterEqual(runs, 0)

    def test_batting_order_wraps_around(self):
        rng = make_rng(1)
        team = Team.generate(rng, "T")
        seen = [team.next_batter() for _ in range(18)]
        self.assertEqual([p.name for p in seen[:9]], [p.name for p in seen[9:]])


# ---------------------------------------------------------------------------
# Layer 5: the full game
# ---------------------------------------------------------------------------


class TestGame(unittest.TestCase):
    def test_game_completes_with_a_winner(self):
        for seed in range(40):
            rng = make_rng(seed)
            away = Team.generate(rng, "Away")
            home = Team.generate(rng, "Home")
            result = Game.start(home, away, rng).simulate()
            self.assertIsNotNone(result.winner, "game ended in a tie")
            self.assertNotEqual(result.home_score, result.away_score)
            self.assertGreaterEqual(result.innings_played, 9)

    def test_scores_are_plausible(self):
        scores = []
        rng = make_rng(99)
        for i in range(120):
            away = Team.generate(rng, f"A{i}")
            home = Team.generate(rng, f"H{i}")
            result = Game.start(home, away, rng).simulate()
            scores.extend([result.home_score, result.away_score])
        avg = statistics.mean(scores)
        self.assertGreater(avg, 3.0, f"avg {avg:.2f} runs is too few")
        self.assertLess(avg, 6.5, f"avg {avg:.2f} runs is too many")

    def test_home_team_does_not_bat_when_already_winning(self):
        """Standard rule: no bottom of the ninth if the home team leads."""
        rng = make_rng(7)
        found = False
        for i in range(80):
            away = Team.generate(rng, f"A{i}")
            home = Team.generate(rng, f"H{i}")
            game = Game.start(home, away, rng)
            result = game.simulate()
            if result.home_score > result.away_score and result.innings_played == 9:
                # Away batted 9 times, home 8 -> 17 half-innings.
                self.assertEqual(game.inning_counter % 2, 1)
                found = True
                break
        self.assertTrue(found, "never produced a home win in regulation to check")

    def test_same_seed_gives_same_game(self):
        """Determinism: essential for reproducing bugs and fair testing."""
        def play(seed):
            rng = make_rng(seed)
            away = Team.generate(rng, "Away")
            home = Team.generate(rng, "Home")
            r = Game.start(home, away, rng).simulate()
            return r.home_score, r.away_score, len(r.plays)

        self.assertEqual(play(2024), play(2024))

    def test_different_seeds_give_different_games(self):
        """Randomness: the same matchup shouldn't always play out identically."""
        def play(seed):
            rng = make_rng(seed)
            away = Team.generate(make_rng(500), "Away")
            home = Team.generate(make_rng(501), "Home")
            r = Game.start(home, away, rng).simulate()
            return r.home_score, r.away_score

        outcomes = {play(s) for s in range(40)}
        self.assertGreater(len(outcomes), 15, "same matchup is too deterministic")

    def test_play_by_play_is_recorded(self):
        rng = make_rng(3)
        away = Team.generate(rng, "Away")
        home = Team.generate(rng, "Home")
        result = Game.start(home, away, rng).simulate()
        self.assertGreater(len(result.plays), 50)
        self.assertTrue(all(p.description for p in result.plays))
        self.assertTrue(all(p.pitch_history for p in result.plays))


# ---------------------------------------------------------------------------
# The test that matters most for a manager game
# ---------------------------------------------------------------------------


class TestTalentMatters(unittest.TestCase):
    """If better players don't win more, the whole management layer is pointless.

    This is the single most important property of the simulation. Every
    roster decision the player makes is only meaningful if talent reliably
    translates into wins over a large sample.
    """

    def test_better_teams_win_more(self):
        rng = make_rng(4242)
        wins = 0
        games = 200
        for i in range(games):
            good = Team.generate(rng, f"Good{i}", talent_bonus=12.0)
            bad = Team.generate(rng, f"Bad{i}", talent_bonus=-12.0)
            result = Game.start(good, bad, rng).simulate()
            if result.winner is good:
                wins += 1
        rate = wins / games
        self.assertGreater(rate, 0.62, f"stacked team only won {rate:.1%} of games")

    def test_evenly_matched_teams_split(self):
        rng = make_rng(555)
        home_wins = 0
        games = 200
        for i in range(games):
            away = Team.generate(rng, f"A{i}")
            home = Team.generate(rng, f"H{i}")
            result = Game.start(home, away, rng).simulate()
            if result.winner is home:
                home_wins += 1
        rate = home_wins / games
        self.assertGreater(rate, 0.38, f"home win rate {rate:.1%} is lopsided")
        self.assertLess(rate, 0.62, f"home win rate {rate:.1%} is lopsided")

    def test_level_offset_scales_talent(self):
        """The hook for tee ball through the majors."""
        rng = make_rng(6)
        low = [Player.generate(rng, f"L{i}", level_offset=-20) for i in range(200)]
        high = [Player.generate(rng, f"H{i}", level_offset=20) for i in range(200)]
        low_avg = statistics.mean(p.hitting.hit_grade for p in low)
        high_avg = statistics.mean(p.hitting.hit_grade for p in high)
        self.assertGreater(high_avg, low_avg + 15)


# ---------------------------------------------------------------------------
# Stats bookkeeping
# ---------------------------------------------------------------------------


class TestPlayerStats(unittest.TestCase):
    def test_batting_average_ignores_walks(self):
        stats = PlayerStats()
        stats.record_result(AtBatResult.SINGLE)
        stats.record_result(AtBatResult.STRIKEOUT)
        stats.record_result(AtBatResult.WALK)
        self.assertEqual(stats.at_bats, 2)
        self.assertEqual(stats.plate_appearances, 3)
        self.assertAlmostEqual(stats.batting_average, 0.500)

    def test_on_base_percentage_counts_walks(self):
        stats = PlayerStats()
        stats.record_result(AtBatResult.SINGLE)
        stats.record_result(AtBatResult.STRIKEOUT)
        stats.record_result(AtBatResult.WALK)
        self.assertAlmostEqual(stats.on_base_percentage, 2 / 3)

    def test_slugging_weights_extra_base_hits(self):
        stats = PlayerStats()
        stats.record_result(AtBatResult.HOME_RUN)
        stats.record_result(AtBatResult.STRIKEOUT)
        self.assertAlmostEqual(stats.slugging, 2.0)

    def test_era_computation(self):
        stats = PlayerStats()
        stats.outs_recorded = 27
        stats.earned_runs = 3
        self.assertAlmostEqual(stats.innings_pitched, 9.0)
        self.assertAlmostEqual(stats.era, 3.0)

    def test_empty_stats_do_not_divide_by_zero(self):
        stats = PlayerStats()
        self.assertEqual(stats.batting_average, 0.0)
        self.assertEqual(stats.era, 0.0)
        self.assertEqual(stats.ops, 0.0)


class TestTeamValidation(unittest.TestCase):
    def test_short_lineup_rejected(self):
        rng = make_rng()
        team = Team.generate(rng, "T")
        team.lineup = Lineup(batting_order=team.lineup[:8])
        with self.assertRaises(ValueError):
            team.validate()

    def test_duplicate_player_rejected(self):
        rng = make_rng()
        team = Team.generate(rng, "T")
        team.lineup[1] = team.lineup[0]
        with self.assertRaises(ValueError):
            team.validate()

    def test_missing_pitcher_rejected(self):
        rng = make_rng()
        team = Team.generate(rng, "T")
        team.starting_pitcher = None
        with self.assertRaises(ValueError):
            team.validate()

    def test_generated_team_is_valid(self):
        rng = make_rng()
        Team.generate(rng, "T").validate()


# ---------------------------------------------------------------------------
# The engine seams: each stage testable on its own
# ---------------------------------------------------------------------------


class TestFieldingEngine(unittest.TestCase):
    """Physical outcomes only. Hit vs. error is not this engine's job."""

    def setUp(self):
        self.rng = make_rng()
        self.defense = Team.generate(self.rng, "Defense")
        self.engine = FieldingEngine()

    def test_over_the_fence_needs_no_fielder(self):
        blast = BattedBall(110.0, 30.0, 0.0, 450.0, 5.5)
        result = self.engine.resolve(blast, self.defense, Situation(), self.rng)
        self.assertIs(result.outcome, FieldingOutcome.OVER_THE_FENCE)
        self.assertIsNone(result.fielder)

    def test_way_foul_is_out_of_play(self):
        hooked = BattedBall(95.0, 30.0, 60.0, 300.0, 4.0)
        result = self.engine.resolve(hooked, self.defense, Situation(), self.rng)
        self.assertIs(result.outcome, FieldingOutcome.FOUL)

    def test_never_returns_a_scoring_judgment(self):
        """The enum has no HIT or ERROR member; that is deliberate."""
        names = {m.name for m in FieldingOutcome}
        self.assertNotIn("HIT", names)
        self.assertNotIn("ERROR", names)

    def test_ground_balls_are_fielded_along_their_path(self):
        """The largest v0.1 calibration bug.

        A grounder first touches grass 60-80 ft from the plate while
        infielders play at ~145 ft. Judging it by the landing point put the
        ball 75 ft from the shortstop and made nearly every grounder a hit.
        This one is hit straight at the shortstop but lands short of him.
        """
        at_the_shortstop = BattedBall(85.0, 2.0, -12.0, 70.0, 0.0)
        outcomes = [
            self.engine.resolve(
                at_the_shortstop, self.defense, Situation(), make_rng(s)
            ).outcome
            for s in range(200)
        ]
        fielded = sum(o is FieldingOutcome.FIELDED_CLEANLY for o in outcomes)
        self.assertGreater(
            fielded, 150, "a grounder hit right at the shortstop is not being fielded"
        )

    def test_hard_ball_up_the_middle_gets_through(self):
        """The flip side: the gap between short and second is a real hole."""
        up_the_middle = BattedBall(98.0, 2.0, 0.0, 95.0, 0.0)
        outcomes = [
            self.engine.resolve(
                up_the_middle, self.defense, Situation(), make_rng(s)
            ).outcome
            for s in range(50)
        ]
        self.assertTrue(all(o is FieldingOutcome.THROUGH_INFIELD for o in outcomes))


class TestOfficialScorer(unittest.TestCase):
    """The same physical play scores differently depending on judgment."""

    def setUp(self):
        self.scorer = OfficialScorer()
        self.grounder = BattedBall(95.0, 2.0, 0.0, 90.0, 0.0)

    def _score(self, outcome, bases=0, safe=False):
        from baseball import BaserunningResult

        return self.scorer.score(
            PitchCall.IN_PLAY,
            self.grounder,
            FieldingResult(outcome=outcome, fielder=average_player("F")),
            BaserunningResult(batter_bases=bases, batter_safe=safe),
            Situation(),
        ).result

    def test_misplay_is_an_error_not_a_hit(self):
        self.assertIs(self._score(FieldingOutcome.MISPLAYED, 1, True), AtBatResult.ERROR)

    def test_same_clean_field_is_out_or_infield_hit(self):
        """Identical fielding; the baserunning result decides the ruling."""
        self.assertIs(
            self._score(FieldingOutcome.FIELDED_CLEANLY, 0, False),
            AtBatResult.GROUND_OUT,
        )
        self.assertIs(
            self._score(FieldingOutcome.FIELDED_CLEANLY, 1, True),
            AtBatResult.SINGLE,
        )

    def test_bases_decide_the_size_of_the_hit(self):
        self.assertIs(self._score(FieldingOutcome.DROPPED_IN, 1, True), AtBatResult.SINGLE)
        self.assertIs(self._score(FieldingOutcome.DROPPED_IN, 2, True), AtBatResult.DOUBLE)
        self.assertIs(self._score(FieldingOutcome.DROPPED_IN, 3, True), AtBatResult.TRIPLE)

    def test_strikeout_and_walk_come_from_the_count(self):
        for call, expected in (
            (PitchCall.SWINGING_STRIKE, AtBatResult.STRIKEOUT),
            (PitchCall.CALLED_STRIKE, AtBatResult.STRIKEOUT),
            (PitchCall.BALL, AtBatResult.WALK),
            (PitchCall.HIT_BY_PITCH, AtBatResult.HIT_BY_PITCH),
        ):
            self.assertIs(
                self.scorer.score(call, None, None, None, Situation()).result, expected
            )


class TestPlayIsComplete(unittest.TestCase):
    """Play must carry an int out count -- that is what unlocks double plays."""

    def test_outs_recorded_is_an_integer(self):
        rng = make_rng(17)
        away = Team.generate(rng, "Away")
        home = Team.generate(rng, "Home")
        result = Game.start(home, away, rng).simulate()
        for play in result.plays:
            self.assertIsInstance(play.outs_recorded, int)
            self.assertNotIsInstance(play.outs_recorded, bool)

    def test_runs_reconcile_with_advancements(self):
        rng = make_rng(23)
        away = Team.generate(rng, "Away")
        home = Team.generate(rng, "Home")
        result = Game.start(home, away, rng).simulate()
        for play in result.plays:
            scored = sum(1 for a in play.advancements if a.scored)
            self.assertEqual(
                scored, play.runs_scored, f"{play.description}: advancements disagree"
            )

    def test_total_runs_match_the_final_score(self):
        rng = make_rng(31)
        away = Team.generate(rng, "Away")
        home = Team.generate(rng, "Home")
        result = Game.start(home, away, rng).simulate()
        self.assertEqual(
            sum(p.runs_scored for p in result.plays),
            result.home_score + result.away_score,
        )


class TestSituationIsImmutable(unittest.TestCase):
    def test_engines_cannot_mutate_the_game_through_it(self):
        situation = Situation(inning=3, outs=2)
        with self.assertRaises(Exception):
            situation.outs = 0

    def test_base_runners_are_snapshotted(self):
        live = BaseRunners(first=average_player("A"))
        snap = live.snapshot()
        live.clear()
        self.assertIsNotNone(snap.first, "snapshot followed the live base state")


class TestPlayerIsPersistent(unittest.TestCase):
    """A Player must be safe to reuse across simulations."""

    def test_same_player_in_two_games_does_not_interfere(self):
        rng = make_rng(64)
        shared = Team.generate(rng, "Shared")
        other_a = Team.generate(rng, "A")
        other_b = Team.generate(rng, "B")

        Game.start(shared, other_a, make_rng(1)).simulate()
        first_pitcher = shared.starting_pitcher
        carried = shared.state_for(first_pitcher).pitches_thrown

        Game.start(shared, other_b, make_rng(1)).simulate()
        self.assertGreater(carried, 0, "no pitches were thrown to check")
        # Game.start resets per-game state, so fatigue cannot snowball.
        self.assertLessEqual(
            shared.state_for(first_pitcher).pitches_thrown,
            first_pitcher.pitching.stamina + 40,
            "pitch count carried across games",
        )


class TestPerPlateAppearanceRNG(unittest.TestCase):
    """The two properties step 7 exists to provide."""

    def test_streams_are_stable_across_processes(self):
        """Pinned value. The v0.3 sketch used hash(), which Python
        randomizes per process for strings -- that silently destroys the
        same-seed replay this feature is for. A golden value fails loudly
        if anyone swaps the derivation back."""
        self.assertAlmostEqual(
            derive(7, 1, "top", 0, 0).random(), 0.2816287460455701, places=15
        )

    def test_batting_around_does_not_reuse_a_stream(self):
        """batter_index alone collides when a team bats around."""
        first_time = derive(7, 1, "top", 0, 3).random()
        second_time = derive(7, 1, "top", 9, 3).random()
        self.assertNotEqual(first_time, second_time)

    def test_tags_separate_decisions_in_one_slot(self):
        self.assertNotEqual(
            derive(7, 1, "top", 0, 0, "pa").random(),
            derive(7, 1, "top", 0, 0, "steal").random(),
        )

    def test_same_seed_reproduces_exactly(self):
        def play():
            away = Team.generate(make_rng(500), "Away")
            home = Team.generate(make_rng(501), "Home")
            r = Game.start(home, away, make_rng(3), seed=9090).simulate()
            return [(p.official_result, p.pitches, p.runs_scored) for p in r.plays]

        self.assertEqual(play(), play())

    def test_a_config_change_perturbs_only_what_it_touches(self):
        """The point of per-PA streams.

        Under one shared generator, changing any probability shifts the
        number of draws and reshuffles every later result, so calibration
        moved even for behaviorally neutral edits.
        """
        from dataclasses import replace as replace_config

        from baseball import SimulationConfig

        def play(config):
            away = Team.generate(make_rng(500), "Away")
            home = Team.generate(make_rng(501), "Home")
            r = Game.start(
                home, away, make_rng(3), config=config, seed=4141
            ).simulate()
            return [(p.batter.name, p.official_result) for p in r.plays]

        base = SimulationConfig.mlb()
        nudged = replace_config(base, hbp_rate=base.hbp_rate * 1.5)

        a, b = play(base), play(nudged)
        shared = sum(1 for x, y in zip(a, b) if x == y)
        fraction = shared / max(len(a), len(b))
        self.assertGreater(
            fraction,
            0.5,
            f"only {fraction:.0%} of plays survived an unrelated knob change",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
