# v0.4 Specification — Complete the Rulebook + Decision Layer

**Status:** draft 2

**Theme:** finish the rules for a legal game, add the manager decision
layer with AI decision-making, then calibrate once.

---

## Scope

### In

- Force-play family: fielder's choice, double plays, triple plays
- Bunts: mechanics, decision, and scoring
- Sacrifice fly scoring fix
- Run-scoring plumbing: wild pitches, passed balls, tag-up advancement
- Earned vs. unearned runs
- `StrategyEngine` + `ManagerAgent` interface + `AIManager`
- Single-slot bullpen with a continuous warmth model
- Pinch hitting and pinch running per MLB rules
- Configurable roster sizes (26-man default)
- Defensive alignment (infield in/back, outfield depth)
- Mound visits with pitch/zone preference
- Single calibration pass to MLB parity

### Out — v0.5 and beyond

See the roadmap at the end. Briefly: `HumanManager`, the play/skip prompt,
real-time viewing, opposing-bullpen visibility, standing orders, and the
season loop.

### Why the split

**AI manager decisions move the calibration** — a manager who bunts,
steals, and changes pitchers changes run scoring, so those must land
*before* the tuning pass. **The human UI moves nothing**, so it defers
cleanly. v0.4 builds the full `Decision` / `ManagerAgent` contract so v0.5
is purely additive: one new `ManagerAgent` implementation and a UI loop.

---

## Design decisions confirmed

| Question | Decision |
|---|---|
| Decision layer scope | `StrategyEngine` + `AIManager`; human UI in v0.5 |
| Bullpen | **One slot**, config-driven. Swappable at any pitch |
| Warm-up | **30 pitches to ready, 30 to go cold.** Continuous counter |
| Warm-up cost | Bullpen throws feed the existing fatigue model at a discount |
| Roster | 26-man default, **configurable per league** |
| Bunt sign | Dugout sign, no mound visit consumed |
| Mound visits | 5 per game; pitching changes don't consume one |
| Pitch/zone preference | Shifts weights, doesn't force. Persists until changed |
| Infield alignment | Between pitches, free |
| Outfield depth | Plate-appearance boundary |
| DH | Pinch hitting for the DH keeps it; a DH taking the field forfeits it |

---

## Phase 0 — Instrumentation

Complete before any behavior change.

- [ ] `calibrate.py --seeds N` (default 5), reporting **mean ± sd**
- [ ] In-range determined by mean ± sd overlapping the benchmark band
- [ ] LOB diagnostic — distinguishes "not enough contact" from "not enough
      advancement," which the current harness cannot do
- [ ] New benchmark rows:

| Metric | Real MLB (per team-game unless noted) |
|---|---|
| GIDP | 0.70–0.80 |
| Triples (per PA) | ~0.4% |
| Sacrifice flies | 0.20–0.30 |
| Sacrifice hits | 0.10–0.20 |
| Wild pitches | 0.30–0.40 |
| Passed balls | 0.10–0.20 |
| Errors | 0.55–0.65 |
| Unearned runs (share of runs) | 7–8% |
| Stolen base attempts | 0.80–1.10 |
| Caught stealing | 0.15–0.25 |
| Intentional walks | 0.10–0.20 |
| Runners left on base | 6.5–7.0 |
| **Pitchers used** | **4.0–4.8** |
| **Pinch hitters used** | **0.4–0.8** |

The last two, plus sacrifice hits, are how you learn whether the AI
manager's heuristics are sane. A manager who burns his bullpen or bunts
constantly fails calibration immediately — no separate evaluation harness
needed.

---

## Phase 1 — Foundations

No behavior change. Structure the later phases need.

### 1.1 RosterConfig

```
RosterConfig:
    active_roster_size: int = 26
    max_pitchers:       int = 13
    rotation_size:      int = 5
    lineup_size:        int = 9
    min_bench:          int = 4
    use_dh:             bool = True
```

