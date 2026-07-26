"""A pitch-by-pitch baseball simulation engine."""

from .config import DEFAULT_CONFIG, DEFAULT_PARK, ParkConfig, SimulationConfig
from .enums import (
    AtBatResult,
    FieldingOutcome,
    PitchCall,
    PitchType,
    Position,
    SwingOutcome,
)
from .player import (
    FieldingProfile,
    HittingProfile,
    PitchArsenalEntry,
    PitchingProfile,
    Player,
    PlayerStats,
    RunningProfile,
)
from .state import BaseRunners, ForceState, Lineup, PlayerGameState, Situation
from .pitch import Pitch
from .batted_ball import BattedBall
from .events import (
    Advancement,
    BaserunningResult,
    FieldingResult,
    Play,
    PlateAppearanceOutcome,
    ScoringDecision,
)
from .engines import (
    BaserunningEngine,
    BattingEngine,
    FieldingEngine,
    OfficialScorer,
    PitchingEngine,
)
from .at_bat import AtBat
from .team import Team
from .game import Engines, Game, GameResult, HalfInning

__all__ = [
    # Layer 0 - configuration
    "SimulationConfig", "ParkConfig", "DEFAULT_CONFIG", "DEFAULT_PARK",
    # Enums
    "AtBatResult", "FieldingOutcome", "PitchCall", "PitchType", "Position",
    "SwingOutcome",
    # Layer 1 - persistent domain objects
    "Player", "PlayerStats", "HittingProfile", "PitchingProfile",
    "FieldingProfile", "RunningProfile", "PitchArsenalEntry",
    # Layer 2 - per-game state
    "PlayerGameState", "Lineup", "BaseRunners", "ForceState", "Situation",
    "Team",
    # Layer 3 - value objects
    "Pitch", "BattedBall", "FieldingResult", "Advancement", "Play",
    "PlateAppearanceOutcome", "BaserunningResult", "ScoringDecision",
    # Layer 4 - engines
    "PitchingEngine", "BattingEngine", "FieldingEngine", "BaserunningEngine",
    "OfficialScorer", "Engines",
    # Layer 5 - orchestration
    "AtBat", "HalfInning", "Game", "GameResult",
]
