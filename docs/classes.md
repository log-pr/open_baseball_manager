# Baseball Manager — Core Simulation Classes (v0.3)

Supersedes v0.2. Scope is still one game between two teams: no season,
roster management, trading, or training. Those layers get built on top once
this one is trustworthy.

This revision exists to fix three things: `AtBat` couldn't produce the
`Play` object v0.2 asked it for, the tuning constants had nowhere to live
once logic was split across engines, and `GameContext` was accumulating
into a god object.

---

## Changelog from v0.2

| # | v0.2 revision | Status | Why |
|---|---|---|---|
| 1 | `PlayerGameState` for per-game mutable state | **Accepted** | Fixes a real v0.1 bug: `pitches_thrown` on `Player` drifted unboundedly across at-bats until the pitcher walked everyone |
| 2 | `Lineup` owned by `Team` | **Accepted** | Batting order and substitution are their own concern |
| 3 | Immutable `Pitch` holding pitcher/batter refs | **Accepted** | A pitch is a historical fact; nothing should mutate one after it crosses the plate |
| 4 | `Play` replaces bare `AtBatResult` | **Accepted** | Kills the worst code in v0.1 (`HalfInning._apply_result` reverse-engineering runs and outs from an enum) |
| 5 | Split physics / fielding / scoring into engines | **Accepted, extended** | Extended to five engines — see #10 |
| 6 | Rename `BaseRunners` → `BaseState` | **Rejected** | `BaseRunners` is more concrete and domain-accurate; `-State` is a generic suffix. Pure churn against working code |
| 7 | `GameContext` holding all shared state | **Modified** | Decomposed into `SimulationConfig` + `ParkConfig` + immutable `Situation` + explicit `rng`. See "Why no GameContext" below |
| 8 | Injected RNG for deterministic replay | **Accepted, extended** | Already how v0.1 works; extended with per-PA seed derivation so a change in one probability stops reshuffling every downstream result |
| 9 | Simulation algorithms move off `Player` | **Accepted** | Codifies what the v0.1 implementation already discovered: a swing needs the count and the pitch, not just the batter |
| 10 | — | **Added** | `BaserunningEngine` — the missing fifth engine (see below) |
| 11 | — | **Added** | `SimulationConfig` — one home for every tuned constant |
| 12 | — | **Restored** | `PlayerStats`, which vanished from the v0.2 doc, now fed by `OfficialScorer` |
| — | `confidence`, `injury_modifier` on `PlayerGameState` | **Dropped** | No consumer yet. `confidence` is a design decision (does morale affect outcomes, and how?) disguised as a field |

### The contradiction v0.2 had

v0.2 asked `AtBat.simulate()` to return a `Play` containing `runs_scored`,
`runner_advancements`, and `outs_recorded`, while `HalfInning` owned
`BaseRunners`. `AtBat` cannot fill in any of those three fields:

- whether a ground ball is a **double play** depends on who's on base and how many outs there are
- whether a fly ball is a **sacrifice fly** depends on a runner being on third
- whether a fielded grounder is a **fielder's choice** or a single depends on the force situation — which means `OfficialScorer` had the same problem

So either `AtBat` gets `BaseRunners` (and is now doing baserunning,
contradicting `HalfInning` owning it), or those fields stay empty.

**Resolution:** `AtBat` produces a narrow, base-state-free outcome. A new
`BaserunningEngine` turns that outcome plus the current base state into
advancements, runs, and outs. `HalfInning` composes the results into the
`Play`. `AtBat` stays testable without constructing a base state, and the
messiest v0.1 code moves behind an interface that can be tested directly.

### Why no `GameContext`

An object holding inning, half, outs, score, weather, wind, park, *and* the
RNG, passed to every engine, has two concrete costs. Every engine can read
and write everything, and you lose the ability to test a pitch with two
arguments — `throw_pitch(pitcher, rng)` becomes "construct a whole game
context first."

It also bundles two different kinds of thing:

- **Configuration** (park, weather, wind, tuning constants) — fixed for the
  game, injected once at construction
- **Mutable state** (inning, outs, score, base runners) — changes constantly

v0.3 splits them. Engines receive their config at construction and an
**immutable** `Situation` snapshot per call. Nothing an engine holds can
mutate the game.

---

## Design principles