Game-day availability derives from this: 13 position players (9 lineup, 4
bench), 1 starting pitcher, 8 relievers. Non-starting rotation members are
unavailable.

Every roster number reads from config — no literals.

### 1.2 GameRoster

`Lineup` handles batting order; `GameRoster` handles availability.

- `bench: List[Player]`
- `bullpen: List[Player]`
- `used_players: Set[Player]` — **substituted players cannot re-enter**
- `available_position_players()`, `available_pitchers()`, `mark_used(player)`

### 1.3 StrategyEngine and ManagerAgent

```
StrategyEngine(config)
    pending_decisions(situation, team, roster) -> List[Decision]
    apply(decision, choice, game_state) -> None

Decision:
    kind:     DecisionKind
    options:  List[Option]
    default:  Option
    boundary: DecisionBoundary
    context:  DecisionContext

ManagerAgent (interface)
    decide(decision) -> Option

    AIManager        heuristics; every team in v0.4
    ScriptedManager  fixed answers; test double
    HumanManager     v0.5
```

**`DecisionKind`:** `STEAL`, `BUNT`, `HIT_AND_RUN`, `PINCH_HIT`,
`PINCH_RUN`, `PITCHING_CHANGE`, `BULLPEN_SLOT`, `INTENTIONAL_WALK`,
`INFIELD_ALIGNMENT`, `OUTFIELD_DEPTH`, `MOUND_VISIT`, `PITCHOUT`, `PICKOFF`

**`DecisionBoundary`:** `PRE_HALF_INNING`, `PRE_PLATE_APPEARANCE`,
`BETWEEN_PITCHES`, `MID_PLAY`, `POST_PLAY`

**Constraint:** `DecisionContext` exposes `PlayerStats`, never
`HittingProfile` or `PitchingProfile`. The AI judges players on observed
results, exactly as the human will.

### 1.4 DecisionLog

Ordered `(boundary, kind, choice)` records. **Seed + decision log = exact
replay.** Built in v0.4 even though only the AI decides, because it's what
makes v0.5's human input replayable without a redesign.

### 1.5 Step-based Game loop *(recommended)*

Convert `Game.simulate()` into `Game.step()` returning one event, with
`simulate()` as a draining wrapper.

Not needed for v0.4 — but v0.5's real-time viewing requires the simulation
to stop and resume, and a step-based loop is serializable mid-game where a
generator is not. The loop is being touched anyway; deferring means
rewriting it twice.

### 1.6 Extensions to existing types

- `BattingEngine.decide_swing() -> bool` becomes
  `decide_approach() -> Approach` (`TAKE | SWING | BUNT`)
- `FieldingResult` gains `force_available`, `lead_runner_retired`,
  `throw_error`
- `Play` gains `is_sacrifice_fly`, `is_sacrifice_hit`, `is_double_play`,
  `is_triple_play`, `is_fielders_choice`, `earned_runs`
- `PlayerStats` gains `sac_flies`, `sac_hits`, `gidp`, `stolen_bases`,
  `caught_stealing`, `unearned_runs`, `wild_pitches`, `passed_balls`
- **`PlayerGameState` gains `warmth`, `game_pitches_thrown`, `fatigue_load`,
  `entry_warmth`** — see 5.3

---

## Phase 2 — Force-play family

- [ ] **Fielder's choice first** — the prerequisite. A fielded grounder with
      a force available may retire the lead runner instead of the batter.
      Double and triple plays extend this same resolution.
- [ ] **Ground-ball double plays.** Ground ball, `FIELDED_CLEANLY`, runner
      on first, fewer than two outs. A ball nobody reached cannot be a DP.
- [ ] Conversion weighted by batter speed and pivot fielder `field_grade`.
      Target **~0.75 GIDP per team-game**.
- [ ] **Line-drive and fly-ball double plays** (runner doubled off). Rare;
      no target.
