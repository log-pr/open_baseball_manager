"""Simulate many games and compare aggregate output to real baseball.

This is the tuning harness. It asserts nothing -- it prints the simulation's
league-wide numbers next to real MLB benchmarks so you can see which
constants need adjusting.

Run it across several seeds, always. Run scoring has a seed-to-seed standard
deviation around 0.09 at 500 games, which is about as wide as the gaps
typically being closed, so a single seed will happily tell you a change
worked when it did nothing. A metric counts as in range when mean +/- sd
overlaps the benchmark band.

Rows reading `--` measure a mechanic that does not exist yet. They are here
deliberately: the benchmark goes in before the mechanic, so there is a way
to tell whether new code produces a realistic rate.
"""

import argparse
import random
import statistics
import sys
from collections import Counter

sys.path.insert(0, ".")

from baseball import (  # noqa: E402
    AtBatResult,
    BattingEngine,
    Game,
    PitchingEngine,
    PlayerGameState,
    Situation,
    Team,
)

# Real MLB reference points, roughly current-era. Per team-game unless noted.
BENCHMARKS = {
    "Runs per team per game": (4.3, 4.7),
    "Batting average": (0.240, 0.255),
    "On-base pct": (0.310, 0.325),
    "Slugging pct": (0.390, 0.420),
    "Strikeout rate (per PA)": (0.210, 0.235),
    "Walk rate (per PA)": (0.075, 0.095),
    "HR per team per game": (1.0, 1.3),
    "Pitches per PA": (3.8, 4.0),
    "Avg exit velocity (mph)": (88.0, 90.0),
    "Avg launch angle (deg)": (10.0, 14.0),
    "Barrel rate (per BBE)": (0.060, 0.085),
    "Hard-hit rate (per BBE)": (0.380, 0.430),
    "Ground ball rate": (0.400, 0.460),
    "Fly ball rate": (0.250, 0.330),
    "BABIP": (0.285, 0.305),
    # --- v0.4 rows -------------------------------------------------------
    "GIDP": (0.70, 0.80),
    "Triples (per PA)": (0.003, 0.005),
    "Sacrifice flies": (0.20, 0.30),
    "Sacrifice hits": (0.10, 0.20),
    "Wild pitches": (0.30, 0.40),
    "Passed balls": (0.10, 0.20),
    "Errors": (0.55, 0.65),
    "Unearned run share": (0.07, 0.08),
    "Stolen base attempts": (0.80, 1.10),
    "Caught stealing": (0.15, 0.25),
    "Intentional walks": (0.10, 0.20),
    "Runners left on base": (6.5, 7.0),
    "Pitchers used": (4.0, 4.8),
    "Pinch hitters used": (0.4, 0.8),
}

# Metrics whose mechanic is not implemented yet. Reported as `--` rather
# than 0.000 so an unbuilt mechanic never reads as a calibration failure.
NOT_YET_IMPLEMENTED = {
    "GIDP",
    "Sacrifice flies",
    "Sacrifice hits",
    "Wild pitches",
    "Passed balls",
    "Unearned run share",
    "Intentional walks",
    "Pinch hitters used",
}


def measure(n_games: int, seed: int) -> dict:
    """One full run at one seed. Returns metric -> value."""
    rng = random.Random(seed)

    results: Counter = Counter()
    total_pa = total_pitches = 0
    total_runs = total_team_games = 0
    total_lob = 0
    total_pitchers_used = 0
    sac_flies = sac_hits = gidp = 0
    stolen = caught = 0
    wild_pitches = passed_balls = intentional_walks = 0
    earned = unearned = 0

    for i in range(n_games):
        away = Team.generate(rng, f"Away{i}")
        home = Team.generate(rng, f"Home{i}")
        result = Game.start(home, away, rng).simulate()

        total_runs += result.home_score + result.away_score
        total_team_games += 2
        total_lob += result.home_left_on_base + result.away_left_on_base

        for play in result.plays:
            results[play.official_result] += 1
            total_pa += 1
            total_pitches += play.pitches
            if play.outs_recorded >= 2:
                gidp += 1
            earned += getattr(play, "earned_runs", play.runs_scored)
            unearned += play.runs_scored - getattr(
                play, "earned_runs", play.runs_scored
            )

        for team in (result.home_team, result.away_team):
            total_pitchers_used += sum(
                1
                for player, state in team.game_states.items()
                if state.pitches_thrown > 0
            )
            for stats in team.stats.values():
                sac_flies += stats.sac_flies
                sac_hits += stats.sac_hits
                stolen += stats.stolen_bases
                caught += stats.caught_stealing
                wild_pitches += stats.wild_pitches
                passed_balls += stats.passed_balls

    bb_stats = sample_batted_balls(rng, n=20000)

    hits = sum(results[r] for r in AtBatResult if r.is_hit)
    walks = results[AtBatResult.WALK]
    hbp = results[AtBatResult.HIT_BY_PITCH]
    ks = results[AtBatResult.STRIKEOUT]
    hrs = results[AtBatResult.HOME_RUN]
    doubles = results[AtBatResult.DOUBLE]
    triples = results[AtBatResult.TRIPLE]
    singles = results[AtBatResult.SINGLE]
    errors = results[AtBatResult.ERROR]
    at_bats = total_pa - walks - hbp - results[AtBatResult.SAC_FLY]
    total_bases = singles + 2 * doubles + 3 * triples + 4 * hrs
    balls_in_play = at_bats - ks - hrs
    per_team_game = total_team_games

    return {
        "Runs per team per game": total_runs / per_team_game,
        "Batting average": hits / at_bats,
        "On-base pct": (hits + walks + hbp) / (at_bats + walks + hbp),
        "Slugging pct": total_bases / at_bats,
        "Strikeout rate (per PA)": ks / total_pa,
        "Walk rate (per PA)": walks / total_pa,
        "HR per team per game": hrs / per_team_game,
        "Pitches per PA": total_pitches / total_pa,
        "BABIP": (hits - hrs) / balls_in_play if balls_in_play else 0.0,
        "GIDP": gidp / per_team_game,
        "Triples (per PA)": triples / total_pa,
        "Sacrifice flies": sac_flies / per_team_game,
        "Sacrifice hits": sac_hits / per_team_game,
        "Wild pitches": wild_pitches / per_team_game,
        "Passed balls": passed_balls / per_team_game,
        "Errors": errors / per_team_game,
        "Unearned run share": (unearned / total_runs) if total_runs else 0.0,
        "Stolen base attempts": (stolen + caught) / per_team_game,
        "Caught stealing": caught / per_team_game,
        "Intentional walks": intentional_walks / per_team_game,
        "Runners left on base": total_lob / per_team_game,
        "Pitchers used": total_pitchers_used / per_team_game,
        "Pinch hitters used": 0.0,
        **bb_stats,
    }