1. **Ratings are hidden truth; stats are noisy observation.** `hit_grade`
   drives the simulation, `batting_average` is what the manager sees. The
   gap between them is the entire point of a manager game.
2. **Persistent objects hold no per-game state.** A `Player` can appear in
   two simulations at once without interference.
3. **Engines are stateless.** Config in at construction, `Situation` in per
   call, value object out. No hidden mutation.
4. **Every tuned constant lives in `SimulationConfig`.** Splitting logic
   across engines otherwise scatters the knobs across five files.
5. **Value objects are immutable.** `Pitch`, `BattedBall`, `FieldingResult`,
   `Situation`, and `Play` are records of what happened.

---

## Layer 0 — Configuration

### SimulationConfig

Every tuned constant in one place. This is the single most practical
addition in v0.3.

The v0.1 constants were fit against real MLB benchmarks, and **they
interact**. Foul rate and strikeout rate are directly coupled: raise the
foul rate, counts get deeper, strikeouts go up whether you wanted that or
not. Several tuning iterations were lost to that coupling before it was
obvious. Scattering these across five engine files makes it invisible.

Grouped by the engine that reads them:

- **Pitching**: `zone_target_rate`, `control_grade_weight`,
  `command_sigma_base`, `command_grade_weight`, `velocity_noise`,
  `fatigue_velocity_penalty`, `fatigue_cap`
- **Batting**: `zone_swing_rate`, `two_strike_swing_rate`, `chase_rate_base`,
  `eye_grade_weight`, `whiff_base`, `whiff_velocity_weight`,
  `whiff_spin_weight`, `foul_rate_base`, `hbp_rate`
- **Contact physics**: `bat_speed_coefficient`, `pitch_speed_coefficient`,
  `squared_up_spread`, `launch_angle_offset`, `launch_angle_sigma`,
  `spray_sigma`, `drag_factor`, `drag_angle_penalty`
- **Fielding**: `infield_reach_factor`, `outfield_reach_factor`,
  `reaction_time_base`, `catch_probability_slope`
- **Baserunning**: `score_from_second_on_single`, `first_to_third_on_single`,
  `score_from_first_on_double`, `tag_from_third_rate`, `speed_weight`,
  `double_play_base_rate`

Methods:
- `classmethod mlb() -> SimulationConfig` — the calibrated defaults
- `classmethod for_level(level) -> SimulationConfig` — see below

**This is what makes the tee-ball-to-pro idea work properly.** A swappable
config means a tee-ball league can have genuinely *different physics* — no
meaningful pitch velocity, everything in play, no strikeouts — rather than
just the same game with worse grades. `level_offset` shifts talent;
`SimulationConfig` changes what the sport is.

### ParkConfig

- `wall_distance_by_angle` — a function or lookup; v0.1 used
  330 ft down the lines to 400 ft to center
- `altitude`, `temperature`, `wind_vector` *(hooks; unused at MVP)*

Separate from `SimulationConfig` because a league shares one rules config
but every stadium differs.

---

## Layer 1 — Persistent domain objects

These carry no per-game state and are safe to share across simulations.

### Player

Identity and ratings only. **No simulation methods** — see revision #9.

- `name`, `age`, `bats`, `throws`, `primary_position`
- `hitting: HittingProfile`
- `pitching: PitchingProfile`
- `fielding: FieldingProfile`
- `running: RunningProfile`

Methods:
- `classmethod generate(rng, name, position=None, level_offset=0.0) -> Player`
- `scouting_report() -> str`

### HittingProfile / PitchingProfile / FieldingProfile / RunningProfile

Carried forward from v0.1 unchanged. Grades use the 20-80 scouting scale
(50 = average, 10 points ≈ one standard deviation).

Worth restating one distinction, since it's easy to collapse: **control is
accuracy** (do you throw strikes at all), **command is precision** (do you
hit the spot you aimed at). A pitcher can have one without the other, and
they fail differently.

### PlayerStats

Restored — absent from the v0.2 doc. Accumulated observation, written by
`OfficialScorer`, which is the natural producer since scoring decisions are
exactly what stats are made of.

- Batting: `at_bats`, `hits`, `doubles`, `triples`, `home_runs`, `walks`,
  `strikeouts`, `hit_by_pitch`, `rbi`, `runs`, `plate_appearances`