- [ ] **Triple plays.** No outs, two or more runners forced, ground ball
      fielded cleanly. **Not calibrated** — MLB sees ~4–5 per season
      league-wide (≈0.002 per team-game), unmeasurable at any sample size
      you'll run. Test reachability, not frequency.
- [ ] **Third-out force rule.** No run scores if the third out is a force
      play or the batter-runner is retired before reaching first.

---

## Phase 3 — Scoring correctness

- [ ] **Emit `AtBatResult.SAC_FLY`** — defined and currently never produced.
      Fly ball or line drive caught, fewer than two outs, **a run scores**.
      A runner advancing second-to-third is not a sac fly.
- [ ] **Sac flies belong in the OBP denominator:**
      `(H + BB + HBP) / (AB + BB + HBP + SF)`. Sacrifice *hits* are excluded
      from both sides; sacrifice *flies* from at-bats only. Fixing
      `is_at_bat` alone makes OBP drift up silently, and it will look like a
      successful tuning result.
- [ ] **Earned vs. unearned runs.** Every run currently charges the pitcher,
      so **ERA is systematically ~8% too high.** Simplification: unearned
      when an error or passed ball occurred earlier in the inning and the
      inning would otherwise have ended. Target 7–8%.
- [ ] **RBI edge cases:** none on a GIDP, none on an error-caused run.
- [ ] **Verify** `PA = AB + BB + HBP + SF + SH`.

---

## Phase 4 — Run-scoring plumbing

Not new rules — advancement the engine never generates. The missing ~0.4
runs most likely lives here.

- [ ] **Wild pitches and passed balls**, driven by pitch location distance
      from the zone and the catcher's `field_grade`
- [ ] **Tag-up advancement beyond third-to-home.** A runner on second should
      reach third on a deep fly out. v0.1 handled only third-to-home;
      confirm whether v0.3 inherited that limit
- [ ] **Advancement on errors and wild throws**, weighted by runner speed
- [ ] **Advancement scaled by where the ball landed**, not just hit type

---

## Phase 5 — Decision layer

Each item is a vertical slice: mechanic plus the `AIManager` heuristic.

### 5.1 Migrate steals

- [ ] Move steal logic out of `HalfInning` into `StrategyEngine`
- [ ] `AIManager` heuristic from observed data: runner's SB/CS record,
      catcher's observed caught-stealing rate, count, score, inning
- [ ] Targets: 0.80–1.10 attempts, 0.15–0.25 caught per team-game

### 5.2 Bunts

- [ ] **Bunt contact physics** — bypasses `make_contact()` entirely. Exit
      velocity 25–45 mph, launch angle near zero, spray biased to a line.
      Bat speed irrelevant.
- [ ] Outcomes: sacrifice, bunt single, popped-up bunt, foul bunt
- [ ] **Foul bunt with two strikes is a strikeout.** The engine cannot
      currently express this — fouls never make the third strike. Needs an
      explicit exception, and it's the bunt rule most likely to be missed.
- [ ] Distinguish sacrifice bunt from bunting for a hit
- [ ] **Sacrifice hit scoring:** excluded from at-bats **and** the OBP
      denominator. Counts as a plate appearance.
- [ ] `AIManager`: runner on first or second, fewer than two outs, close and
      late, weak hitter. **Target 0.10–0.20 per team-game — the benchmark
      self-polices an over-eager heuristic.**

### 5.3 The bullpen and pitching changes

**One slot, one continuous counter.** The bullpen holds exactly one pitcher
at a time (`bullpen_slots`, default 1). Occupancy can change on any pitch.

```
PlayerGameState.warmth: int, clamped 0 .. pitches_to_warm

    +1 per game pitch while occupying the bullpen slot
    -1 per game pitch while outside it
```

- `warmth == 30` → ready
- `warmth == 0` → cold
- everything between is partial credit

Deriving `COLD` / `WARMING` / `READY` as display labels from the counter —
rather than storing them as states — handles the awkward cases for free. A
reliever pulled from the slot at 22 and returned three pitches later
resumes at 19; no re-entry rule required.

