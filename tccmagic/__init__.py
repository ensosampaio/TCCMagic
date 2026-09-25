"""Otimização de sideboard em Magic: The Gathering (Modern) via BRKGA-A.

Módulos:
    attributes   – os 9 atributos que vetorizam cada carta
    cards        – banco de dados: cartas, maindeck, pool, oponentes (Módulo 1)
    decoder      – chaves → pesos → Score → Top-15 (Módulo 1/2)
    brkga        – BRKGA_Optimizer genérico (Módulo 2)
    sideboarding – plano de troca por afinidade para os Games 2/3
    simulation   – motores (Forge / substituto) e orquestração Bo3 (Módulo 3)
    fitness      – função de fitness com cache e paralelismo (Módulo 3)
    pipeline     – experimento completo
    export       – exportação JSON / XLSX
"""

from tccmagic.attributes import ATTRIBUTES, N_ATTRIBUTES
from tccmagic.brkga import BRKGA_Optimizer, BRKGAConfig, BRKGAResult
from tccmagic.cards import Card, Database, Deck, Opponent, load_database
from tccmagic.decoder import DecodedSideboard, SideboardDecoder, keys_to_weights
from tccmagic.fitness import FitnessEvaluator
from tccmagic.pipeline import ExperimentConfig, ExperimentResult, run_experiment

__all__ = [
    "ATTRIBUTES",
    "BRKGAConfig",
    "BRKGAResult",
    "BRKGA_Optimizer",
    "Card",
    "Database",
    "DecodedSideboard",
    "Deck",
    "ExperimentConfig",
    "ExperimentResult",
    "FitnessEvaluator",
    "N_ATTRIBUTES",
    "Opponent",
    "SideboardDecoder",
    "keys_to_weights",
    "load_database",
    "run_experiment",
]
