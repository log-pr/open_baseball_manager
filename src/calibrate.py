"""Simulate a lot of games and compare the aggregate rates to real baseball.

This is the tuning harness. It doesn't assert anything -- it prints the
simulation's league-wide numbers next to real MLB benchmarks so you can see
which constants need adjusting.
"""

import random
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

# Real MLB reference points, roughly current-era.
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
    "Fly ball rate": (0.250, 0.330),  # 25-50 deg only; popups counted separately
    "BABIP": (0.285, 0.305),
}


def run(n_games: int = 200, seed: int = 7) -> None:
    rng = random.Random(seed)

    results = Counter()
    total_pa = 0
    total_pitches = 0
    total_runs = 0
    total_team_games = 0
    innings = 0

    for i in range(n_games):
        away = Team.generate(rng, f"Away{i}")
        home = Team.generate(rng, f"Home{i}")
        game = Game.start(home, away, rng)
        result = game.simulate()

        total_runs += result.home_score + result.away_score
        total_team_games += 2
        innings += result.innings_played

        for play in result.plays:
            results[play.official_result] += 1
            total_pa += 1
            total_pitches += play.pitches

    # Batted ball characteristics measured separately so we can sample a lot
    # of contact cheaply.
    bb_stats = sample_batted_balls(rng, n=20000)

    hits = sum(results[r] for r in AtBatResult if r.is_hit)
    walks = results[AtBatResult.WALK]
    hbp = results[AtBatResult.HIT_BY_PITCH]
    ks = results[AtBatResult.STRIKEOUT]
    hrs = results[AtBatResult.HOME_RUN]
    doubles = results[AtBatResult.DOUBLE]
    triples = results[AtBatResult.TRIPLE]
    singles = results[AtBatResult.SINGLE]
    at_bats = total_pa - walks - hbp - results[AtBatResult.SAC_FLY]
    total_bases = singles + 2 * doubles + 3 * triples + 4 * hrs
    balls_in_play = at_bats - ks - hrs

    measured = {
        "Runs per team per game": total_runs / total_team_games,
        "Batting average": hits / at_bats,
        "On-base pct": (hits + walks + hbp) / (at_bats + walks + hbp),
        "Slugging pct": total_bases / at_bats,
        "Strikeout rate (per PA)": ks / total_pa,
        "Walk rate (per PA)": walks / total_pa,
        "HR per team per game": hrs / total_team_games,
        "Pitches per PA": total_pitches / total_pa,
        "BABIP": (hits - hrs) / balls_in_play if balls_in_play else 0.0,
        **bb_stats,
    }

    print(f"\n{n_games} games simulated  |  {total_pa} plate appearances\n")
    print(f"{'Metric':<28} {'Sim':>9} {'Real MLB':>16}   Status")
    print("-" * 70)
    for label, (low, high) in BENCHMARKS.items():
        value = measured.get(label)
        if value is None:
            continue
        ok = "OK" if low <= value <= high else ("LOW" if value < low else "HIGH")
        print(f"{label:<28} {value:>9.3f} {f'{low:.3f}-{high:.3f}':>16}   {ok}")

    print("\nOutcome distribution (per PA):")
    for result, count in results.most_common():
        print(f"  {result.name:<16} {count/total_pa:6.3%}")


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


if __name__ == "__main__":
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    run(count)