- [ ] **Cold-entry penalty scales continuously** with
      `(pitches_to_warm - warmth) / pitches_to_warm`:
      - `cold_entry_max_control_penalty`: 8 grade
      - `cold_entry_max_command_penalty`: 8 grade
      - `cold_entry_max_velocity_penalty`: 1.5 mph
      - Locked in at `entry_warmth` and held **through the end of the
        half-inning he entered**
- [ ] **Bullpen throws feed the existing fatigue model**, at a discount:

      `fatigue_load += warmup_fatigue_ratio` per warming pitch (default 0.5)

      This is what makes repeat warm-ups costly without a separate counter.
      Against a reliever's ~55 stamina:

      | Times warmed to ready | Fatigue load | Usable arm remaining |
      |---|---|---|
      | Once | 15 | ~2.5 innings |
      | Twice | 30 | ~1.6 innings |
      | Three times | 45 | ~0.6 innings |

- [ ] **Two counters, not one.** `game_pitches_thrown` drives the box score;
      `fatigue_load` drives the model. Merging them would report a reliever
      throwing 46 pitches when he threw 16.
- [ ] The slot **frees the instant a reliever enters the game** — using your
      hot arm means starting the next one from zero
- [ ] The starting pitcher begins at `warmth = pitches_to_warm` and never
      occupies the slot; neither does whoever is currently on the mound
- [ ] `pitches_to_warm` and `pitches_to_cool` are **separate config values**,
      both defaulting to 30. Making cooling slower than warming is more
      realistic and worth trying during calibration
- [ ] `AIManager` occupies the slot when the current pitcher passes ~70% of
      stamina, or when trailing late
- [ ] Target **4.0–4.8 pitchers used per team-game**

**Emergent property worth noting:** a single slot at 30 pitches means only
~9 pitchers could theoretically be fully warmed across a whole game, and
realistically far fewer. Pitching changes are self-limiting, which should
pull naturally toward the benchmark without a separate constraint.

**The tradeoff this creates** is the point of the mechanic: a fully warm
reliever is accurate but carries fatigue before throwing a competitive
pitch; a cold one is fresh but wild. A manager caught short has a genuine
choice rather than just a punishment.

**Calibration note:** reliever `stamina` (currently ~55) may need
re-baselining once warm-up load is charged against it.

### 5.4 Pinch hitting and pinch running

- [ ] A substituted player **cannot re-enter** (`GameRoster.used_players`)
- [ ] The substitute takes the replaced player's batting-order slot
- [ ] A pinch hitter must then take a defensive position or be replaced
- [ ] **DH rules:** pinch hitting for the DH keeps the DH; a DH who takes
      the field forfeits it for the rest of the game
- [ ] Pinch runner replaces a runner on base, inherits the lineup slot
- [ ] `AIManager`: high leverage, weak hitter due up, bench bat with better
      observed OPS, late innings
- [ ] Target **0.4–0.8 pinch hitters per team-game**
- [ ] Double switch: **deferred**

### 5.5 Defensive alignment

- [ ] `DefensiveAlignment`: `NORMAL`, `INFIELD_IN`, `DOUBLE_PLAY_DEPTH`,
      `CORNERS_IN`
- [ ] `OutfieldDepth`: `NORMAL`, `SHALLOW`, `NO_DOUBLES`
- [ ] Infield changeable **between pitches, free**; outfield at the
      plate-appearance boundary
- [ ] Effects in `FieldingEngine`:
      - `INFIELD_IN` — ~15 ft shallower, less reaction time on grounders
        (more balls through) but cuts the run at the plate
      - `DOUBLE_PLAY_DEPTH` — better GIDP conversion, slightly worse range
      - `CORNERS_IN` — better bunt coverage, holes at the corners
      - `NO_DOUBLES` — concedes singles, prevents extra bases
- [ ] `AIManager`: infield in with a runner on third and fewer than two outs
      in a close game; no-doubles protecting a late lead

