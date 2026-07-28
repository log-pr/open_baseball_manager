"""Demo CLI for poking at the simulation at every level.

Usage:
    python3 demo.py pitch            a single pitch, broken down
    python3 demo.py atbat            one plate appearance, pitch by pitch
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
    PitchCall,
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
    """Exactly one pitch, broken down. The smallest unit in the simulation."""
    header("SINGLE PITCH -- the smallest unit of the simulation")
    pitcher = Player.generate(rng, "Dave Rodriguez", Position.SP)
    batter = Player.generate(rng, "Marcus Webb", Position.CF)
    print(f"\n{pitcher.scouting_report()}\n")

    pitch = PitchingEngine().throw_pitch(
        pitcher, PlayerGameState(player=pitcher), batter, Situation(), rng
    )
    aimed_x, aimed_z = pitch.intended_location

    for label, value in (
        ("Type", str(pitch.pitch_type)),
        ("Velocity", f"{pitch.velocity:.1f} mph"),
        (
            "Effective velo",
            f"{pitch.effective_velocity:.1f} mph "
            f"(off {pitcher.pitching.extension} ft of extension)",
        ),
        ("Spin", f"{pitch.spin_rate:.0f} rpm"),
        ("Aimed at", f"({aimed_x:>5.2f}, {aimed_z:>4.2f}) ft"),
        ("Crossed at", f"({pitch.x:>5.2f}, {pitch.z:>4.2f}) ft"),
        ("Missed spot by", f"{pitch.miss_distance:.2f} ft"),
        ("In strike zone", "yes" if pitch.in_zone else "no"),
    ):
        print(f"  {label:<15} {value}")

    print(
        f"\n  Control {pitcher.pitching.control_grade} decided whether he aimed at the "
        f"zone at all.\n"
        f"  Command {pitcher.pitching.command_grade} decided how close he landed to "
        f"the spot he picked.\n"
        f"  They are separate grades because they fail differently."
    )


def demo_at_bat(rng):
    """One complete plate appearance, pitch by pitch."""
    header("FULL AT-BAT -- pitches until the plate appearance resolves")
    defense = Team.generate(rng, "Fielders")
    pitcher = defense.starting_pitcher
    batter = Player.generate(rng, "Marcus Webb", Position.CF)

    print(f"\n{pitcher.scouting_report()}\n")
    print(f"{batter.scouting_report()}\n")

    at_bat = AtBat(
        batter=batter,
        pitcher=pitcher,
        pitcher_state=PlayerGameState(player=pitcher),
        rng=rng,
    )
    print(f"{'#':>3}  {'Pitch':<22} {'Velo':>6} {'Spin':>6} {'Loc (x,z)':>14} {'Zone':>6}  Result")
    print("-" * 78)

    call = None
    while not at_bat.is_complete:
        call, pitch = at_bat.throw_next_pitch()
        zone = "yes" if pitch.in_zone else "no"
        print(
            f"{len(at_bat.pitches):>3}  {str(pitch.pitch_type):<22} {pitch.velocity:>6.1f} "
            f"{pitch.spin_rate:>6.0f} {str(pitch.actual_location):>14} {zone:>6}  "
            f"{call.name}  ({at_bat.count})"
        )
        if call is PitchCall.IN_PLAY:
            print(f"     -> {at_bat.batted_ball}")
            break

    print(
        f"\n  {call.name} on {len(at_bat.pitches)} pitches "
        f"(final count {at_bat.count})."
    )
    print(
        "  What the ball in play becomes is not decided here -- an at-bat\n"
        "  cannot know the base state. See `inning`."
        if call is PitchCall.IN_PLAY
        else "  Resolved without a ball in play."
    )


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


def demo_game(rng, verbose=True, title="FULL GAME"):
    header(title)
    away = Team.generate(rng, "Ravens")
    home = Team.generate(rng, "Hawks")
    result = Game.start(home, away, rng).simulate(verbose=verbose)
    print(f"\n{'=' * 68}\nFINAL: {result.line_score()}")
    print(f"Winner: {result.winner.name}\n")
    box_score(result)


def demo_boxscore(rng):
    """The same game as `game`, without the pitch-by-pitch narration."""
    demo_game(rng, verbose=False, title="BOX SCORE")


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


# command -> (handler, how many positional args come before the seed).
# The arity is what `series` needs: every other command takes the seed
# immediately, so a bare {name: handler} table couldn't express it and the
# odd ones out had to be special-cased ahead of the dispatch.
COMMANDS = {
    "pitch": (demo_pitch, 0),
    "atbat": (demo_at_bat, 0),
    "contact": (demo_contact, 0),
    "inning": (demo_inning, 0),
    "game": (demo_game, 0),
    "boxscore": (demo_boxscore, 0),
    "scout": (demo_scout, 0),
    "series": (demo_series, 1),
}


def main():
    args = sys.argv[1:]
    command = args[0] if args else "game"

    entry = COMMANDS.get(command)
    if entry is None:
        print(__doc__)
        sys.exit(1)

    handler, arity = entry
    extra = [int(a) for a in args[1 : 1 + arity]]
    seed = int(args[1 + arity]) if len(args) > 1 + arity else None
    handler(random.Random(seed), *extra)


if __name__ == "__main__":
    main()
