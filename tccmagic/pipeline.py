"""Pipeline completo: banco de dados → decodificador → simulador Bo3 → BRKGA."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from tccmagic.attributes import N_ATTRIBUTES
from tccmagic.brkga import BRKGA_Optimizer, BRKGAConfig, GenerationStats
from tccmagic.cards import DATA_DIR, Database, load_database
from tccmagic.decoder import SideboardDecoder
from tccmagic.fitness import Evaluation, FitnessEvaluator
from tccmagic.simulation import (
    Bo3Simulator,
    EvaluationReport,
    ForgeConfig,
    ForgeEngine,
    MatchEngine,
    SurrogateConfig,
    SurrogateEngine,
)


@dataclass
class ExperimentConfig:
    engine: str = "surrogate"            # "surrogate" ou "forge"
    matches_per_opponent: int = 50       # séries Bo3 por oponente, por avaliação
    max_swaps: int = 5                   # máx. de cartas trocadas no sideboarding
    swap_margin: float = 0.0
    copy_penalty: float = 1.0            # δ do decodificador (retornos decrescentes por cópia)
    workers: int = 1                     # processos para avaliar indivíduos em paralelo
    data_dir: str = str(DATA_DIR)
    maindeck_file: str = "maindeck_boros_energy.json"
    brkga: BRKGAConfig = field(default_factory=BRKGAConfig)
    surrogate: SurrogateConfig = field(default_factory=SurrogateConfig)
    forge: ForgeConfig | None = None


@dataclass(frozen=True)
class GenerationRecord:
    """Linha do histórico evolutivo (uma por geração)."""

    generation: int
    best_fitness: float
    mean_fitness: float
    std_fitness: float
    winrate_md1: float
    winrate_bo3: float
    winrate_postboard: float
    delta_winrate: float
    weights: dict[str, float]
    sideboard: list[tuple[str, int]]
    simulated_sideboards: int
    elapsed_seconds: float


@dataclass
class ExperimentResult:
    config: ExperimentConfig
    database: Database
    history: list[GenerationRecord]
    best: Evaluation
    best_keys: list[float]
    baseline_no_sideboard: EvaluationReport
    stopped_early: bool
    elapsed_seconds: float

    def config_dict(self) -> dict:
        return asdict(self.config)


def build_engine(config: ExperimentConfig, database: Database) -> MatchEngine:
    if config.engine == "surrogate":
        return SurrogateEngine(database.maindeck, config.surrogate)
    if config.engine == "forge":
        if config.forge is None:
            raise ValueError("engine='forge' requer ExperimentConfig.forge (caminho do JAR etc.).")
        return ForgeEngine(config.forge)
    raise ValueError(f"Motor desconhecido: {config.engine!r}")


def run_experiment(
    config: ExperimentConfig,
    progress: Callable[[GenerationRecord], None] | None = None,
) -> ExperimentResult:
    start = time.perf_counter()
    database = load_database(Path(config.data_dir), config.maindeck_file)
    decoder = SideboardDecoder(database, copy_penalty=config.copy_penalty)
    simulator = Bo3Simulator(
        database,
        build_engine(config, database),
        matches_per_opponent=config.matches_per_opponent,
        max_swaps=config.max_swaps,
        swap_margin=config.swap_margin,
    )

    with FitnessEvaluator(decoder, simulator, workers=config.workers) as evaluator:
        history: list[GenerationRecord] = []

        def record(stats: GenerationStats) -> None:
            best = evaluator.evaluate_one(stats.best_keys)  # vem do cache
            rec = GenerationRecord(
                generation=stats.generation,
                best_fitness=stats.best_fitness,
                mean_fitness=stats.mean_fitness,
                std_fitness=stats.std_fitness,
                winrate_md1=best.report.winrate_md1,
                winrate_bo3=best.report.winrate_bo3,
                winrate_postboard=best.report.winrate_postboard,
                delta_winrate=best.report.delta_winrate,
                weights=best.decoded.weights_by_attribute(),
                sideboard=best.decoded.card_counts(),
                simulated_sideboards=evaluator.simulations,
                elapsed_seconds=stats.elapsed_seconds,
            )
            history.append(rec)
            if progress:
                progress(rec)

        optimizer = BRKGA_Optimizer(N_ATTRIBUTES, evaluator, config.brkga, on_generation=record)
        result = optimizer.run()
        best = evaluator.evaluate_one(result.best_keys)
        baseline = evaluator.baseline_without_sideboard()

    return ExperimentResult(
        config=config,
        database=database,
        history=history,
        best=best,
        best_keys=[float(k) for k in result.best_keys],
        baseline_no_sideboard=baseline,
        stopped_early=result.stopped_early,
        elapsed_seconds=time.perf_counter() - start,
    )