def sample_batted_balls(rng: random.Random, n: int = 20000) -> dict:
    """Measure contact quality across many swings on contact."""
    from baseball.batted_ball import BattedBall

    pitching = PitchingEngine()
    batting = BattingEngine()
    situation = Situation()

    # Sample across many generated teams, not one, so these numbers reflect
    # the league-wide talent distribution instead of nine specific players.
    teams = [Team.generate(rng, f"Sample{i}") for i in range(30)]
    batters = [p for t in teams for p in t.lineup]
    pitchers = [t.starting_pitcher for t in teams]

    evs, las = [], []
    barrels = hard = ground = fly = 0
    made = 0

    while made < n:
        batter = rng.choice(batters)
        pitcher = rng.choice(pitchers)
        pitch = pitching.throw_pitch(
            pitcher, PlayerGameState(player=pitcher), batter, situation, rng
        )
        # Force a contact event so we sample batted balls, not swing decisions.
        if rng.random() < batting.whiff_probability(batter, pitch):
            continue
        if rng.random() < batting.foul_probability(batter, pitch):
            continue
        bb = BattedBall.from_contact(batter, pitch, rng)
        made += 1
        evs.append(bb.exit_velocity)
        las.append(bb.launch_angle)
        barrels += bb.is_barrel
        hard += bb.is_hard_hit
        if bb.batted_ball_type == "ground ball":
            ground += 1
        elif bb.batted_ball_type == "fly ball":
            fly += 1

    return {
        "Avg exit velocity (mph)": sum(evs) / len(evs),
        "Avg launch angle (deg)": sum(las) / len(las),
        "Barrel rate (per BBE)": barrels / made,
        "Hard-hit rate (per BBE)": hard / made,
        "Ground ball rate": ground / made,
        "Fly ball rate": fly / made,
    }


def status(mean: float, sd: float, low: float, high: float) -> str:
    """Classify a metric against its benchmark band.

    The spec's rule is "in range when mean +/- sd overlaps the band". That
    is implemented here, but split across two labels rather than one:

        OK    mean is inside the band
        EDGE  mean is outside, but mean +/- sd still overlaps it

    Both count as in range. They are distinguished because collapsing them
    hides the case that matters: a metric whose point estimate sits outside
    the band and only passes on the width of its own error bar. That reads
    as success and is how a tuning pass convinces you it worked.
    """
    if mean + sd < low:
        return "LOW"
    if mean - sd > high:
        return "HIGH"
    if low <= mean <= high:
        return "OK"
    return "EDGE"


def run(n_games: int = 200, seed: int = 7, seeds: int = 1) -> None:
    seed_list = [seed + i * 1000 for i in range(seeds)]
    runs = [measure(n_games, s) for s in seed_list]

    print(
        f"\n{n_games} games x {len(seed_list)} seed(s)  |  seeds "
        f"{', '.join(str(s) for s in seed_list)}\n"
    )
    print(f"{'Metric':<28} {'Mean':>9} {'SD':>7} {'Real MLB':>16}   Status")
    print("-" * 78)

    for label, (low, high) in BENCHMARKS.items():
        values = [r[label] for r in runs if label in r]
        if not values:
            continue
        if label in NOT_YET_IMPLEMENTED:
            print(
                f"{label:<28} {'--':>9} {'--':>7} {f'{low:.3f}-{high:.3f}':>16}"
                f"   not implemented"
            )
            continue
        mean = statistics.mean(values)
        sd = statistics.stdev(values) if len(values) > 1 else 0.0
        print(
            f"{label:<28} {mean:>9.3f} {sd:>7.3f} "
            f"{f'{low:.3f}-{high:.3f}':>16}   {status(mean, sd, low, high)}"
        )

    print("\nOutcome distribution (per PA), first seed:")
    first = runs[0]
    for label in ("Strikeout rate (per PA)", "Walk rate (per PA)"):
        print(f"  {label:<28} {first[label]:6.3%}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("games", nargs="?", type=int, default=200,
                        help="games per seed (default 200)")
    parser.add_argument("--seeds", type=int, default=5,
                        help="how many seeds to average over (default 5)")
    parser.add_argument("--seed", type=int, default=7,
                        help="base seed (default 7)")
    args = parser.parse_args()
    run(args.games, seed=args.seed, seeds=args.seeds)


if __name__ == "__main__":
    main()
