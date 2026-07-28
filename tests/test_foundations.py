"""v0.4 Phase 1 foundations: roster, bullpen slot, and the decision contract.

These cover structure rather than baseball. The mechanics that use them
arrive in Phases 2-5; what is tested here is that the scaffolding holds the
invariants those phases will depend on.
"""

import random
import unittest

from baseball import (
    AIManager,
    BullpenSlot,
    Decision,
    DecisionBoundary,
    DecisionContext,
    DecisionKind,
    DecisionLog,
    GameRoster,
    Option,
    Player,
    PlayerGameState,
    PlayerStats,
    Position,
    RandomManager,
    RosterConfig,
    ScriptedManager,
    SimulationConfig,
    Situation,
    StrategyEngine,
    Team,
)

CONFIG = SimulationConfig.mlb()


def a_player(name="P", position=Position.RP):
    return Player(name=name, primary_position=position)


class TestRosterConfig(unittest.TestCase):
    def test_defaults_describe_a_26_man_roster(self):
        cfg = RosterConfig()
        # 13 position players (9 lineup + 4 bench) and 13 pitchers.
        self.assertEqual(cfg.bench_size(), 4)
        # Only one of the five starters pitches today.
        self.assertEqual(cfg.relievers_available(), 8)
        cfg.validate()

    def test_a_roster_too_thin_for_its_bench_is_rejected(self):
        with self.assertRaises(ValueError):
            RosterConfig(active_roster_size=26, max_pitchers=15).validate()

    def test_a_staff_that_is_all_rotation_is_rejected(self):
        with self.assertRaises(ValueError):
            RosterConfig(max_pitchers=5, rotation_size=5).validate()


class TestGameRoster(unittest.TestCase):
    def setUp(self):
        self.a, self.b = a_player("A"), a_player("B")
        self.roster = GameRoster(bench=[self.a], bullpen=[self.b])

    def test_a_substituted_player_cannot_re_enter(self):
        self.assertIn(self.a, self.roster.available_position_players())
        self.roster.mark_used(self.a)
        self.assertNotIn(self.a, self.roster.available_position_players())
        self.assertFalse(self.roster.is_available(self.a))

    def test_availability_is_tracked_per_group(self):
        self.roster.mark_used(self.b)
        self.assertEqual(self.roster.available_pitchers(), [])
        self.assertEqual(self.roster.available_position_players(), [self.a])


class TestPlayerGameState(unittest.TestCase):
    def test_two_counters_not_one(self):
        """Merging them would report a reliever throwing 46 pitches when
        he threw 16."""
        state = PlayerGameState(player=a_player())
        for _ in range(16):
            state.record_pitch()
        for _ in range(30):
            state.record_warmup_pitch(CONFIG)

        self.assertEqual(state.game_pitches_thrown, 16, "box score got warm-ups")
        self.assertEqual(state.fatigue_load, 16 + 30 * CONFIG.warmup_fatigue_ratio)

    def test_warmth_never_leaves_its_bounds(self):
        state = PlayerGameState(player=a_player())
        for _ in range(200):
            state.record_warmup_pitch(CONFIG)
        self.assertEqual(state.warmth, CONFIG.pitches_to_warm)
        for _ in range(500):
            state.cool(CONFIG)
        self.assertEqual(state.warmth, 0)

    def test_labels_are_derived_from_the_counter(self):
        state = PlayerGameState(player=a_player())
        self.assertEqual(state.warmth_label(CONFIG), "COLD")
        state.warmth = 15
        self.assertEqual(state.warmth_label(CONFIG), "WARMING")
        state.warmth = CONFIG.pitches_to_warm
        self.assertEqual(state.warmth_label(CONFIG), "READY")
        self.assertTrue(state.is_ready(CONFIG))

    def test_cold_penalty_scales_continuously(self):
        state = PlayerGameState(player=a_player())
        state.entry_warmth = 0
        self.assertAlmostEqual(state.cold_penalty_scale(CONFIG), 1.0)
        state.entry_warmth = CONFIG.pitches_to_warm
        self.assertAlmostEqual(state.cold_penalty_scale(CONFIG), 0.0)
        # No cliff between 29 and 30.
        state.entry_warmth = CONFIG.pitches_to_warm - 1
        near = state.cold_penalty_scale(CONFIG)
        self.assertGreater(near, 0.0)
        self.assertLess(near, 0.1)

    def test_starter_begins_ready(self):
        state = PlayerGameState(player=a_player(position=Position.SP))
        state.start_warm(CONFIG)
        self.assertTrue(state.is_ready(CONFIG))
        self.assertAlmostEqual(state.cold_penalty_scale(CONFIG), 0.0)


