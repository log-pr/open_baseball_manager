# Baseball Simulation Engine (v0.3)

A pitch-by-pitch baseball simulator: the core layer of the manager game.
No dependencies beyond the Python 3 standard library.

Scope is deliberately one game between two teams. No season, roster
management, trading, or training yet — those get built on top once this
layer is trustworthy.

## Quick start

```bash
python3 demo.py game          # full game with play-by-play
python3 demo.py boxscore      # full game, box score only
python3 demo.py pitch         # a single pitch, broken down
python3 demo.py atbat         # one plate appearance, pitch by pitch
python3 demo.py contact       # batted ball physics on 15 swings
python3 demo.py inning        # one half-inning
python3 demo.py scout         # 20-80 scouting reports for a team
python3 demo.py series 200    # does talent actually win?

python3 -m unittest test_baseball -v   # 75 tests
python3 calibrate.py 500               # compare output to real MLB rates
```

Every command takes an optional seed to reproduce a run exactly:

```bash
python3 demo.py game 2024
```

## Layout

```
baseball/
  config.py       SimulationConfig + ParkConfig: every tuned constant
  enums.py        Position, PitchType, AtBatResult, FieldingOutcome, geometry
  player.py       Player, the four scouting profiles, PlayerStats
  state.py        PlayerGameState, Lineup, BaseRunners, Situation
  pitch.py        One pitched ball (immutable record)
  batted_ball.py  Contact physics only
  events.py       FieldingResult, Advancement, Play — the event record
  engines.py      The five decision engines
  rngs.py         Per-plate-appearance random streams
  at_bat.py       The plate appearance loop
  team.py         Team
  game.py         HalfInning, Game, GameResult
demo.py           CLI for exploring each layer
calibrate.py      Tuning harness: simulate many games, compare to real MLB
test_baseball.py  Test suite, organized bottom-up by layer
```

## How one plate appearance flows

```
Situation (immutable snapshot)
        |
   AtBat.simulate()        -> PlateAppearanceOutcome   (no base state)
        |
   FieldingEngine.resolve() -> FieldingResult   (caught? through? misplayed?)
        |
   BaserunningEngine.advance() -> advancements, runs, outs
        |
   OfficialScorer.score()   -> AtBatResult, RBI, stat updates
        |
      Play  ---> HalfInning applies it to BaseRunners and outs
```

Each arrow is a testable seam: the failing stage tells you which engine
broke.

## Design notes

**Ratings use the 20-80 scouting scale.** 50 is average, each 10 points is
about one standard deviation. `level_offset` shifts the center of every
grade distribution, so a tee-ball league is just a large negative offset.

**Control and command are separate.** Control is accuracy (do you throw
strikes at all); command is precision (do you hit the spot you aimed at).
A pitcher can have one without the other, and they fail differently.

**Hidden ratings vs. observed stats.** `HittingProfile.hit_grade` is true
talent and drives the simulation. `PlayerStats.batting_average` is what you
observe. The gap between them is the entire point of a manager game: you
judge players on noisy samples, not on their real numbers.

**Fielding and scoring are separate decisions.** `FieldingEngine` answers
the physical question — did anybody get to it, did he hold on. Whether that
is a hit or an error is a judgment, and `OfficialScorer` makes it. The
`FieldingOutcome` enum deliberately has no `HIT` or `ERROR` member.

**Persistent objects hold no per-game state.** A `Player` carries ratings
only; `pitches_thrown` lives on `PlayerGameState`. The same `Player` can
appear in two simulations without interference. In v0.1 he could not.

**Engines are stateless.** Config in at construction, an immutable
`Situation` in per call, a value object out. Nothing an engine holds can
mutate the game, which is why there is no `GameContext`.

**Every tuned constant lives in `SimulationConfig`.** They interact — foul
rate and strikeout rate are coupled through count depth — and scattering
them across five engine files hides that. A swappable config is also what
makes the tee-ball-to-pro idea work properly: it changes what the sport
*is*, not just how good the players are.

**Contact physics is grounded in real measurements.** `is_barrel`
implements Statcast's published definition (98 mph minimum, 26-30 degrees
at that speed, window widening with velocity). Distance uses projectile
motion with a launch-angle-dependent drag correction, because a flat drag
factor badly overstates towering fly balls.

**Each plate appearance gets its own random stream**, derived from the game
seed. Under a single shared generator, any change to the *number* of draws
reshuffles every later result, so calibration moved even for behaviorally
neutral edits. See `rngs.py` for two non-obvious requirements the obvious
implementation gets wrong.

## Calibration

`calibrate.py` simulates many games and compares aggregate output to real
MLB rates. Over 500 games at the default seed:

