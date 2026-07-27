# v0.4 Class Structure — Diagrams

Mermaid source for the v0.4 architecture. Split by layer rather than shown
as one graph, because ~30 classes in a single diagram is unreadable.

Items marked *(v0.5)* are deferred but shown in context so the extension
points are visible.

---

## 1. Layer overview

```mermaid
flowchart TB
    subgraph L0["Layer 0 - Configuration"]
        SimulationConfig
        ParkConfig
        RosterConfig
    end

    subgraph L1["Layer 1 - Persistent domain"]
        Player
        Profiles["HittingProfile / PitchingProfile<br/>FieldingProfile / RunningProfile"]
        PlayerStats
    end

    subgraph L2["Layer 2 - Per-game state"]
        Team
        Lineup
        GameRoster
        BullpenSlot
        PlayerGameState
        BaseRunners
        Situation
    end

    subgraph L3["Layer 3 - Value objects"]
        Pitch
        BattedBall
        FieldingResult
        Advancement
        Play
        Decision
    end

    subgraph L4["Layer 4 - Engines"]
        PitchingEngine
        BattingEngine
        FieldingEngine
        BaserunningEngine
        OfficialScorer
        StrategyEngine
    end

    subgraph L5["Layer 5 - Agents"]
        ManagerAgent
        AIManager
        ScriptedManager
    end

    subgraph L6["Layer 6 - Orchestration"]
        AtBat
        HalfInning
        Game
        DecisionLog
    end

    L0 --> L4
    L1 --> L2
    L2 --> L4
    L4 --> L3
    L5 --> L4
    L3 --> L6
    L4 --> L6
    L6 --> DecisionLog
```

---

## 2. Configuration

```mermaid
classDiagram
    class SimulationConfig {
        +float zone_target_rate
        +float whiff_base
        +float foul_rate_base
        +float chase_rate_base
        +float squared_up_spread
        +float drag_factor
        +float drag_angle_penalty
        +float infield_reach_factor
        +float outfield_reach_factor
        +float double_play_base_rate
        +int bullpen_slots
        +int pitches_to_warm
        +int pitches_to_cool
        +float warmup_fatigue_ratio
        +int cold_entry_max_control_penalty
        +int cold_entry_max_command_penalty
        +float cold_entry_max_velocity_penalty
        +int mound_visits_per_game
        +mlb() SimulationConfig
        +for_level(level) SimulationConfig
    }

    class ParkConfig {
        +float altitude
        +float temperature
        +wall_distance_at(spray_angle) float
    }

    class RosterConfig {
        +int active_roster_size
        +int max_pitchers
        +int rotation_size
        +int lineup_size
        +int min_bench
        +bool use_dh
        +relievers_available() int
        +bench_size() int
    }
```

---

## 3. Persistent domain

```mermaid
classDiagram
    class Player {
        +String name
        +int age
        +String bats
        +String throws
        +Position primary_position
        +generate(rng, name, position, level_offset) Player
        +scouting_report() String
    }

    class HittingProfile {
        +int hit_grade
        +int power_grade
        +int eye_grade
        +float bat_speed
        +float attack_angle
        +float swing_length
        +float pull_tendency
    }

    class PitchingProfile {
        +int control_grade
        +int command_grade
        +float extension
        +int stamina
        +List~PitchArsenalEntry~ repertoire
    }

    class FieldingProfile {
        +int field_grade
        +int arm_grade
        +error_rate() float
    }

    class RunningProfile {
        +int run_grade
        +float sprint_speed
        +float steal_aggression
        +int steal_success_grade
    }

    class PlayerStats {
        +int at_bats
        +int hits
        +int walks
        +int strikeouts
        +int sac_flies
        +int sac_hits
        +int gidp
        +int stolen_bases
        +int caught_stealing
        +int earned_runs
        +int unearned_runs
        +int wild_pitches
        +int passed_balls
        +batting_average() float
        +on_base_percentage() float
        +era() float
    }

    Player *-- HittingProfile
    Player *-- PitchingProfile
    Player *-- FieldingProfile
    Player *-- RunningProfile
    Player ..> PlayerStats : observed by
```

