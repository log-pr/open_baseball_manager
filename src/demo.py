"""Demo CLI for poking at the simulation at every level.

Usage:
    python3 demo.py pitch            one pitch at a time, with the count
    python3 demo.py atbat            a single plate appearance, pitch by pitch
    python3 demo.py contact          batted ball physics on 15 swings
    python3 demo.py inning           one half-inning
    python3 demo.py game             a full game with play-by-play
    python3 demo.py boxscore         a full game, box score only
    python3 demo.py scout            scouting reports for a generated team
    python3 demo.py series 100       simulate N games, show the win split

Add a seed to reproduce any run exactly:
    python3 demo.py game 2024
"""

import random
import sys

from baseball import (
    AtBat,
    BattingEngine,
    Game,
    HalfInning,
    PitchingEngine,
    Player,
    PlayerGameState,
    Position,
    Situation,
    Team,
)


def header(text):
    print(f"\n{'=' * 68}\n{text}\n{'=' * 68}")


def demo_pitch(rng):
    header("SINGLE PITCH -- the smallest unit of the simulation")
    pitcher = Player.generate(rng, "Dave Rodriguez", Position.SP)
    batter = Player.generate(rng, "Marcus Webb", Position.CF)

    print(f"\n{pitcher.scouting_report()}\n")
    print(f"{batter.scouting_report()}\n")

    at_bat = AtBat(batter=batter, pitcher=pitcher, rng=rng)
    print(f"{'#':>3}  {'Pitch':<22} {'Velo':>6} {'Spin':>6} {'Loc (x,z)':>14} {'Zone':>6}  Result")
    print("-" * 78)
    n = 0
    while not at_bat.is_complete and n < 12:
        n += 1
        call, pitch = at_bat.throw_next_pitch()
        zone = "yes" if pitch.in_zone else "no"
        print(
            f"{n:>3}  {str(pitch.pitch_type):<22} {pitch.velocity:>6.1f} "
            f"{pitch.spin_rate:>6.0f} {str(pitch.actual_location):>14} {zone:>6}  "
            f"{call.name}  ({at_bat.count})"
        )
        if call.name == "IN_PLAY":
            print(f"     -> {at_bat.batted_ball}")
            break


def demo_at_bat(rng):
    header("FULL AT-BAT")
    defense = Team.generate(rng, "Fielders")
    pitcher = defense.starting_pitcher
    batter = Player.generate(rng, "Marcus Webb", Position.CF)

    for i in range(5):
        state = PlayerGameState(player=pitcher)
        at_bat = AtBat(
            batter=batter, pitcher=pitcher, pitcher_state=state, rng=rng
        )
        outcome = at_bat.simulate()
        detail = f"  |  {at_bat.batted_ball}" if at_bat.batted_ball else ""
        print(
            f"\nPA {i + 1}: {outcome.terminal_call.name} on {outcome.pitches} pitches "
            f"(final count {at_bat.count}){detail}"
        )
        for pitch in at_bat.pitches:
            print(f"    {pitch}")


def demo_contact(rng):
    header("BATTED BALL PHYSICS")
    pitcher = Player.generate(rng, "Pitcher", Position.SP)
    batter = Player.generate(rng, "Slugger", Position.RF)
    pitching = PitchingEngine()
    batting = BattingEngine()
    print(f"\n{batter.scouting_report()}\n")
    print(
        f"{'EV (mph)':>9} {'Launch':>8} {'Spray':>8} {'Dist':>7} {'Hang':>6}  "
        f"{'Type':<12} {'Barrel':>7} {'Hard':>6}"
    )
    print("-" * 72)
    for _ in range(15):
        pitch = pitching.throw_pitch(
            pitcher, PlayerGameState(player=pitcher), batter, Situation(), rng
        )
        bb = batting.make_contact(batter, pitch, rng)
        print(
            f"{bb.exit_velocity:>9.1f} {bb.launch_angle:>8.1f} {bb.spray_angle:>8.1f} "
            f"{bb.distance:>7.0f} {bb.hang_time:>6.2f}  {bb.batted_ball_type:<12} "
            f"{'YES' if bb.is_barrel else '-':>7} {'YES' if bb.is_hard_hit else '-':>6}"
        )