- Pitching: `outs_recorded`, `earned_runs`, `strikeouts_pitched`,
  `walks_allowed`, `hits_allowed`
- Fielding: `putouts`, `assists`, `errors`

Computed properties: `batting_average`, `on_base_percentage`, `slugging`,
`ops`, `innings_pitched`, `era`

---

## Layer 2 — Per-game state

### PlayerGameState

Per-game mutable state, keyed to a player. Fixes the v0.1 bug where
`pitches_thrown` lived on `Player` and drifted across at-bats.

- `player: Player`
- `pitches_thrown: int`
- `fatigue: float` *(computed from `pitches_thrown` vs. stamina, capped —
  a gassed pitcher gets much worse but never becomes incapable of throwing
  a strike)*

Methods:
- `record_pitch()`
- `reset()`

Dropped from v0.2: `confidence` and `injury_modifier`. Add them when
something reads them.

### Lineup

- `batting_order: List[Player]` (9)
- `current_index: int`

Methods:
- `current_batter() -> Player`
- `next_batter() -> Player`
- `substitute(player_out, player_in)`
- `validate() -> None` — 9 players, no duplicates

### Team

- `name: str`
- `lineup: Lineup`
- `fielding_positions: Dict[Player, Position]`
- `starting_pitcher: Player`
- `current_pitcher: Player`
- `bullpen: List[Player]`
- `game_states: Dict[Player, PlayerGameState]`
- `stats: Dict[Player, PlayerStats]`

Methods:
- `state_for(player) -> PlayerGameState`
- `stats_for(player) -> PlayerStats`
- `needs_relief() -> bool`
- `bring_in_reliever() -> Optional[Player]`
- `validate() -> None`

The bullpen isn't optional polish. Without it one arm absorbs the whole
game, fatigue snowballs, and starters end up throwing 180 pitches and
walking 10 — which is what v0.1 did before it was added.

### BaseRunners

