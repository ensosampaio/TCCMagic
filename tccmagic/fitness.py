"""Função de fitness: cromossomo → sideboard → séries Bo3 → taxa de vitória.

fitness(x) = Σ_opp share(opp) · WinRate_Bo3(opp)

Como o Game 1 usa sempre o mesmo maindeck, WinRate_Md1 é constante entre
indivíduos; maximizar WinRate_Bo3 equivale, portanto, a maximizar
ΔWinRate = WinRate_Bo3 − WinRate_Md1. Ambos são registrados nos relatórios.

Otimizações:
* **Cache de sideboards**: muitos vetores de pesos decodificam para o mesmo
  Top-15; os resultados de cada sideboard distinto são guardados e reaproveitados.
* **Cache de jogos** (em ``Bo3Simulator.games``): o resultado de um jogo
  depende só do deck pós-side, não do sideboard de origem; sideboards diferentes
  que levam ao mesmo deck contra um oponente compartilham os jogos simulados.
* **Reamostragem** (``resample=True``, para motores estocásticos como o Forge):
  cada vez que um sideboard é avaliado de novo ele joga mais uma rodada de
  séries, somada às anteriores. O fitness é a taxa acumulada, de modo que um
  sideboard que teve sorte em poucas séries regride à sua taxa real em vez de
  ficar no topo para sempre.
* **Paralelismo**: os lotes de jogos (um por oponente × deck pós-side
  distinto) são distribuídos entre processos com ``ProcessPoolExecutor``. O simulador é enviado a cada worker uma
  única vez (``initializer``), não a cada tarefa.
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from typing import Sequence

import numpy as np

from tccmagic.cards import Card
from tccmagic.decoder import DecodedSideboard, SideboardDecoder
from tccmagic.simulation.bo3 import Batch, Bo3Simulator, EvaluationReport, SeriesWins

# Índice inicial das séries de validação: longe das séries usadas na busca, para
# que motores com sorteios fixados por índice (substituto) gerem jogos novos.
VALIDATION_MATCH_OFFSET = 1_000_000_000

# Estado global de cada processo worker (preenchido pelo initializer).
_WORKER_SIMULATOR: Bo3Simulator | None = None


def _init_worker(simulator: Bo3Simulator) -> None:
    global _WORKER_SIMULATOR
    _WORKER_SIMULATOR = simulator


def _run_task(simulator: Bo3Simulator, task: tuple) -> list[bool]:
    """Executa uma tarefa: Games 1 com o maindeck ou um lote de jogos com um deck pós-side."""
    kind, opp_index, *args = task
    opp = simulator.db.opponents[opp_index]
    if kind == "game1":
        return simulator.play_game1(opp, *args)
    deck, specs = args
    return simulator.engine.play_games(deck, opp, specs)


def _run_task_in_worker(task: tuple) -> list[bool]:
    assert _WORKER_SIMULATOR is not None, "Worker não inicializado."
    return _run_task(_WORKER_SIMULATOR, task)


@dataclass(frozen=True)
class Evaluation:
    decoded: DecodedSideboard
    report: EvaluationReport

    @property
    def fitness(self) -> float:
        return self.report.winrate_bo3


class FitnessEvaluator:
    """Avalia populações inteiras de cromossomos (com cache e paralelismo)."""

    def __init__(self, decoder: SideboardDecoder, simulator: Bo3Simulator, workers: int = 1,
                 resample: bool = False):
        self.decoder = decoder
        self.simulator = simulator
        self.workers = max(1, workers)
        self.resample = resample
        self.cache: dict[tuple[str, ...], EvaluationReport] = {}
        self.rounds: dict[tuple[str, ...], int] = {}  # rodadas já jogadas por sideboard
        self.simulations = 0  # nº de avaliações (sideboard × rodada) efetivamente simuladas
        self._pool: ProcessPoolExecutor | None = None
        if self.workers > 1:
            self._pool = ProcessPoolExecutor(
                max_workers=self.workers, initializer=_init_worker, initargs=(simulator,)
            )
        if simulator.game1 is None:
            try:
                simulator.game1 = self.play_game1(simulator.matches_per_opponent)
            except BaseException:
                self.close()
                raise

    # ------------------------------------------------------------------ #
    def _map(self, tasks: list[tuple]) -> list:
        if self._pool is None:
            return [_run_task(self.simulator, task) for task in tasks]
        chunksize = max(1, len(tasks) // (4 * self.workers))
        return list(self._pool.map(_run_task_in_worker, tasks, chunksize=chunksize))

    def play_game1(self, n_matches: int, match_offset: int = 0) -> dict[str, list[bool]]:
        """Game 1 de ``n_matches`` séries contra cada oponente."""
        opponents = self.simulator.db.opponents
        results = self._map([("game1", i, n_matches, match_offset) for i in range(len(opponents))])
        return {opp.name: g1 for opp, g1 in zip(opponents, results)}

    def _run_batches(self, batches: list[Batch]) -> list[list[bool]]:
        return self._map([("games", i, deck, specs) for i, deck, specs in batches])

    def _play(self, jobs: Sequence[tuple[tuple[Card, ...], int]],
              game1: dict[str, list[bool]]) -> list[EvaluationReport]:
        """Joga os Games 2/3 de cada (sideboard, índice inicial das séries)."""
        return self.simulator.play_postboard(jobs, game1, self._run_batches)

    # ------------------------------------------------------------------ #
    def evaluate_population(self, population: np.ndarray, sample: bool = True) -> list[Evaluation]:
        """Avalia a população; com ``sample=False`` só simula sideboards inéditos."""
        decoded = [self.decoder.decode(keys) for keys in population]

        pending: dict[tuple[str, ...], tuple[Card, ...]] = {}
        for d in decoded:
            if d.key not in self.cache or (sample and self.resample):
                pending.setdefault(d.key, tuple(d.cards))

        if pending:
            assert self.simulator.game1 is not None
            n = self.simulator.matches_per_opponent
            jobs = [(cards, self.rounds.get(key, 0) * n) for key, cards in pending.items()]
            for key, report in zip(pending, self._play(jobs, self.simulator.game1)):
                previous = self.cache.get(key)
                self.cache[key] = report if previous is None else previous.merge(report)
                self.rounds[key] = self.rounds.get(key, 0) + 1
            self.simulations += len(pending)

        return [Evaluation(d, self.cache[d.key]) for d in decoded]

    def __call__(self, population: np.ndarray) -> np.ndarray:
        """Interface genérica usada pelo BRKGA: população → vetor de fitness."""
        return np.array([e.fitness for e in self.evaluate_population(population)])

    def evaluate_one(self, keys: Sequence[float]) -> Evaluation:
        """Avaliação acumulada de um cromossomo, sem jogar rodadas extras."""
        return self.evaluate_population(np.atleast_2d(np.asarray(keys, dtype=float)), sample=False)[0]

    def validate(self, sideboards: Sequence[Sequence[Card]], n_matches: int) -> list[EvaluationReport]:
        """Reavalia sideboards com séries novas (Game 1 incluído), fora do cache.

        Todos os sideboards enfrentam os mesmos Games 1. Passar ``()`` avalia o
        Bo3 sem nenhuma troca (Games 2/3 com o maindeck): a linha de base que
        separa o ganho do sideboard do efeito puramente estatístico do formato
        melhor-de-3 (que amplifica taxas ≠ 50%).
        """
        return self.validate_detailed(sideboards, n_matches)[0]

    def validate_detailed(self, sideboards: Sequence[Sequence[Card]],
                          n_matches: int) -> tuple[list[EvaluationReport], list[SeriesWins]]:
        """Como ``validate``, mais o resultado de cada série, para comparações pareadas."""
        game1 = self.play_game1(n_matches, VALIDATION_MATCH_OFFSET)
        jobs = [(tuple(sb), VALIDATION_MATCH_OFFSET) for sb in sideboards]
        return self.simulator.play_postboard_detailed(jobs, game1, self._run_batches)

    def close(self) -> None:
        if self._pool is not None:
            self._pool.shutdown()
            self._pool = None

    def __enter__(self) -> "FitnessEvaluator":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