| Metric | Sim | Real MLB | |
|---|---|---|---|
| Runs per team per game | 4.29 | 4.3–4.7 | low |
| Batting average | .249 | .240–.255 | |
| On-base pct | .315 | .310–.325 | |
| Slugging pct | .396 | .390–.420 | |
| Strikeout rate | 23.5% | 21–23.5% | at the edge |
| Walk rate | 7.8% | 7.5–9.5% | |
| HR per team per game | 1.28 | 1.0–1.3 | |
| Pitches per PA | 3.76 | 3.8–4.0 | low |
| Avg exit velocity | 89.3 mph | 88–90 | |
| Avg launch angle | 13.5° | 10–14 | |
| Barrel rate | 6.9% | 6–8.5% | |
| Hard-hit rate | 42.2% | 38–43% | |
| Ground ball rate | 43.9% | 40–46% | |
| Fly ball rate | 25.4% | 25–33% | |
| BABIP | .302 | .285–.305 | |

**Read a single seed with suspicion.** Run scoring at 500 games has a
seed-to-seed standard deviation of roughly 0.08 runs, so any one figure can
land a tenth of a run off the true rate. Measured across five seeds, this
engine produces about **4.21** runs per team per game — marginally below
the 4.30 benchmark floor, and it sat there before the v0.3 refactor too
(4.31 across the same five seeds, statistically indistinguishable). The
older README's 4.41 came from a favorable single seed. Runs per game and
pitches per PA are the two metrics genuinely worth tuning next.

Note that these constants were tuned against *these* benchmarks. If you
change the physics, re-run `calibrate.py` before trusting anything — the
knobs interact. Foul rate and strikeout rate in particular are coupled:
more fouls means deeper counts, which means more chances to whiff.

## Known limitations

Deliberate simplifications, roughly in the order worth fixing:

- **No double plays.** The structure now supports them — `Play.outs_recorded`
  is an int and `BaseRunners.force_state()` exists — but the logic is
  unwritten. This is the largest single gap.
- **No situational fielding.** Fielders stand in fixed spots; no shifts and
  no positioning by batter tendency.
- **Simplified baserunning.** Runners take an extra base probabilistically
  based on speed, but there's no tagging-up decision, no first-and-third
  situations, no pickoffs.
- **Sacrifice flies aren't scored as such.** A runner tags from third on a
  fly ball and the run counts, but the play is recorded as `FLY_OUT`, so it
  wrongly counts as an official at-bat. `AtBatResult.SAC_FLY` exists and is
  never produced. Carried forward from v0.1 deliberately: fixing it moves
  batting average, and v0.3 was a structural change.
- **No platoon splits.** `bats` and `throws` are stored but unused.
- **Uniform ballpark.** `ParkConfig` has hooks for altitude, temperature,
  and wind; nothing reads them.
- **Simplified relief.** A pitcher is pulled the moment he passes his
  stamina, regardless of game situation. No matchups, no closers.
- **`SimulationConfig.for_level()` is not implemented.** It needs a level
  taxonomy — what levels exist and what actually changes at each — which is
  a design decision rather than a mechanical one.

## Test suite

75 tests, organized bottom-up so the lowest failing test points at the
broken layer:

- **Pitch** — velocity ranges, zone geometry, command tightening the
  grouping, control raising the zone rate, fatigue sapping velocity
- **BattedBall** — exit velocity ranges, power driving EV, attack angle
  driving launch angle, the barrel definition against Statcast's published
  thresholds, distance plausibility
- **AtBat** — the count advances, fouls never make the third strike, at-bats
  always terminate, and the outcome carries no base state
- **Engine seams** — `FieldingEngine` never returns a scoring judgment;
  `OfficialScorer` rules differently on identical fielding; ground balls are
  fielded along their path, not at their landing point
- **Play** — `outs_recorded` is an int, advancements reconcile with runs,
  per-play runs sum to the final score
- **State** — `Situation` is immutable, base runners are snapshotted, a
  `Player` in two games no longer shares a pitch count
- **RNG** — streams are stable across processes, batting around doesn't
  reuse a stream, an unrelated config change leaves most plays untouched
- **TalentMatters** — the most important tests. Better teams win more,
  evenly matched teams split. If these ever fail, the entire management
  layer above is pointless.

## Next steps

1. Double plays, now that the structure carries the force state
2. Tune runs per game and pitches per PA back into range
3. Score sacrifice flies correctly
4. Platoon splits, since the data is already stored
5. A level taxonomy, so `SimulationConfig.for_level()` can exist
6. Season loop and standings
7. `(current, potential)` grade pairs, which is what training needs