Name kept deliberately (v0.2 #6 rejected).

- `first`, `second`, `third: Optional[Player]`

Methods:
- `occupied(base) -> bool`
- `force_state() -> ForceState` — which bases are forced, needed by
  `BaserunningEngine` and `OfficialScorer` for double plays and
  fielder's choices
- `place(runner, base)`, `remove(base)`, `clear()`
- `snapshot() -> BaseRunners` — immutable copy for a `Situation`

Mutated **only** by `HalfInning`, applying a `BaserunningEngine` result.

### Situation (immutable)

The snapshot passed to engines. This is what replaces `GameContext`.

- `inning: int`, `half: str`
- `outs: int`
- `balls: int`, `strikes: int`
- `base_runners: BaseRunners` *(snapshot copy)*
- `score_differential: int`

Read-only. An engine cannot reach through it to mutate the game.

---

## Layer 3 — Value objects (the event record)

All immutable.

### Pitch

- `pitcher: Player`, `batter: Player`
- `pitch_type: PitchType`
- `velocity`, `spin_rate`, `effective_velocity`
- `intended_location: (x, z)`, `actual_location: (x, z)`
- `in_zone: bool`, `distance_from_center: float`, `miss_distance: float`

Created only by `PitchingEngine.throw_pitch()`.

### BattedBall

**Contact physics only** — no longer resolves fielding (v0.2 #5).

- `exit_velocity`, `launch_angle`, `spray_angle`, `distance`, `hang_time`

Methods:
- `is_barrel() -> bool` — Statcast's published definition: 98 mph minimum,
  26–30° at that speed, window widening with velocity to 8–50° at 116 mph
- `is_hard_hit() -> bool` (≥ 95 mph), `is_sweet_spot() -> bool` (8–32°)
- `batted_ball_type -> str`

Two v0.1 physics findings worth preserving, since both were bugs found by
calibration rather than by reading:

1. **Exit velocity is left-skewed**, clustered near the physical maximum
   with a long weak-contact tail. A symmetric gaussian gets average exit
   velocity, hard-hit rate, and barrel rate all wrong simultaneously.
2. **Drag must scale with launch angle.** A flat drag factor had a 103 mph
   ball at 38° carrying 433 ft (real: ~380 ft), which inflated home runs
   badly.

### FieldingResult

What the defense physically did. Output of `FieldingEngine`, input to both
`BaserunningEngine` and `OfficialScorer`.

- `fielder: Optional[Player]`
- `outcome: FieldingOutcome` — `CAUGHT, FIELDED_CLEANLY, MISPLAYED, THROUGH_INFIELD, DROPPED_IN, OVER_THE_FENCE, FOUL`
- `landing_zone: str`, `distance_traveled: float`, `time_available: float`

Deliberately **not** a hit or an error. That's a scoring judgment, made by
`OfficialScorer`.

### Advancement

- `runner: Player`, `from_base: int`, `to_base: int` *(4 = scored)*
- `out: bool`

### Play

The complete record of a plate appearance (v0.2 #4).

- `batter: Player`, `pitcher: Player`
- `pitch_history: List[Pitch]`
- `batted_ball: Optional[BattedBall]`
- `fielding_result: Optional[FieldingResult]`
- `official_result: AtBatResult`
- `outs_recorded: int` — **int, not bool**; this is what unlocks double plays
- `runs_scored: int`
- `advancements: List[Advancement]`
- `rbi_credited: int`
- `description: str` — play-by-play line

---

## Layer 4 — Engines

Stateless. Constructed with `SimulationConfig` (and `ParkConfig` where
relevant), called with explicit arguments plus a `Situation`.

### PitchingEngine
- `__init__(config: SimulationConfig)`
- `throw_pitch(pitcher, pitcher_state, batter, situation, rng) -> Pitch`

### BattingEngine
- `__init__(config: SimulationConfig)`
- `decide_swing(batter, pitch, situation, rng) -> bool`
- `resolve_swing(batter, pitch, rng) -> SwingOutcome` — `WHIFF | FOUL | CONTACT`
- `make_contact(batter, pitch, rng) -> BattedBall`

### FieldingEngine
- `__init__(config: SimulationConfig, park: ParkConfig)`
- `resolve(batted_ball, defense, situation, rng) -> FieldingResult`

Carries the v0.1 fix worth flagging loudly: **ground balls must be fielded
along their path, not at a landing point.** A grounder first touches grass
60–80 ft from the plate while infielders stand at ~145 ft, so treating the
first bounce as the landing point made essentially every ground ball a hit.
This was the single largest calibration bug in v0.1.

### BaserunningEngine *(new — the missing engine)*
- `__init__(config: SimulationConfig)`
- `advance(fielding_result, batted_ball, base_runners, outs, rng) -> BaserunningResult`

Returns `advancements`, `runs_scored`, `outs_recorded`. Owns everything
`AtBat` structurally cannot know:

- double plays (needs force state and outs)
- sacrifice flies and tagging from third
- fielder's choices
- extra bases on hits, weighted by runner speed

Real runners take extra bases — scoring from second on a single, first to
third — and modeling that is worth roughly a run per game. It isn't
optional.

### OfficialScorer
- `__init__(config: SimulationConfig)`
- `score(pitch_history, fielding_result, baserunning_result, situation) -> ScoringDecision`
- `apply_to_stats(play, batting_team, defending_team) -> None`

Rules on hit vs. error vs. fielder's choice, assigns the `AtBatResult`,
credits RBI, and writes to `PlayerStats`. Separating this from
`FieldingEngine` is what lets "the shortstop didn't reach it" and "that's
a hit, not an error" be independent decisions.

---

## Layer 5 — Orchestration

### AtBat

Produces a **narrow** outcome, not a full `Play` — the v0.2 contradiction fix.

- `batter`, `pitcher`, `pitcher_state`
- `balls`, `strikes`, `fouls`
- `pitches: List[Pitch]`
- `batted_ball: Optional[BattedBall]`

Methods:
- `throw_next_pitch(situation, rng) -> PitchCall` — **the smallest testable unit**
- `simulate(situation, rng) -> PlateAppearanceOutcome`

Where `PlateAppearanceOutcome` is `{ pitch_history, terminal_call, batted_ball }`
— strikeout, walk, HBP, or a batted ball. **No base state, no runs, no outs.**
Testable without constructing a game.

### HalfInning

Owns `BaseRunners` and composes the `Play`:

1. build a `Situation` snapshot
2. `AtBat.simulate()` → `PlateAppearanceOutcome`
3. if a batted ball: `FieldingEngine.resolve()` → `FieldingResult`
4. `BaserunningEngine.advance()` → advancements, runs, outs
5. `OfficialScorer.score()` → `AtBatResult`, RBI, stat updates
6. assemble the `Play`, apply advancements to `BaseRunners`, increment outs

- `batting_team`, `defending_team`, `inning`, `half`
- `outs`, `runs`, `base_runners`, `plays: List[Play]`

Methods:
- `play(max_runs=None) -> int`

### Game

- `home_team`, `away_team`
- `config: SimulationConfig`, `park: ParkConfig`
- `rng: Random`
- `home_score`, `away_score`, `inning_counter`

Methods:
- `classmethod start(home, away, config, park, rng) -> Game`
- `simulate(verbose=False) -> GameResult`

### GameResult
- `home_team`, `away_team`, `home_score`, `away_score`, `innings_played`
- `plays: List[Play]`
- `winner -> Optional[Team]`, `line_score() -> str`, `box_score() -> str`

---

## Data flow for one plate appearance

```
Situation (immutable snapshot)
        |
        v
   AtBat.simulate()
        |  loops: PitchingEngine.throw_pitch()
        |         BattingEngine.decide_swing() / resolve_swing()
        |         BattingEngine.make_contact()  -> BattedBall
        v
PlateAppearanceOutcome   (no base state, no runs, no outs)
        |
        v
FieldingEngine.resolve()          -> FieldingResult   (physical: caught? through?)
        |
        v
BaserunningEngine.advance()       -> advancements, runs, outs
        |
        v
OfficialScorer.score()            -> AtBatResult, RBI, stat updates
        |
        v
      Play  ---> HalfInning applies to BaseRunners and outs
```

Each arrow is a testable seam. The failing stage tells you which engine
broke.

---

## RNG strategy

A single shared RNG makes determinism brittle: any change to the *number*
of random draws shifts every downstream result. In v0.1 this meant
calibration numbers moved every time a probability was touched, even when
the change should have been behaviorally neutral.

Derive a per-plate-appearance stream instead:

```
pa_seed = hash((game_seed, inning, half, batter_index))
pa_rng  = Random(pa_seed)
```

Each plate appearance gets its own generator. Changing the whiff formula
now perturbs only the at-bats it actually touches, instead of reshuffling
the rest of the game. Same-seed replay still reproduces exactly.

---

## Migration plan

This is a substantial rewrite of code currently calibrated to 13 of 15 real
MLB benchmarks, and those constants are fragile. Don't big-bang it.

**Run `calibrate.py` before and after every step.** If runs per game or
BABIP moves, you changed behavior, not just structure. That's the gate.

| Step | Change | Risk | Why here |
|---|---|---|---|
| 1 | `SimulationConfig` — extract constants, change nothing else | Low | Do this first or every later step scatters knobs further |
| 2 | `Play` + `BaserunningEngine` | Medium | Biggest cleanup, fixes the worst v0.1 code |
| 3 | `PlayerGameState` | Low | Mechanical move of `pitches_thrown` |
| 4 | `FieldingEngine` + `OfficialScorer` split | Medium | Needs `FieldingResult` to exist first |
| 5 | `PitchingEngine` + `BattingEngine` | Medium | Mostly relocating working logic |
| 6 | `Lineup` extraction | Low | Independent of everything above |
| 7 | Per-PA RNG streams | **High** | Deliberately last — it invalidates every existing seed, so do it when the structure has stopped moving |

Step 1 before step 2 is the ordering that matters most. Step 7 last is the
other one.

---

## Deliberately not in v0.3

Carried forward as known gaps, roughly in the order worth fixing:

- **Double plays** — the structure now supports them (`outs_recorded: int`,
  `BaserunningEngine` with force state), but the logic isn't specified
- **Situational fielding** — fixed positions, no shifts, no positioning by
  batter tendency
- **Platoon splits** — `bats` and `throws` are stored but unused; the data
  is already there
- **Catcher framing, blocking, pop time** — `arm_grade` exists only for steals
- **Pickoffs, leads, first-and-third situations**
- **Weather and wind** — `ParkConfig` has the hooks, nothing reads them
- **Relief strategy** — pitchers are pulled on stamina alone, no matchups
  or closers