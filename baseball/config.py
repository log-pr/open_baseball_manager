"""Every tuned constant in the simulation, in one place.

These constants were fit against real MLB benchmarks and **they interact**.
Foul rate and strikeout rate are the clearest example: raise the foul rate,
counts get deeper, and strikeouts go up whether or not you wanted them to.
Scattering these across the modules that read them makes that coupling
invisible, which is how tuning iterations get lost.

Re-run `calibrate.py` after touching anything in here. Nothing in this file
is safe to adjust on intuition.

Grouped by the code that reads them, since that's how you'll go looking.

Deliberately *not* here:

- **Player generation** (`PITCH_BASELINES`, bat speed and grade spreads in
  `player.py`). Those describe how a league's talent is drawn, not how the
  sport behaves.
- **Profile-derived rates** (`FieldingProfile.error_rate`,
  `RunningProfile.steal_success_rate`). Those read as attributes of a
  player, and the v0.3 design doesn't list them as config.
- **Field geometry** (`enums.py`) and defensive alignment
  (`FIELDER_POSITIONS`). Fixed rules of the sport, or a positioning concern
  that gets its own home once shifts exist.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ParkConfig:
    """One stadium. A league shares a SimulationConfig but not a park."""

    # Wall distance is interpolated from the foul lines to straightaway
    # center: 330 ft down the lines out to 400 ft in center.
    line_distance: float = 330.0
    center_bonus: float = 70.0

    # Hooks, currently unread.
    altitude: float = 0.0
    temperature: float = 70.0
    wind_vector: tuple = (0.0, 0.0)

    def wall_distance(self, spray_angle: float) -> float:
        """Distance to the fence at a given spray angle, in feet."""
        import math

        capped = min(45.0, abs(spray_angle))
        return self.line_distance + self.center_bonus * math.cos(
            math.radians(capped * 2)
        )


@dataclass(frozen=True)
class RosterConfig:
    """Roster shape for one league. Every roster number reads from here.

    Game-day availability derives from these: with the defaults, 13 position
    players (9 in the lineup, 4 on the bench), one starting pitcher, and 8
    relievers. The other four rotation members are unavailable today.
    """

    active_roster_size: int = 26
    max_pitchers: int = 13
    rotation_size: int = 5
    lineup_size: int = 9
    min_bench: int = 4
    use_dh: bool = True

    def relievers_available(self) -> int:
        """Pitchers who can appear today: everyone but the rotation."""
        return self.max_pitchers - self.rotation_size

    def bench_size(self) -> int:
        return self.active_roster_size - self.max_pitchers - self.lineup_size

    def validate(self) -> None:
        if self.bench_size() < self.min_bench:
            raise ValueError(
                f"bench of {self.bench_size()} is below min_bench "
                f"{self.min_bench}; widen the roster or carry fewer pitchers"
            )
        if self.relievers_available() < 1:
            raise ValueError("no relievers available: rotation fills the staff")


@dataclass(frozen=True)
class SimulationConfig:
    """The tuning knobs. `SimulationConfig.mlb()` is the calibrated default."""

    # --- Pitching: pitch selection ---------------------------------------
    # Better offerings get thrown more often. Weight is grade minus an
    # offset, so a 20-grade pitch is nearly never chosen.
    pitch_selection_offset: float = 15.0
    pitch_selection_min_weight: float = 1.0

    # --- Pitching: control (do you attack the zone at all) ---------------
    zone_target_rate: float = 0.498
    control_grade_weight: float = 0.055
    zone_target_max: float = 0.90
    zone_target_x_halfwidth: float = 0.55
    zone_target_z_inset: float = 0.30
    chase_target_x_min: float = 0.85
    chase_target_x_max: float = 1.25
    chase_target_z_below: float = 0.55
    chase_target_z_above: float = 0.45

    # --- Pitching: command (how tightly it clusters on the target) -------
    command_sigma_base: float = 0.42
    command_grade_weight: float = 0.055
    command_sigma_min: float = 0.16

    # --- Pitching: stuff and fatigue -------------------------------------
    velocity_noise: float = 0.9
    spin_noise: float = 90.0
    extension_baseline: float = 6.4
    extension_velocity_weight: float = 2.6
    fatigue_control_penalty: float = 1.5
    fatigue_command_penalty: float = 1.5
    fatigue_velocity_penalty: float = 2.2
    # A gassed pitcher gets much worse but never becomes physically
    # incapable of throwing a strike, hence the cap.
    fatigue_cap: float = 2.0
    fatigue_pitches_scale: float = 40.0

    # --- Batting: swing decisions ----------------------------------------
    # Plate discipline shows up mostly as laying off balls, not as swinging
    # more at strikes, so eye weight is much larger on the chase side.
    zone_swing_rate: float = 0.67
    two_strike_zone_swing_rate: float = 0.88
    zone_swing_eye_weight: float = 0.015
    zone_swing_min: float = 0.15
    zone_swing_max: float = 0.97

    chase_rate_base: float = 0.475
    eye_grade_weight: float = 0.055
    chase_nearness_offset: float = 0.85
    chase_nearness_scale: float = 1.9
    chase_nearness_floor: float = 0.12
    two_strike_chase_bonus: float = 0.20
    chase_min: float = 0.02
    chase_max: float = 0.92

    # --- Batting: whiffs --------------------------------------------------
    whiff_base: float = 0.170
    whiff_hit_grade_weight: float = 0.035
    whiff_velocity_baseline: float = 92.0
    whiff_velocity_weight: float = 0.0055
    whiff_spin_baseline: float = 2250.0
    whiff_spin_weight: float = 0.000022
    whiff_location_offset: float = 0.75
    whiff_location_weight: float = 0.16
    whiff_swing_length_baseline: float = 7.3
    whiff_swing_length_weight: float = 0.022
    whiff_min: float = 0.03
    whiff_max: float = 0.85

    # --- Batting: fouls ---------------------------------------------------
    # Coupled to strikeout rate through count depth. Do not touch alone.
    foul_rate_base: float = 0.575
    foul_hit_grade_weight: float = 0.012
    foul_location_offset: float = 0.75
    foul_location_weight: float = 0.10
    foul_min: float = 0.15
    foul_max: float = 0.70

    # --- Batting: hit by pitch --------------------------------------------
    hbp_distance_threshold: float = 1.5
    hbp_rate: float = 0.011

    # --- Contact physics: the collision -----------------------------------
    # Exit velocity ceiling scales with bat speed plus a smaller share of
    # the incoming pitch speed.
    bat_speed_coefficient: float = 1.23
    pitch_speed_coefficient: float = 0.23
    # Squared-up rate is drawn as one minus a half-normal, which makes exit
    # velocity left-skewed: clustered near the physical maximum with a long
    # weak-contact tail. A symmetric draw gets average exit velocity,
    # hard-hit rate, and barrel rate all wrong at once.
    squared_up_spread: float = 0.194
    squared_up_hit_grade_weight: float = 0.010
    squared_up_location_offset: float = 0.6
    squared_up_location_weight: float = 0.055
    squared_up_spread_min: float = 0.09
    squared_up_min: float = 0.28
    exit_velocity_min: float = 28.0

    # --- Contact physics: launch and spray --------------------------------
    launch_height_baseline: float = 2.5
    launch_height_weight: float = 6.0
    launch_angle_offset: float = 3.8
    launch_angle_sigma: float = 22.0
    launch_angle_min: float = -70.0
    launch_angle_max: float = 85.0

    pull_weight: float = 18.0
    spray_inside_weight: float = 8.0
    spray_sigma: float = 15.0
    spray_max: float = 45.0

    # --- Contact physics: trajectory --------------------------------------
    ground_roll_factor: float = 0.55
    ground_angle_scale: float = 60.0
    ground_distance_min: float = 5.0
    # Drag must scale with launch angle. A flat factor had a 103 mph ball at
    # 38 degrees carrying 433 ft against a real ~380, which inflated home
    # runs badly.
    drag_factor: float = 0.63
    drag_angle_threshold: float = 25.0
    drag_angle_penalty: float = 0.0032
    drag_factor_min: float = 0.32
    air_distance_min: float = 3.0
    hang_time_factor: float = 1.12

    # --- Fielding: ground balls -------------------------------------------
    # Friction and the bounce bleed off a good chunk of exit velocity before
    # the ball reaches infield depth.
    ground_ball_speed_retention: float = 0.70
    ground_ball_speed_min: float = 20.0
    infield_reaction_time: float = 0.34
    infield_reaction_grade_weight: float = 0.035
    # Lateral movement on a grounder is slower than an open-field sprint.
    infield_reach_factor: float = 0.674
    ground_double_corner_rate: float = 0.16
    ground_double_base_rate: float = 0.04
    infield_hit_base: float = 0.055
    infield_hit_velocity_baseline: float = 80.0
    infield_hit_velocity_scale: float = 25.0
    infield_hit_velocity_weight: float = 0.02
    infield_hit_min: float = 0.01

    # --- Fielding: air balls ----------------------------------------------
    reaction_time_base: float = 0.55
    outfield_reaction_grade_weight: float = 0.06
    outfield_reach_factor: float = 0.874
    # Smooth catch probability rather than a hard cutoff, so close plays go
    # either way.
    catch_probability_slope: float = 9.0
    air_error_multiplier: float = 0.6

    # --- Fielding: how far a ball that drops goes -------------------------
    home_run_min_angle: float = 15.0
    home_run_max_angle: float = 50.0
    corner_spray_angle: float = 30.0
    corner_bonus: float = 0.18
    wall_margin: float = 25.0
    off_wall_triple_rate: float = 0.22
    deep_distance: float = 250.0
    deep_triple_rate: float = 0.07
    deep_triple_corner_weight: float = 0.3
    deep_double_rate: float = 0.84
    medium_distance: float = 170.0
    medium_double_rate: float = 0.38

    # --- Baserunning -------------------------------------------------------
    # Runners don't advance the same number of bases as the hit. Modeling
    # the extra base is worth roughly a run a game, so it isn't optional.
    baserunning_speed_baseline: float = 27.0
    speed_weight: float = 0.06
    score_from_second_on_single: float = 0.58
    first_to_third_on_single: float = 0.30
    score_from_first_on_double: float = 0.45
    extra_base_default: float = 0.20
    extra_base_max: float = 0.95
    score_from_third_on_ground_out: float = 0.55
    tag_from_third_rate: float = 0.50

    # --- Baserunning: steals -----------------------------------------------
    steal_catcher_arm_weight: float = 0.04

    # --- Bullpen warmth (v0.4) ----------------------------------------------
    # One slot, one continuous counter. States are derived from `warmth`
    # rather than stored, which handles the awkward cases for free: a
    # reliever pulled from the slot at 22 and returned three pitches later
    # resumes at 19, with no re-entry rule needed.
    bullpen_slots: int = 1
    pitches_to_warm: int = 30
    # Separate from pitches_to_warm on purpose. Cooling slower than warming
    # is more realistic and worth trying during calibration.
    pitches_to_cool: int = 30
    # Warm-up throws feed the existing fatigue model at a discount. This is
    # what makes repeat warm-ups costly without a second counter.
    warmup_fatigue_ratio: float = 0.5
    # Cold-entry penalties, scaled continuously by how unready he was.
    cold_entry_max_control_penalty: int = 8
    cold_entry_max_command_penalty: int = 8
    cold_entry_max_velocity_penalty: float = 1.5

    mound_visits_per_game: int = 5

    # --- Not yet implemented ------------------------------------------------
    # Double plays. The structure supports them (BaserunningEngine owns force
    # state) but the logic is unspecified, so this knob is currently unread.
    double_play_base_rate: float = 0.0

    @classmethod
    def mlb(cls) -> "SimulationConfig":
        """The calibrated defaults: 13 of 15 benchmarks in range."""
        return cls()


# The shared default. Threaded through as an explicit argument everywhere so
# a caller can swap it; module-level only so v0.1 call sites keep working.
DEFAULT_CONFIG = SimulationConfig.mlb()
DEFAULT_PARK = ParkConfig()