`PlayerStats` is deliberately not owned by `Player`. Ratings are hidden
truth; stats are noisy observation held by the `Team`.

---

## 4. Per-game state

```mermaid
classDiagram
    class Team {
        +String name
        +Lineup lineup
        +GameRoster roster
        +BullpenSlot bullpen_slot
        +Player current_pitcher
        +DefensiveAlignment infield_alignment
        +OutfieldDepth outfield_depth
        +int mound_visits_remaining
        +state_for(player) PlayerGameState
        +stats_for(player) PlayerStats
        +validate() void
    }

    class Lineup {
        +List~Player~ batting_order
        +int current_index
        +current_batter() Player
        +next_batter() Player
        +substitute(out, incoming) void
    }

    class GameRoster {
        +List~Player~ bench
        +List~Player~ bullpen
        +Set~Player~ used_players
        +available_position_players() List
        +available_pitchers() List
        +mark_used(player) void
    }

    class BullpenSlot {
        +int capacity
        +List~Player~ occupants
        +assign(player) void
        +vacate(player) void
        +tick(all_pitchers) void
        +is_occupied_by(player) bool
    }

    class PlayerGameState {
        +Player player
        +int game_pitches_thrown
        +float fatigue_load
        +int warmth
        +int entry_warmth
        +fatigue() float
        +is_ready() bool
        +cold_penalty_scale() float
    }

    class BaseRunners {
        +Player first
        +Player second
        +Player third
        +force_state() ForceState
        +snapshot() BaseRunners
    }

    class Situation {
        +int inning
        +String half
        +int outs
        +int balls
        +int strikes
        +BaseRunners base_runners
        +int score_differential
    }

    Team *-- Lineup
    Team *-- GameRoster
    Team *-- BullpenSlot
    Team *-- "many" PlayerGameState
    BullpenSlot ..> PlayerGameState : ticks warmth
    Situation o-- BaseRunners
```

`BullpenSlot.tick()` runs once per game pitch: occupants gain warmth and
fatigue load, everyone else cools. `Situation` is immutable — engines get a
snapshot and cannot reach through it to mutate the game.

---

## 5. Value objects

```mermaid
classDiagram
    class Pitch {
        +Player pitcher
        +Player batter
        +PitchType pitch_type
        +float velocity
        +float spin_rate
        +bool in_zone
        +distance_from_center() float
    }

    class BattedBall {
        +float exit_velocity
        +float launch_angle
        +float spray_angle
        +float distance
        +float hang_time
        +is_barrel() bool
        +batted_ball_type() String
    }

    class FieldingResult {
        +Player fielder
        +FieldingOutcome outcome
        +bool force_available
        +bool lead_runner_retired
        +bool throw_error
    }

    class Advancement {
        +Player runner
        +int from_base
        +int to_base
        +bool out
    }

    class Play {
        +Player batter
        +Player pitcher
        +List~Pitch~ pitch_history
        +BattedBall batted_ball
        +FieldingResult fielding_result
        +AtBatResult official_result
        +int outs_recorded
        +int runs_scored
        +int earned_runs
        +bool is_sacrifice_fly
        +bool is_sacrifice_hit
        +bool is_double_play
        +bool is_triple_play
        +bool is_fielders_choice
        +String description
    }

    Play *-- "many" Pitch
    Play o-- BattedBall
    Play o-- FieldingResult
    Play *-- "many" Advancement
```

`outs_recorded` is an int, not a bool. That is what makes double and triple
plays expressible.

---

## 6. Engines and agents