def demo_inning(rng):
    header("HALF-INNING")
    offense = Team.generate(rng, "Ravens")
    defense = Team.generate(rng, "Hawks")
    half = HalfInning(offense, defense, rng, inning=1, half="top")
    runs = half.play()
    for play in half.plays:
        print(play)
    print(f"\n{runs} run(s) scored.")


def demo_game(rng, verbose=True):
    header("FULL GAME")
    away = Team.generate(rng, "Ravens")
    home = Team.generate(rng, "Hawks")
    result = Game.start(home, away, rng).simulate(verbose=verbose)
    print(f"\n{'=' * 68}\nFINAL: {result.line_score()}")
    print(f"Winner: {result.winner.name}\n")
    box_score(result)


def box_score(result):
    for team in (result.away_team, result.home_team):
        print(f"\n{team.name} batting")
        print(f"  {'Player':<22} {'AB':>3} {'H':>3} {'HR':>3} {'BB':>3} {'K':>3} {'RBI':>4} {'AVG':>6}")
        print("  " + "-" * 56)
        for player in team.lineup:
            s = team.stats_for(player)
            print(
                f"  {player.name:<22} {s.at_bats:>3} {s.hits:>3} {s.home_runs:>3} "
                f"{s.walks:>3} {s.strikeouts:>3} {s.rbi:>4} {s.batting_average:>6.3f}"
            )
        pitcher = team.starting_pitcher
        ps = team.stats_for(pitcher)
        print(
            f"\n  {pitcher.name}: {ps.innings_pitched:.1f} IP, {ps.hits_allowed} H, "
            f"{ps.earned_runs} ER, {ps.walks_allowed} BB, {ps.strikeouts_pitched} K, "
            f"{team.state_for(pitcher).pitches_thrown} pitches"
        )


def demo_scout(rng):
    header("SCOUTING REPORTS")
    team = Team.generate(rng, "Hawks")
    for player in team.lineup:
        print(f"\n{player.scouting_report()}")
    print(f"\n{team.starting_pitcher.scouting_report()}")


def demo_series(rng, n=100):
    header(f"{n}-GAME SERIES -- does talent actually win?")
    good_wins = 0
    runs_for = runs_against = 0
    for i in range(n):
        good = Team.generate(rng, "Contenders", talent_bonus=10.0)
        bad = Team.generate(rng, "Cellar Dwellers", talent_bonus=-10.0)
        result = Game.start(good, bad, rng).simulate()
        if result.winner is good:
            good_wins += 1
        runs_for += result.home_score
        runs_against += result.away_score
    print(f"\nContenders (+10 talent) vs Cellar Dwellers (-10 talent)")
    print(f"  Record: {good_wins}-{n - good_wins}  ({good_wins / n:.1%})")
    print(f"  Runs scored:  {runs_for / n:.2f} per game")
    print(f"  Runs allowed: {runs_against / n:.2f} per game")


COMMANDS = {
    "pitch": demo_pitch,
    "atbat": demo_at_bat,
    "contact": demo_contact,
    "inning": demo_inning,
    "game": demo_game,
    "scout": demo_scout,
}


def main():
    args = sys.argv[1:]
    command = args[0] if args else "game"

    if command == "series":
        n = int(args[1]) if len(args) > 1 else 100
        seed = int(args[2]) if len(args) > 2 else None
        demo_series(random.Random(seed), n)
        return

    seed = int(args[1]) if len(args) > 1 else None
    rng = random.Random(seed)

    if command == "boxscore":
        away = Team.generate(rng, "Ravens")
        home = Team.generate(rng, "Hawks")
        result = Game.start(home, away, rng).simulate(verbose=False)
        header("BOX SCORE")
        print(f"\nFINAL: {result.line_score()}")
        box_score(result)
        return

    handler = COMMANDS.get(command)
    if handler is None:
        print(__doc__)
        sys.exit(1)
    handler(rng)


if __name__ == "__main__":
    main()
