"""Pipeline completo: banco de dados → decodificador → simulador Bo3 → BRKGA."""

from __future__ import annotations

import math
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Sequence

import numpy as np

from tccmagic.analysis import OpponentSwapAnalysis, analyze_swaps
from tccmagic.archive import GameArchive, context_fingerprint
from tccmagic.attributes import N_ATTRIBUTES
from tccmagic.brkga import BRKGA_Optimizer, BRKGAConfig, GenerationStats
from tccmagic.cards import DATA_DIR, SIDEBOARD_SIZE, Card, Database, Opponent, load_database
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
from tccmagic.simulation.bo3 import SeriesWins

# Séries de validação por oponente, como múltiplo de ``matches_per_opponent``.
VALIDATION_FACTOR = 5

# Nome da linha de base (Games 2/3 com o maindeck) na comparação de sideboards.
NO_SIDEBOARD = "sem_sideboard"


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
    # Pasta do arquivo de jogos pós-side (None = não grava nem lê). Os jogos de
    # execuções anteriores do mesmo contexto somam-se à análise das trocas.
    games_dir: str | None = None
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
    validation: Validation | None  # None só no resultado parcial (busca concluída, validação pendente)
    swap_analysis: list[OpponentSwapAnalysis]  # vazio no plano por afinidade
    games_simulated: int
    games_reused: int
    resampled: bool
    stopped_early: bool
    elapsed_seconds: float
    games_archived: int = 0     # jogos de execuções anteriores somados à análise das trocas

    def config_dict(self) -> dict:
        return asdict(self.config)


@dataclass(frozen=True)
class Candidate:
    """Um sideboard avaliado na comparação (ou a linha de base sem sideboard)."""

    name: str
    cards: tuple[tuple[str, int], ...]  # lista compacta (carta, cópias); vazia na linha de base
    report: EvaluationReport
    series_wins: SeriesWins             # oponente -> [venceu a série m?]


@dataclass(frozen=True)
class Comparison:
    """Diferença de WinRate_Bo3 entre dois candidatos que jogaram sobre os mesmos Games 1."""

    candidate: str
    reference: str
    gain: float    # Bo3 do candidato − Bo3 da referência
    stderr: float  # pareado, por blocos de séries (ver ``paired_comparison``)

    def interval(self, z: float = 1.96) -> tuple[float, float]:
        return self.gain - z * self.stderr, self.gain + z * self.stderr

    @property
    def significant(self) -> bool:
        low, high = self.interval()
        return low > 0 or high < 0


@dataclass
class ComparisonResult:
    config: ExperimentConfig
    database: Database
    n_matches: int
    candidates: list[Candidate]      # na ordem pedida; a linha de base é a última
    comparisons: list[Comparison]
    swap_analysis: list[OpponentSwapAnalysis]  # vazio no plano por afinidade
    games_simulated: int
    games_reused: int
    games_archived: int
    elapsed_seconds: float

    def config_dict(self) -> dict:
        return asdict(self.config)


def paired_comparison(candidate: Candidate, reference: Candidate, block: int = 1) -> Comparison:
    """Compara dois candidatos série a série.

    A série ``m`` dos dois parte do mesmo Game 1 e, no plano aleatório, do
    mesmo sorteio de trocas; quando os decks pós-side coincidem, os jogos são
    os mesmos. O erro da diferença é por isso bem menor que o de duas amostras
    independentes, e é estimado a partir das diferenças por série.

    As séries de um mesmo bloco compartilham o plano de troca e não são
    independentes entre si: a variância é calculada entre **blocos** de
    ``block`` séries (erro padrão por conglomerados). Com menos de dois blocos
    o erro é ``NaN``.
    """
    matchups = candidate.report.matchups
    total = sum(m.meta_share for m in matchups)
    variance = 0.0
    for m in matchups:
        diff = (np.asarray(candidate.series_wins[m.opponent], dtype=float)
                - np.asarray(reference.series_wins[m.opponent], dtype=float))
        sums = np.add.reduceat(diff, np.arange(0, len(diff), block))
        if len(sums) < 2:
            variance = math.nan
            break
        spread = float(np.sum((sums - sums.mean()) ** 2)) * len(sums) / (len(sums) - 1)
        variance += (m.meta_share / total) ** 2 * spread / len(diff) ** 2
    gain = candidate.report.winrate_bo3 - reference.report.winrate_bo3
    return Comparison(candidate.name, reference.name, gain, math.sqrt(variance))