### 5.6 Mound visits and pitch preference

- [ ] `mound_visits_remaining`, default 5
- [ ] `MOUND_VISIT` sets a `PitchingInstruction`:
      `favored_pitch_type`, `favored_zone`
- [ ] **Shifts weights, does not force.** Persists until changed or the
      pitcher exits
- [ ] A pitching change does **not** consume a visit
- [ ] `AIManager` uses visits sparingly — burning all five by the third
      inning is a bug

### 5.7 Intentional walks

- [ ] `AIManager`: first base open, dangerous hitter, weak hitter on deck,
      late and close
- [ ] Target 0.10–0.20 per team-game

---

## Phase 6 — Calibration

Only after Phases 2–5 are merged and green.

- [ ] **Re-baseline multi-seed** before touching a constant. Expect runs to
      drop toward ~3.95 from double plays, then partially recover from
      Phase 4
- [ ] Tune runs per team-game into **4.3–4.7**
- [ ] Tune pitches per PA into **3.8–4.0** — strikeout rate sits at its
      23.5% ceiling, so **raise `foul_rate_base` and lower `whiff_base`
      together.** One knob, two dials
- [ ] Fix triples (~0.4% of PA)
- [ ] **Re-baseline reliever stamina** against warm-up load
- [ ] Verify every new benchmark row
- [ ] **Confirm across at least 5 seeds**; record multi-seed means in the
      README

---

## Phase 7 — Tests

### Invariants

- [ ] Outs never exceed 3 in a half-inning. This is the bug double plays
      will introduce, and it won't throw — it will silently end innings
      early or let them run long
- [ ] Double play impossible with two outs; triple play requires zero
- [ ] A substituted player never appears again
- [ ] Mound visits never go negative
- [ ] **At most `bullpen_slots` pitchers warming at any moment**
- [ ] **`warmth` never leaves `0 .. pitches_to_warm`**
- [ ] The active pitcher never occupies the bullpen slot

### Rules

- [ ] Third-out force rule: bases loaded, one out, inning-ending double play
      → **zero runs score**
- [ ] Foul bunt with two strikes is a strikeout
- [ ] Sac fly: no at-bat charged, RBI credited, **in the OBP denominator**
- [ ] Sac hit: excluded from both at-bats and OBP denominator
- [ ] Triple play reachable — construct the situation directly
- [ ] DH forfeited when the DH takes the field

### Bullpen

- [ ] 30 pitches in the slot reaches ready; 30 out returns to cold
- [ ] Partial warmth produces a proportional penalty
- [ ] Swapping the slot mid-warm preserves accumulated warmth
- [ ] Warming twice measurably shortens the usable outing
- [ ] `game_pitches_thrown` excludes bullpen throws

### Decision layer

- [ ] **`DecisionsMatter`** — identical rosters, `AIManager` vs.
      `RandomManager`. The competent manager should win well above half. If
      this fails, decisions are cosmetic
- [ ] **`TalentMatters` re-verified.** Double plays and bunts both give a
      worse team cheap outs. If the +10/−10 gradient flattens from ~93%, the
      mechanics are eating the signal that makes roster decisions matter —
      invisible in every other metric
- [ ] Replay determinism: seed + `DecisionLog` reproduces a game exactly
- [ ] `ScriptedManager` forcing a bunt every PA produces legal games

---

## Definition of done

1. Every `calibrate.py` metric in range on a 5-seed mean, including the
   fourteen new rows
2. Fielder's choice, double plays, triple plays, sacrifice flies, and
   sacrifice bunts all produced and scored correctly
3. ERA reflects earned runs only
4. `AIManager` makes every decision type; `HumanManager` is the only missing
   implementation
5. `DecisionsMatter` and `TalentMatters` both pass
6. Seed + `DecisionLog` reproduces any game exactly
7. README calibration table updated with multi-seed means

---

# v0.5 Roadmap — The Manager's Chair

**Theme:** put the user in the dugout. No new baseball rules, no
recalibration — v0.4 settles the simulation, v0.5 exposes it.