class TestBullpenSlot(unittest.TestCase):
    def setUp(self):
        self.slot = BullpenSlot(capacity=CONFIG.bullpen_slots)
        self.a, self.b = a_player("A"), a_player("B")
        self.states = {
            self.a: PlayerGameState(player=self.a),
            self.b: PlayerGameState(player=self.b),
        }

    def test_capacity_is_enforced(self):
        self.slot.assign(self.a)
        with self.assertRaises(ValueError):
            self.slot.assign(self.b)

    def test_at_most_capacity_pitchers_warm_at_once(self):
        self.slot.assign(self.a)
        for _ in range(10):
            self.slot.tick(self.states, CONFIG)
        warming = [s for s in self.states.values() if s.warmth > 0]
        self.assertLessEqual(len(warming), self.slot.capacity)

    def test_tick_warms_the_occupant_and_cools_everyone_else(self):
        self.states[self.b].warmth = 10
        self.slot.assign(self.a)
        for _ in range(5):
            self.slot.tick(self.states, CONFIG)
        self.assertEqual(self.states[self.a].warmth, 5)
        self.assertEqual(self.states[self.b].warmth, 5)

    def test_the_active_pitcher_is_exempt(self):
        """He is neither warming nor going cold."""
        self.states[self.b].warmth = 12
        self.slot.assign(self.a)
        for _ in range(5):
            self.slot.tick(self.states, CONFIG, active_pitcher=self.b)
        self.assertEqual(self.states[self.b].warmth, 12)

    def test_swapping_the_slot_preserves_accumulated_warmth(self):
        """Pulled at 22 and returned later resumes near where he left off,
        which is why warmth is a counter and not a state machine."""
        self.slot.assign(self.a)
        for _ in range(22):
            self.slot.tick(self.states, CONFIG)
        self.assertEqual(self.states[self.a].warmth, 22)

        self.slot.vacate(self.a)
        self.slot.assign(self.b)
        for _ in range(3):
            self.slot.tick(self.states, CONFIG)
        self.assertEqual(self.states[self.a].warmth, 19)

        self.slot.vacate(self.b)
        self.slot.assign(self.a)
        for _ in range(2):
            self.slot.tick(self.states, CONFIG)
        self.assertEqual(self.states[self.a].warmth, 21)

    def test_warming_costs_the_arm(self):
        self.slot.assign(self.a)
        for _ in range(CONFIG.pitches_to_warm):
            self.slot.tick(self.states, CONFIG)
        expected = CONFIG.pitches_to_warm * CONFIG.warmup_fatigue_ratio
        self.assertAlmostEqual(self.states[self.a].fatigue_load, expected)
        self.assertEqual(self.states[self.a].game_pitches_thrown, 0)


class TestDecisionContract(unittest.TestCase):
    def setUp(self):
        self.yes = Option("yes", payload=True)
        self.no = Option("no", payload=False)

    def _decision(self, default=None):
        return Decision(
            kind=DecisionKind.STEAL,
            boundary=DecisionBoundary.BETWEEN_PITCHES,
            options=[self.yes, self.no],
            default=default or self.no,
        )

    def test_a_decision_needs_options(self):
        with self.assertRaises(ValueError):
            Decision(
                kind=DecisionKind.STEAL,
                boundary=DecisionBoundary.BETWEEN_PITCHES,
                options=[],
                default=self.yes,
            )

    def test_the_default_must_be_a_legal_answer(self):
        with self.assertRaises(ValueError):
            Decision(
                kind=DecisionKind.STEAL,
                boundary=DecisionBoundary.BETWEEN_PITCHES,
                options=[self.yes],
                default=self.no,
            )

    def test_context_exposes_observed_stats_never_ratings(self):
        """The AI must judge players the way the human will."""
        player = a_player("Slugger")
        context = DecisionContext(
            situation=Situation(), observed_stats={player: PlayerStats()}
        )
        self.assertIsInstance(context.stats_for(player), PlayerStats)
        for forbidden in ("hitting", "pitching", "profiles", "ratings"):
            self.assertFalse(
                hasattr(context, forbidden),
                f"DecisionContext exposes {forbidden}",
            )

    def test_unknown_player_yields_an_empty_line_not_an_error(self):
        context = DecisionContext(situation=Situation())
        self.assertEqual(context.stats_for(a_player()).at_bats, 0)


