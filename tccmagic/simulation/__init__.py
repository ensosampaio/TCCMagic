"""Módulo 3 — Simulação de partidas Bo3 (motores Forge e substituto)."""

from tccmagic.simulation.base import GameSpec, MatchEngine
from tccmagic.simulation.bo3 import Bo3Simulator, EvaluationReport, MatchupReport
from tccmagic.simulation.forge import ForgeConfig, ForgeEngine, ForgeError
from tccmagic.simulation.surrogate import SurrogateConfig, SurrogateEngine

__all__ = [
    "Bo3Simulator",
    "EvaluationReport",
    "ForgeConfig",
    "ForgeEngine",
    "ForgeError",
    "GameSpec",
    "MatchEngine",
    "MatchupReport",
    "SurrogateConfig",
    "SurrogateEngine",
]
