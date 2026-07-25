# Baseball Simulation Engine (v0.1)

A pitch-by-pitch baseball simulator: the core layer of the manager game.
No dependencies beyond the Python 3 standard library.

Scope is deliberately one game between two teams. No season, roster
management, trading, or training yet — those get built on top once this
layer is trustworthy.

## Quick start

```bash
python3 demo.py game          # full game with play-by-play
python3 demo.py boxscore      # full game, box score only
python3 demo.py pitch         # one pitch at a time
python3 demo.py atbat         # a plate appearance, pitch by pitch
python3 demo.py contact       # batted ball physics on 15 swings
python3 demo.py inning        # one half-inning
python3 demo.py scout         # 20-80 scouting reports for a team
python3 demo.py series 200    # does talent actually win?

python3 -m unittest test_baseball -v   # 52 tests
python3 calibrate.py 500               # compare output to real MLB rates
```

Every command takes an optional seed to reproduce a run exactly:

```bash
python3 demo.py game 2024
```

## Layout

```
baseball/
  enums.py        Position, PitchType, AtBatResult, field geometry, 20-80 helpers
  player.py       Player + HittingProfile / PitchingProfile / FieldingProfile / RunningProfile
  pitch.py        One pitched ball; control vs. command randomness
  batted_ball.py  Contact physics + fielding resolution
  at_bat.py       Plate appearance loop (the smallest testable unit)
  team.py         Team, BaseRunners, PlayerStats
  game.py         HalfInning, Game, GameResult, play-by-play
demo.py           CLI for exploring each layer
calibrate.py      Tuning harness: simulate many games, compare to real MLB
test_baseball.py  Test suite, organized bottom-up by layer
```

## Design notes

**Ratings use the 20-80 scouting scale.** 50 is average, each 10 points is
about one standard deviation. This is the industry standard, and it gives a
clean hook for the tee-ball-to-pro progression: `level_offset` shifts the
center of every grade distribution, so a tee-ball league is just a large
negative offset.

**Control and command are separate.** Control is accuracy (do you throw
strikes at all); command is precision (do you hit the spot you aimed at).
A pitcher can have one without the other, and they fail differently.

**Hidden ratings vs. observed stats.** `HittingProfile.hit_grade` is true
talent and drives the simulation. `PlayerStats.batting_average` is what you
observe. The gap between them is the entire point of a manager game: you
judge players on noisy samples, not on their real numbers.

**Randomness enters at six specific points**, not uniformly: pitch
execution, swing decision, contact quality, launch/spray angle, fielding,
and steal attempts. The grades themselves are stable.

**Contact physics is grounded in real measurements.** Exit velocity comes
from a bat-speed/pitch-speed collision model scaled by a squared-up factor.
`is_barrel` implements Statcast's actual published definition (98 mph
minimum, 26-30 degrees at that speed, window widening with velocity).
Distance uses projectile motion with a launch-angle-dependent drag
correction, because a flat drag factor badly overstates towering fly balls.

## Calibration

`calibrate.py` simulates many games and compares aggregate output to real
MLB rates. Current status over 500 games:

| Metric | Sim | Real MLB |
|---|---|---|
| Runs per team per game | 4.41 | 4.3–4.7 |
| Batting average | .251 | .240–.255 |
| On-base pct | .317 | .310–.325 |
| Slugging pct | .398 | .390–.420 |
| Strikeout rate | 22.9% | 21–23.5% |
| Walk rate | 8.0% | 7.5–9.5% |
| HR per team per game | 1.30 | 1.0–1.3 |
| Avg exit velocity | 89.4 mph | 88–90 |
| Avg launch angle | 14.0° | 10–14 |
| Barrel rate | 7.5% | 6–8.5% |
| Hard-hit rate | 42.2% | 38–43% |
| BABIP | .302 | .285–.305 |

Pitches per PA (3.76 vs. a real 3.8–4.0) is the one metric still slightly
outside range.

Note that these constants were tuned against *these* benchmarks. If you
change the physics, re-run `calibrate.py` before trusting anything — the
knobs interact. Foul rate and strikeout rate in particular are coupled:
more fouls means deeper counts, which means more chances to whiff.

## Known limitations

Deliberate simplifications, roughly in the order worth fixing:

- **No situational fielding.** Fielders stand in fixed spots; no shifts, no
  positioning by batter tendency, no double plays or force-outs at any base
  other than first.
- **Simplified baserunning.** Runners take an extra base probabilistically
  based on speed, but there's no tagging up decision, no first-and-third
  situations, no pickoffs.
- **No platoon splits.** `bats` and `throws` are stored but unused. Adding
  lefty/righty effects is a natural next step since the data is already there.
- **Uniform ballpark.** One symmetric park (330 down the lines, 400 to
  center). No park factors, altitude, wind, or weather.
- **Simplified relief.** A pitcher is pulled the moment he passes his
  stamina, regardless of game situation. No matchup decisions, no closers.
- **No catcher framing, blocking, or pop time**, despite `arm_grade`
  existing for the steal calculation.
- **Errors are simplified.** One roll against `field_grade`, always
  advancing the batter one base.

## Test suite

52 tests, organized bottom-up so the lowest failing test points at the
broken layer:

- **Pitch** — velocity ranges, zone geometry, command tightening the
  grouping, control raising the zone rate, fatigue sapping velocity
- **BattedBall** — exit velocity ranges, power driving EV, attack angle
  driving launch angle, the barrel definition against Statcast's published
  thresholds, distance plausibility
- **AtBat** — the count advances, fouls never make the third strike, at-bats
  always terminate, walks need four balls, good eyes draw more walks
- **BaseRunners** — home runs clear the bases, bases-loaded walks force in a
  run, a walk with a runner on second doesn't force, runners never pass
  each other
- **Game** — games complete with a winner, scores are plausible, the home
  team doesn't bat when already winning, same seed reproduces exactly,
  different seeds diverge
- **TalentMatters** — the most important tests. Better teams win more
  (+10/-10 talent gap wins ~93%; +5/-5 wins ~78%), evenly matched teams
  split. If these ever fail, the entire management layer above is pointless.

## Next steps

1. Fielding/positioning improvements (double plays are the biggest gap)
2. Platoon splits, since the data is already stored
3. Roster + Lineup split, so you pick the nine instead of generating them
4. Season loop and standings
5. `(current, potential)` grade pairs, which is what training needs