```mermaid
classDiagram
    class PitchingEngine {
        +throw_pitch(pitcher, state, batter, situation, rng) Pitch
    }
    class BattingEngine {
        +decide_approach(batter, pitch, situation, rng) Approach
        +resolve_swing(batter, pitch, rng) SwingOutcome
        +make_contact(batter, pitch, rng) BattedBall
        +make_bunt_contact(batter, pitch, rng) BattedBall
    }
    class FieldingEngine {
        +resolve(batted_ball, defense, situation, rng) FieldingResult
    }
    class BaserunningEngine {
        +advance(fielding_result, base_runners, outs, rng) BaserunningResult
    }
    class OfficialScorer {
        +score(outcome, fielding, baserunning, situation) ScoringDecision
        +apply_to_stats(play, offense, defense) void
    }
    class StrategyEngine {
        +pending_decisions(situation, team, roster) List~Decision~
        +apply(decision, choice, game_state) void
        +leverage(situation) float
    }

    class Decision {
        +DecisionKind kind
        +List~Option~ options
        +Option default_option
        +DecisionBoundary boundary
        +DecisionContext context
    }

    class DecisionContext {
        +PlayerStats observed_stats
        +Situation situation
        +BullpenView opposing_bullpen
    }

    class ManagerAgent {
        <<interface>>
        +decide(decision) Option
    }
    class AIManager {
        +decide(decision) Option
    }
    class ScriptedManager {
        +decide(decision) Option
    }
    class HumanManager {
        +decide(decision) Option
    }

    ManagerAgent <|.. AIManager
    ManagerAgent <|.. ScriptedManager
    ManagerAgent <|.. HumanManager
    StrategyEngine ..> Decision : produces
    ManagerAgent ..> Decision : consumes
    Decision *-- DecisionContext
```

`DecisionContext` exposes `PlayerStats` only — never `HittingProfile` or
`PitchingProfile`. The AI judges players on observed results, the same
constraint the human faces.

`BullpenView` carries who is warming and roughly how warm, for both sides.
This is public information in a real game. `HumanManager` is v0.5, shown
here because adding it must be purely additive.

`leverage()` exists in v0.4 for AI heuristics; v0.5 reuses it to decide
which prompts are worth surfacing.

---

## 7. Orchestration

```mermaid
classDiagram
    class Game {
        +Team home_team
        +Team away_team
        +SimulationConfig config
        +ParkConfig park
        +DecisionLog decision_log
        +int inning_counter
        +step() GameEvent
        +simulate(verbose) GameResult
    }

    class HalfInning {
        +Team batting_team
        +Team defending_team
        +int outs
        +int runs
        +BaseRunners base_runners
        +List~Play~ plays
        +play(max_runs) int
    }

    class AtBat {
        +Player batter
        +Player pitcher
        +int balls
        +int strikes
        +throw_next_pitch(situation, rng) PitchCall
        +simulate(situation, rng) PlateAppearanceOutcome
    }

    class DecisionLog {
        +List~DecisionRecord~ records
        +record(boundary, kind, choice) void
        +replay_for(seed) List
    }

    class GameResult {
        +int home_score
        +int away_score
        +List~Play~ plays
        +winner() Team
        +box_score() String
    }

    Game *-- HalfInning
    HalfInning *-- AtBat
    Game *-- DecisionLog
    Game ..> GameResult : produces
```

`step()` returns one event; `simulate()` drains it. Seed plus `DecisionLog`
reproduces any game exactly.

---

## 8. Plate appearance sequence

```mermaid
sequenceDiagram
    autonumber
    participant HI as HalfInning
    participant SE as StrategyEngine
    participant MA as ManagerAgent
    participant BS as BullpenSlot
    participant AB as AtBat
    participant PE as PitchingEngine
    participant BE as BattingEngine
    participant FE as FieldingEngine
    participant BR as BaserunningEngine
    participant OS as OfficialScorer

    HI->>SE: pending_decisions PRE_PLATE_APPEARANCE
    SE-->>HI: pinch hit / alignment / IBB
    HI->>MA: decide each
    MA-->>HI: chosen options
    HI->>SE: apply choices

    loop until at-bat resolves
        HI->>SE: pending_decisions BETWEEN_PITCHES
        SE-->>HI: steal / bunt sign / bullpen slot / pickoff
        HI->>MA: decide each
        MA-->>HI: chosen options
        HI->>AB: throw_next_pitch
        AB->>PE: throw_pitch
        PE-->>AB: Pitch
        AB->>BE: decide_approach
        BE-->>AB: TAKE or SWING or BUNT
        AB->>BE: resolve_swing or bunt contact
        BE-->>AB: SwingOutcome or BattedBall
        HI->>BS: tick warmth for all pitchers
    end

    AB-->>HI: PlateAppearanceOutcome
    HI->>FE: resolve
    FE-->>HI: FieldingResult
    HI->>BR: advance
    BR-->>HI: advancements / runs / outs
    HI->>OS: score
    OS-->>HI: AtBatResult and stat updates
    HI->>HI: assemble Play and apply to BaseRunners
```