The scope discipline that matters: **if a v0.5 feature would move
`calibrate.py`, it belongs in v0.6.** The human manager should be playing
the same game the AI plays.

## 5.1 HumanManager

One new `ManagerAgent` implementation. If v0.4's contract is right, this
should require no engine changes.

- [ ] `HumanManager.decide(decision)` prompts and returns an `Option`
- [ ] Timeout or no answer falls through to `decision.default`
- [ ] Per-`DecisionKind` routing so the user can take pitching changes while
      the AI handles steals — same interface, different agent per kind

## 5.2 Play, skip, and see results

- [ ] At game start: **Play** or **See Results**
- [ ] *See Results* runs the existing full simulation and shows the box score
- [ ] *Play* enters the interactive loop
- [ ] **Skip** mid-game hands the remainder to `AIManager`, not to raw
      defaults, and is permanent for that game
- [ ] Wired to single-game entry in v0.5; the season loop is v0.6

## 5.3 Step-based loop and real-time presentation

- [ ] `Game.step()` if not already done in v0.4
- [ ] Pitch-by-pitch display: count, base state, outs, score, pitch type and
      location, result
- [ ] Configurable pacing, plus a key to advance manually
- [ ] Pause at any `DecisionBoundary` where the user holds that kind

## 5.4 The information model

This is the design question underneath the UI, and it's worth settling
deliberately: **what can a real manager see?**

Visible:
- Opposing lineup, batting order, and who's on deck
- **Who is in the opposing bullpen slot and roughly how warm** — this is
  public information in a real game and a legitimate input to your decisions
- Opposing pitcher's pitch count and visible fatigue
- All observed `PlayerStats` for both teams
- Score, count, base state, outs, alignment

Hidden:
- Every hidden rating on both teams — yours included. You manage on
  observation, same as the AI
- The opposing manager's pending decisions

- [ ] **Symmetry:** `AIManager` should read your bullpen too. If you're
      warming a lefty, the AI pinch-hitting a righty is exactly the kind of
      counterplay that makes the visibility meaningful rather than decorative

## 5.5 Standing orders and the tedium problem

A nine-inning game has ~70 plate appearances and ~290 pitches. Prompting at
every legal decision point makes the game unplayable. All three mechanisms
are needed:

- [ ] **Standing orders** set pre-game: "steal when the odds are good,"
      "never bunt," "pull the starter at 100 pitches"
- [ ] **Auto-manage per category** — route `DecisionKind`s to `AIManager`
      individually
- [ ] **High-leverage filter** — surface a prompt only when the decision is
      close or consequential. `StrategyEngine` already computes the options;
      it needs to also score how much the choice matters

**Design target:** a user who never intervenes still gets a sensible game.
Interventions should feel like overrides, not obligations.

## 5.6 Save, resume, and replay

- [ ] Serialize mid-game state (this is why `step()` beats a generator)
- [ ] Seed + `DecisionLog` replay, already built in v0.4
- [ ] Highlight reel: filter `Play` records by leverage or result

## 5.7 Tests

- [ ] `ScriptedManager` drives a full interactive game start to finish
- [ ] Skip mid-game produces a legal, completed game
- [ ] A human-played game replays exactly from seed + `DecisionLog`
- [ ] **A game played entirely on defaults matches the pure-AI simulation** —
      proves the interactive path and the fast path are the same game
- [ ] `calibrate.py` is unchanged by anything in v0.5

## Beyond v0.5

- **v0.6 — Season:** schedule, standings, the play/skip prompt in context,
  pitcher rest between games (where warm-up fatigue finally has teeth),
  roster moves
- **v0.7 — Development:** `(current, potential)` grade pairs, training,
  aging, the draft
- **v0.8 — Levels:** `SimulationConfig.for_level()`, tee ball through the
  majors, promotion
- **Unscheduled:** platoon splits, situational fielding and shifts, park
  factors, weather