def sideboard_from_names(database: Database, names: Sequence[str]) -> tuple[Card, ...]:
    """Converte nomes (um por cópia) nas cartas do pool, conferindo se o sideboard é legal."""
    by_name = {card.name: card for card in database.candidates}
    unknown = sorted(set(names) - set(by_name))
    if unknown:
        raise ValueError(f"Cartas fora do pool de sideboard: {unknown}")
    if len(names) != SIDEBOARD_SIZE:
        raise ValueError(f"O sideboard tem {len(names)} cartas (esperado {SIDEBOARD_SIZE}).")
    allowed = Counter(slot.card.name for slot in database.sideboard_slots())
    excess = sorted(name for name, count in Counter(names).items() if count > allowed[name])
    if excess:
        raise ValueError(f"Cópias acima do permitido pelo pool: {excess}")
    return tuple(by_name[name] for name in names)


def random_sideboard(database: Database, rng: np.random.Generator) -> list[str]:
    """Sorteia 15 entradas do pool: um sideboard legal escolhido sem nenhum critério."""
    slots = database.sideboard_slots()
    return [slots[i].card.name for i in sorted(rng.choice(len(slots), SIDEBOARD_SIZE, replace=False))]


def _engine_label(config: ExperimentConfig) -> str:
    """Parte do contexto do arquivo de jogos que depende do motor."""
    if config.engine == "forge" and config.forge is not None:
        return f"forge:{Path(config.forge.jar_path).name}"
    return f"{config.engine}:{sorted(asdict(config.surrogate).items())}"


def open_archive(config: ExperimentConfig, database: Database,
                 notify: Callable[[str], None]) -> GameArchive | None:
    if config.games_dir is None:
        return None
    label = _engine_label(config)
    archive = GameArchive(config.games_dir, context_fingerprint(database, label), label)
    message = f"Arquivo de jogos: {len(archive.previous)} jogos pós-side de execuções anteriores"
    if archive.skipped_runs:
        message += f" ({archive.skipped_runs} execuções de outro motor/decks ficaram de fora)"
    notify(message + ".")
    return archive


def build_simulator(config: ExperimentConfig, database: Database, engine: MatchEngine) -> Bo3Simulator:
    return Bo3Simulator(
        database,
        engine,
        matches_per_opponent=config.matches_per_opponent,
        max_swaps=config.max_swaps,
        swap_margin=config.swap_margin,
        plan=config.plan,
        plan_block=config.plan_block,
        plan_seed=config.plan_seed,
    )


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
    on_search_done: Callable[[ExperimentResult], None] | None = None,
) -> ExperimentResult:
    """Busca (BRKGA) seguida da validação final.

    ``on_search_done`` recebe o resultado parcial (``validation=None``) assim que
    a busca termina, para que possa ser gravado antes da validação: se ela
    falhar, as horas de busca não se perdem.
    """
    start = time.perf_counter()
    notify = status or (lambda message: None)
    database = load_database(Path(config.data_dir), config.maindeck_file)
    decoder = SideboardDecoder(database, copy_penalty=config.copy_penalty)
    engine = build_engine(config, database)
    resample = (not engine.deterministic) if config.resample is None else config.resample
    simulator = build_simulator(config, database, engine)
    archive = open_archive(config, database, notify)

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

        def analysis() -> list[OpponentSwapAnalysis]:
            # Com trocas sorteadas, todos os jogos pós-side já jogados formam um
            # experimento aleatorizado sobre o efeito de cada carta que entra/sai.
            if config.plan != "aleatorio":
                return []
            games = archive.merged(simulator.games, engine.deterministic) if archive else simulator.games
            return analyze_swaps(games, database)

        def snapshot(validation: Validation | None) -> ExperimentResult:
            return ExperimentResult(
                config=config,
                database=database,
                history=history,
                best=best,
                best_keys=[float(k) for k in result.best_keys],
                validation=validation,
                swap_analysis=analysis(),
                games_simulated=simulator.games_played,
                games_reused=simulator.games_reused,
                resampled=resample,
                stopped_early=result.stopped_early,
                elapsed_seconds=time.perf_counter() - start,
                games_archived=len(archive.previous) if archive else 0,
            )

        if archive:
            archive.save(simulator.games)  # antes da validação: se ela falhar, os jogos da busca ficam
        if on_search_done:
            on_search_done(snapshot(None))

        n_validation = config.n_validation_matches
        notify(f"Validação final: {n_validation} séries novas por oponente, com e sem sideboard...")
        try:
            validated, baseline = evaluator.validate([best.decoded.cards, ()], n_validation)
        finally:
            if archive:
                archive.save(simulator.games)

    return snapshot(Validation(n_validation, validated, baseline))


