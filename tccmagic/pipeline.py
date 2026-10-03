"""Pipeline completo: banco de dados → decodificador → simulador Bo3 → BRKGA."""

from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from tccmagic.analysis import OpponentSwapAnalysis, analyze_swaps
from tccmagic.attributes import N_ATTRIBUTES
from tccmagic.brkga import BRKGA_Optimizer, BRKGAConfig, GenerationStats
from tccmagic.cards import DATA_DIR, Database, Opponent, load_database
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

# Séries de validação por oponente, como múltiplo de ``matches_per_opponent``.
VALIDATION_FACTOR = 5


@dataclass
class ExperimentConfig:
    engine: str = "surrogate"            # "surrogate" ou "forge"
    matches_per_opponent: int = 50       # séries Bo3 por oponente, por avaliação
    # Séries por oponente na validação final (None = 5 × matches_per_opponent).
    validation_matches: int | None = None
    # Reavaliar a população a cada geração, acumulando as séries de cada
    # sideboard (None = automático: ligado para motores estocásticos, como o Forge).
    resample: bool | None = None
    max_swaps: int = 5                   # máx. de cartas trocadas no sideboarding
    swap_margin: float = 0.0             # só no plano por afinidade
    # Plano de troca nos Games 2/3: "aleatorio" (sorteia o que entra e o que sai)
    # ou "afinidade" (tabela arquétipo × atributo).
    plan: str = "aleatorio"
    plan_block: int = 10                 # séries consecutivas que compartilham o mesmo sorteio
    plan_seed: int = 2024                # semente dos sorteios de troca
    copy_penalty: float = 1.0            # δ do decodificador (retornos decrescentes por cópia)
    workers: int = 1                     # processos para simular confrontos em paralelo
    data_dir: str = str(DATA_DIR)
    maindeck_file: str = "maindeck_boros_energy.json"
    brkga: BRKGAConfig = field(default_factory=BRKGAConfig)
    surrogate: SurrogateConfig = field(default_factory=SurrogateConfig)
    forge: ForgeConfig | None = None

    @property
    def n_validation_matches(self) -> int:
        if self.validation_matches is not None:
            return self.validation_matches
        return VALIDATION_FACTOR * self.matches_per_opponent


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
    best_n_matches: int  # séries por oponente acumuladas pelo melhor indivíduo
    weights: dict[str, float]
    sideboard: list[tuple[str, int]]
    simulated_sideboards: int
    games_simulated: int  # jogos pós-side jogados pelo motor (acumulado)
    games_reused: int     # jogos pós-side reaproveitados do cache (acumulado)
    elapsed_seconds: float


@dataclass(frozen=True)
class Validation:
    """Reavaliação final com séries novas, independentes das usadas na busca.

    O fitness do melhor indivíduo da busca é otimista por construção (é o
    máximo de muitas estimativas ruidosas). Aqui o sideboard escolhido e a
    linha de base sem sideboard jogam séries novas, sobre os mesmos Games 1.
    """

    n_matches: int
    sideboard: EvaluationReport
    baseline: EvaluationReport

    @property
    def gain(self) -> float:
        """Ganho atribuível ao sideboard: Bo3 com side − Bo3 sem side."""
        return self.sideboard.winrate_bo3 - self.baseline.winrate_bo3

    @property
    def gain_stderr(self) -> float:
        """Erro padrão do ganho (conservador: ignora que os Games 1 são compartilhados)."""
        return math.hypot(self.sideboard.stderr_bo3, self.baseline.stderr_bo3)

    def gain_interval(self, z: float = 1.96) -> tuple[float, float]:
        return self.gain - z * self.gain_stderr, self.gain + z * self.gain_stderr

    @property
    def significant(self) -> bool:
        """O intervalo de 95% do ganho exclui zero?"""
        low, high = self.gain_interval()
        return low > 0 or high < 0


@dataclass
class ExperimentResult:
    config: ExperimentConfig
    database: Database
    history: list[GenerationRecord]
    best: Evaluation            # estimativa acumulada durante a busca (otimista)
    best_keys: list[float]
    validation: Validation
    swap_analysis: list[OpponentSwapAnalysis]  # vazio no plano por afinidade
    games_simulated: int
    games_reused: int
    resampled: bool
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


def measure_game1(config: ExperimentConfig, n_games: int) -> list[tuple[Opponent, int]]:
    """Joga ``n_games`` Games 1 (maindeck) contra cada oponente; retorna as vitórias.

    Diagnóstico para rodar antes de otimizar: mostra se o motor produz taxas de
    vitória plausíveis em cada confronto.
    """
    database = load_database(Path(config.data_dir), config.maindeck_file)
    simulator = Bo3Simulator(database, build_engine(config, database), matches_per_opponent=n_games)
    with FitnessEvaluator(SideboardDecoder(database), simulator, workers=config.workers):
        assert simulator.game1 is not None
        return [(opp, sum(simulator.game1[opp.name])) for opp in database.opponents]


def run_experiment(
    config: ExperimentConfig,
    progress: Callable[[GenerationRecord], None] | None = None,
    status: Callable[[str], None] | None = None,
) -> ExperimentResult:
    start = time.perf_counter()
    notify = status or (lambda message: None)
    database = load_database(Path(config.data_dir), config.maindeck_file)
    decoder = SideboardDecoder(database, copy_penalty=config.copy_penalty)
    engine = build_engine(config, database)
    resample = (not engine.deterministic) if config.resample is None else config.resample
    simulator = Bo3Simulator(
        database,
        engine,
        matches_per_opponent=config.matches_per_opponent,
        max_swaps=config.max_swaps,
        swap_margin=config.swap_margin,
        plan=config.plan,
        plan_block=config.plan_block,
        plan_seed=config.plan_seed,
    )

    notify(f"Jogando o Game 1 ({config.matches_per_opponent} séries por oponente)...")
    with FitnessEvaluator(decoder, simulator, workers=config.workers, resample=resample) as evaluator:
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
                best_n_matches=best.report.n_matches,
                weights=best.decoded.weights_by_attribute(),
                sideboard=best.decoded.card_counts(),
                simulated_sideboards=evaluator.simulations,
                games_simulated=simulator.games_played,
                games_reused=simulator.games_reused,
                elapsed_seconds=stats.elapsed_seconds,
            )
            history.append(rec)
            if progress:
                progress(rec)

        optimizer = BRKGA_Optimizer(
            N_ATTRIBUTES, evaluator, config.brkga, on_generation=record, reevaluate_elites=resample
        )
        result = optimizer.run()
        best = evaluator.evaluate_one(result.best_keys)

        n_validation = config.n_validation_matches
        notify(f"Validação final: {n_validation} séries novas por oponente, com e sem sideboard...")
        validated, baseline = evaluator.validate([best.decoded.cards, ()], n_validation)

    # Com trocas sorteadas, todos os jogos pós-side (busca + validação) formam um
    # experimento aleatorizado sobre o efeito de cada carta que entra/sai.
    swap_analysis = analyze_swaps(simulator.games, database) if config.plan == "aleatorio" else []

    return ExperimentResult(
        config=config,
        database=database,
        history=history,
        best=best,
        best_keys=[float(k) for k in result.best_keys],
        validation=Validation(n_validation, validated, baseline),
        swap_analysis=swap_analysis,
        games_simulated=simulator.games_played,
        games_reused=simulator.games_reused,
        resampled=resample,
        stopped_early=result.stopped_early,
        elapsed_seconds=time.perf_counter() - start,
    )
