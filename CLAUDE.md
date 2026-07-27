# CLAUDE.md

Project context for Claude. Read this before making changes.

## What this is

`open_baseball_manager` — a pitch-by-pitch baseball simulation engine and
(eventually) a Football-Manager-style team management game in Python 3.

The simulation is **calibrated against real MLB statistics**. That
calibration is the project's core asset and the thing most easily broken by
a well-intentioned change.

## Commands

> Verify these against the current repo layout and correct this file if
> they've drifted.

```bash
python3 -m unittest discover -s tests      # full test suite
python3 calibrate.py --seeds 5             # MLB parity check
python3 demo.py game 42                    # play a seeded game
python3 demo.py boxscore 42                # box score only
python3 demo.py series 200                 # talent gradient check
```

## The one rule

**Run `calibrate.py` before and after any change that could affect
behavior, and compare.** If runs per team-game or BABIP moved, you changed
behavior — not just structure. Say so explicitly in your summary.

This applies to refactors too. A "pure" refactor that moves the numbers
isn't pure.

**Never tune against a single seed.** Run scoring has a seed-to-seed
standard deviation around 0.08 at 500 games, which is about as wide as the
gaps typically being closed. Use `--seeds 5` and tune against the mean.

## Architecture

Layered, with strict direction of dependency:

```
config      SimulationConfig, ParkConfig, RosterConfig
domain      Player, HittingProfile/PitchingProfile/FieldingProfile/
            RunningProfile, PlayerStats
state       Team, Lineup, GameRoster, PlayerGameState, BaseRunners, Situation
values      Pitch, BattedBall, FieldingResult, Advancement, Play  (immutable)
engines     Pitching, Batting, Fielding, Baserunning, OfficialScorer, Strategy
agents      ManagerAgent -> AIManager, ScriptedManager, HumanManager
orchestr.   AtBat, HalfInning, Game, DecisionLog
```

Detailed design lives in `docs/`. Check there before proposing structural
changes — most questions are already answered, including why some obvious
ideas were rejected.

## Design principles

These are load-bearing. Don't violate them without discussion.

1. **Ratings are hidden truth; stats are noisy observation.** `hit_grade`
   drives the simulation; `batting_average` is what a manager sees. The gap
   between them is the entire point of the game. Never let UI, AI, or
   reporting code read a `*Profile` where it should read `PlayerStats`.
2. **Persistent objects hold no per-game state.** Per-game mutable data
   lives in `PlayerGameState`, never on `Player`.
3. **Engines are stateless.** Config at construction, `Situation` per call,
   value object out. No hidden mutation.
4. **Every tuned constant lives in `SimulationConfig`.** No magic numbers in
   engine code, ever. If you need a new one, add it to the config with a
   sensible default.
5. **Value objects are immutable.** `Pitch`, `BattedBall`, `FieldingResult`,
   `Situation`, `Play` are records of what happened.

## Traps

Hard-won lessons. Several of these were real bugs that took a while to find.

**Foul rate and strikeout rate are coupled.** More fouls means deeper
counts means more chances to whiff. To raise pitches-per-PA without blowing
past the strikeout ceiling, raise `foul_rate_base` and lower `whiff_base`
*together*. Treat them as one knob with two dials.

**Ground balls are fielded along their path, not at a landing point.** A
grounder first touches grass 60–80 ft from the plate while infielders stand
at ~145 ft. Using the landing point makes essentially every ground ball a
hit. This was the single largest calibration bug in the project's history —
don't reintroduce it when touching `FieldingEngine`.

**Exit velocity is left-skewed**, clustered near the physical maximum with a
long weak-contact tail. A symmetric gaussian breaks average EV, hard-hit
rate, and barrel rate simultaneously.

**Drag scales with launch angle.** A flat drag factor had a 103 mph ball at
38° carrying 433 ft (real: ~380) and badly inflated home runs.

**Pitch counts need two counters.** `game_pitches_thrown` drives the box
score; `fatigue_load` drives the model and includes discounted bullpen
warm-up throws. Merging them misreports pitch counts.

**Sacrifice flies are in the OBP denominator**, sacrifice hits are not:
`(H + BB + HBP) / (AB + BB + HBP + SF)`. Fixing `is_at_bat` alone makes OBP
drift upward silently, and it looks like a successful tuning result.

**No run scores when the third out is a force play** or the batter-runner is
retired before reaching first. A runner crossing the plate on an
inning-ending 6-4-3 does not count.

**Changing a probability shifts every downstream result.** Per-plate-appearance
RNG streams limit the blast radius, but any change to the *number* of draws
still perturbs things. Expected, not a bug — just don't mistake it for a
behavior change when reading a diff of calibration output.

## Testing

Tests are layered bottom-up so the lowest failure names the broken layer:
pitch → contact → at-bat → baserunning → half-inning → game.

Two suites matter more than the rest:

- **`TalentMatters`** — better teams must win more (+10/−10 talent gap wins
  ~93%; +5/−5 wins ~78%). If this flattens, every roster decision in the
  management layer becomes meaningless. Re-verify it after any change that
  adds cheap outs (double plays, bunts) or new randomness.
- **`DecisionsMatter`** — a competent `AIManager` must beat a
  `RandomManager` with identical rosters. If this fails, manager decisions
  are cosmetic.

New behavior needs a test at the layer it lives in, plus a benchmark row in
`calibrate.py` if it's something real baseball measures. **Add the benchmark
row before writing the mechanic** — otherwise there's no way to know the new
code produces a realistic rate.

## Conventions

- Python 3, standard library only. **Ask before adding a dependency.**
- Type hints on public methods.
- Docstrings explain *why*, not *what* — especially for tuned constants and
  physics approximations.
- Deterministic: RNG is always injected, never module-global.
- Comments on any constant that was empirically tuned should say what it was
  tuned against.

## Current state

- v0.3 shipped: engine split, per-PA RNG streams, `SimulationConfig`
- v0.4 in progress: rules completion (double plays, triple plays, bunts,
  sacrifice flies), `StrategyEngine` + `AIManager`, bullpen warm-up,
  substitutions, then a single calibration pass
- v0.5 planned: `HumanManager`, play/skip, real-time viewing
- See `docs/` for the full specification and roadmap

## Before you finish

1. Full test suite passes
2. `calibrate.py --seeds 5` run, and any metric movement reported
3. No new magic numbers outside `SimulationConfig`
4. `TalentMatters` still passing with its usual margins
5. If you changed tuned constants, say which and why

## When unsure

State the assumption and flag it rather than guessing silently — especially
around scoring rules, which have more edge cases than they appear to. If a
change would move the calibration, say so up front rather than after.