def compare_sideboards(
    config: ExperimentConfig,
    sideboards: Mapping[str, Sequence[str]],
    status: Callable[[str], None] | None = None,
) -> ComparisonResult:
    """Valida vários sideboards (nome -> cartas, uma por cópia) sobre os mesmos Games 1, sem busca.

    Joga ``config.n_validation_matches`` séries novas por oponente para cada
    sideboard e para a linha de base sem sideboard. Compara cada sideboard com
    a linha de base e o primeiro sideboard com cada um dos outros.
    """
    start = time.perf_counter()
    notify = status or (lambda message: None)
    if not sideboards:
        raise ValueError("Informe ao menos um sideboard para comparar.")
    if NO_SIDEBOARD in sideboards:
        raise ValueError(f"'{NO_SIDEBOARD}' é o nome reservado da linha de base.")
    database = load_database(Path(config.data_dir), config.maindeck_file)
    cards = {name: sideboard_from_names(database, list(names)) for name, names in sideboards.items()}
    cards[NO_SIDEBOARD] = ()
    engine = build_engine(config, database)
    simulator = build_simulator(config, database, engine)
    simulator.game1 = {}  # não há busca: os Games 1 são só os da validação
    archive = open_archive(config, database, notify)
    n_matches = config.n_validation_matches

    notify(f"Comparação: {n_matches} séries novas por oponente para {len(sideboards)} sideboards "
           "e para a linha de base sem sideboard...")
    with FitnessEvaluator(SideboardDecoder(database), simulator, workers=config.workers) as evaluator:
        try:
            reports, wins = evaluator.validate_detailed(list(cards.values()), n_matches)
        finally:
            if archive:
                archive.save(simulator.games)

    candidates = [
        Candidate(name, tuple(Counter(c.name for c in side).items()), report, won)
        for (name, side), report, won in zip(cards.items(), reports, wins)
    ]
    *with_side, baseline = candidates
    block = config.plan_block if config.plan == "aleatorio" else 1
    comparisons = [paired_comparison(c, baseline, block) for c in with_side]
    comparisons += [paired_comparison(with_side[0], other, block) for other in with_side[1:]]

    swap_analysis: list[OpponentSwapAnalysis] = []
    if config.plan == "aleatorio":
        games = archive.merged(simulator.games, engine.deterministic) if archive else simulator.games
        swap_analysis = analyze_swaps(games, database)
    return ComparisonResult(
        config=config,
        database=database,
        n_matches=n_matches,
        candidates=candidates,
        comparisons=comparisons,
        swap_analysis=swap_analysis,
        games_simulated=simulator.games_played,
        games_reused=simulator.games_reused,
        games_archived=len(archive.previous) if archive else 0,
        elapsed_seconds=time.perf_counter() - start,
    )