class TestManagerAgents(unittest.TestCase):
    def setUp(self):
        self.yes, self.no = Option("yes"), Option("no")
        self.decision = Decision(
            kind=DecisionKind.BUNT,
            boundary=DecisionBoundary.BETWEEN_PITCHES,
            options=[self.yes, self.no],
            default=self.no,
        )

    def test_ai_falls_through_to_the_default_without_a_heuristic(self):
        self.assertIs(AIManager().decide(self.decision), self.no)

    def test_a_registered_heuristic_takes_over(self):
        ai = AIManager()
        ai.register(DecisionKind.BUNT, lambda d: d.option_labeled("yes"))
        self.assertIs(ai.decide(self.decision), self.yes)

    def test_scripted_manager_answers_from_its_script(self):
        scripted = ScriptedManager({DecisionKind.BUNT: "yes"})
        self.assertIs(scripted.decide(self.decision), self.yes)

    def test_scripted_manager_defaults_for_unscripted_kinds(self):
        self.assertIs(ScriptedManager().decide(self.decision), self.no)

    def test_random_manager_always_picks_a_legal_option(self):
        agent = RandomManager(random.Random(1))
        for _ in range(50):
            self.assertIn(agent.decide(self.decision), self.decision.options)


class TestDecisionLog(unittest.TestCase):
    def test_records_answers_in_order(self):
        log = DecisionLog()
        log.record(DecisionBoundary.BETWEEN_PITCHES, DecisionKind.STEAL, "yes")
        log.record(DecisionBoundary.POST_PLAY, DecisionKind.PITCHING_CHANGE, "no")
        self.assertEqual(len(log), 2)
        self.assertEqual(log.records[0].choice, "yes")
        self.assertEqual(log.count(DecisionKind.STEAL), 1)
        self.assertEqual(log.of_kind(DecisionKind.PITCHING_CHANGE)[0].choice, "no")

    def test_a_game_carries_a_log(self):
        from baseball import Game

        rng = random.Random(5)
        away, home = Team.generate(rng, "A"), Team.generate(rng, "H")
        game = Game.start(home, away, rng)
        self.assertIsInstance(game.decision_log, DecisionLog)
        # Nothing produces decisions until Phase 5.
        self.assertEqual(len(game.decision_log), 0)


class TestStrategyEngine(unittest.TestCase):
    def setUp(self):
        self.engine = StrategyEngine(CONFIG)

    def test_leverage_stays_in_range(self):
        for inning in (1, 5, 9, 12):
            for margin in (0, 1, 5, 12):
                for outs in (0, 1, 2):
                    value = self.engine.leverage(
                        Situation(inning=inning, outs=outs, score_differential=margin)
                    )
                    self.assertGreaterEqual(value, 0.0)
                    self.assertLessEqual(value, 1.0)

    def test_a_close_late_game_outleverages_a_blowout(self):
        close = self.engine.leverage(Situation(inning=9, score_differential=1))
        blowout = self.engine.leverage(Situation(inning=9, score_differential=11))
        self.assertGreater(close, blowout)

    def test_offers_no_decisions_yet(self):
        """Phase 1 is the contract only; mechanics arrive in Phase 5."""
        rng = random.Random(3)
        team = Team.generate(rng, "T")
        self.assertEqual(
            self.engine.pending_decisions(
                DecisionBoundary.BETWEEN_PITCHES, Situation(), team
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