Every arrow is a testable seam. A failing stage names the broken engine.
`BullpenSlot.tick()` fires once per pitch — the single clock that drives
both warming and cooling.

---

## 9. Bullpen warmth

One slot, one counter. States are **derived** from `warmth`, not stored.

```mermaid
stateDiagram-v2
    [*] --> Cold

    Cold --> Warming : assigned to slot
    Warming --> Ready : warmth reaches pitches_to_warm
    Warming --> Cooling : removed from slot
    Ready --> Cooling : removed from slot
    Cooling --> Warming : reassigned to slot
    Cooling --> Cold : warmth reaches 0

    Cold --> Active : enters game - full penalty
    Warming --> Active : enters game - partial penalty
    Cooling --> Active : enters game - partial penalty
    Ready --> Active : enters game - no penalty

    Active --> [*] : removed from game

    note right of Warming
        warmth +1 per game pitch
        fatigue_load += warmup_fatigue_ratio
    end note

    note right of Cooling
        warmth -1 per game pitch
        no fatigue accrued
    end note

    note right of Active
        Penalty locked at entry_warmth,
        held through the end of the
        half-inning he entered.
        Slot frees immediately.
    end note
```

The starting pitcher begins at `warmth = pitches_to_warm` and never enters
the slot; neither does whoever is on the mound.

**Cold-entry penalty** scales continuously:

```
scale = (pitches_to_warm - entry_warmth) / pitches_to_warm

control  -= cold_entry_max_control_penalty  * scale
command  -= cold_entry_max_command_penalty  * scale
velocity -= cold_entry_max_velocity_penalty * scale
```

**Cost of repeat warm-ups**, at `warmup_fatigue_ratio = 0.5` against a
reliever's ~55 stamina:

| Times warmed to ready | Fatigue load | Usable arm |
|---|---|---|
| Once | 15 | ~2.5 innings |
| Twice | 30 | ~1.6 innings |
| Three times | 45 | ~0.6 innings |

---

## 10. Decision boundaries

```mermaid
flowchart TD
    A["Game start"] --> B["PRE_GAME<br/>lineup, rotation, standing orders"]
    B --> C["PRE_HALF_INNING<br/>pitching change, alignment"]
    C --> D["PRE_PLATE_APPEARANCE<br/>pinch hit, IBB, infield in, outfield depth"]
    D --> E["BETWEEN_PITCHES<br/>steal, bunt sign, bullpen slot, pitchout, pickoff"]
    E --> F["Pitch resolves - BullpenSlot ticks"]
    F --> G{"Ball in play?"}
    G -- No --> H{"At-bat over?"}
    H -- No --> E
    G -- Yes --> I["MID_PLAY<br/>send or hold the runner"]
    I --> J["POST_PLAY<br/>pitching change, defensive sub, pinch run"]
    H -- Yes --> J
    J --> K{"Three outs?"}
    K -- No --> D
    K -- Yes --> L{"Game over?"}
    L -- No --> C
    L -- Yes --> M["Final"]
```

In v0.4 every boundary resolves through `AIManager` without stopping. These
are the points v0.5's real-time mode pauses on.

---

## 11. v0.5 extension *(preview)*

Nothing in the engine changes. One new agent, one routing layer, one loop.

```mermaid
flowchart LR
    SE["StrategyEngine<br/>produces Decision"] --> R{"DecisionRouter<br/>who owns this kind?"}
    R -- "user-held" --> HM["HumanManager<br/>prompt and wait"]
    R -- "auto-managed" --> AI["AIManager"]
    R -- "standing order matches" --> SO["StandingOrders<br/>answer without prompting"]
    R -- "low leverage" --> AI

    HM --> L["DecisionLog"]
    AI --> L
    SO --> L
    L --> AP["StrategyEngine.apply"]
```

The leverage filter and standing orders sit between the router and the
prompt — that's what keeps ~290 pitches a game from becoming ~290 prompts.
`DecisionLog` records every answer regardless of source, so a human-played
game replays exactly.
