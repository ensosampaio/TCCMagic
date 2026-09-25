"""Função de fitness: cromossomo → sideboard → séries Bo3 → taxa de vitória.

fitness(x) = Σ_opp share(opp) · WinRate_Bo3(opp)

Como o Game 1 usa sempre o mesmo maindeck, WinRate_Md1 é constante entre
indivíduos; maximizar WinRate_Bo3 equivale, portanto, a maximizar
ΔWinRate = WinRate_Bo3 − WinRate_Md1. Ambos são registrados nos relatórios.

Otimizações:
* **Cache**: muitos vetores de pesos decodificam para o mesmo Top-15; cada
  sideboard distinto é simulado uma única vez.
* **Paralelismo**: sideboards ainda não avaliados são distribuídos entre
  processos com ``ProcessPoolExecutor``. O simulador é enviado a cada worker uma
  única vez (``initializer``), não a cada tarefa.
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from typing import Sequence

import numpy as np

from tccmagic.cards import Card
from tccmagic.decoder import DecodedSideboard, SideboardDecoder
from tccmagic.simulation.bo3 import Bo3Simulator, EvaluationReport

# Estado global de cada processo worker (preenchido pelo initializer).
_WORKER_SIMULATOR: Bo3Simulator | None = None


def _init_worker(simulator: Bo3Simulator) -> None:
    global _WORKER_SIMULATOR
    _WORKER_SIMULATOR = simulator


def _evaluate_in_worker(sideboard: tuple[Card, ...]) -> EvaluationReport:
    assert _WORKER_SIMULATOR is not None, "Worker não inicializado."
    return _WORKER_SIMULATOR.evaluate(sideboard)


@dataclass(frozen=True)
class Evaluation:
    decoded: DecodedSideboard
    report: EvaluationReport

    @property
    def fitness(self) -> float:
        return self.report.winrate_bo3


class FitnessEvaluator:
    """Avalia populações inteiras de cromossomos (com cache e paralelismo)."""

    def __init__(self, decoder: SideboardDecoder, simulator: Bo3Simulator, workers: int = 1):
        self.decoder = decoder
        self.simulator = simulator
        self.workers = max(1, workers)
        self.cache: dict[tuple[str, ...], EvaluationReport] = {}
        self.simulations = 0  # nº de sideboards efetivamente simulados
        self.simulator.prepare()  # Game 1 calculado antes de copiar o simulador para os workers
        self._pool: ProcessPoolExecutor | None = None
        if self.workers > 1:
            self._pool = ProcessPoolExecutor(
                max_workers=self.workers, initializer=_init_worker, initargs=(simulator,)
            )

    def evaluate_population(self, population: np.ndarray) -> list[Evaluation]:
        decoded = [self.decoder.decode(keys) for keys in population]

        pending: dict[tuple[str, ...], tuple[Card, ...]] = {}
        for d in decoded:
            if d.key not in self.cache:
                pending.setdefault(d.key, tuple(d.cards))

        if pending:
            keys, sideboards = list(pending), list(pending.values())
            if self._pool is not None:
                chunksize = max(1, len(sideboards) // (4 * self.workers))
                reports = list(self._pool.map(_evaluate_in_worker, sideboards, chunksize=chunksize))
            else:
                reports = [self.simulator.evaluate(sb) for sb in sideboards]
            self.cache.update(zip(keys, reports))
            self.simulations += len(reports)

        return [Evaluation(d, self.cache[d.key]) for d in decoded]

    def __call__(self, population: np.ndarray) -> np.ndarray:
        """Interface genérica usada pelo BRKGA: população → vetor de fitness."""
        return np.array([e.fitness for e in self.evaluate_population(population)])

    def evaluate_one(self, keys: Sequence[float]) -> Evaluation:
        return self.evaluate_population(np.atleast_2d(np.asarray(keys, dtype=float)))[0]

    def baseline_without_sideboard(self) -> EvaluationReport:
        """Bo3 sem nenhuma troca (Games 2/3 com o maindeck): linha de base honesta.

        Útil porque ΔWinRate = Bo3 − Md1 também captura o efeito puramente
        estatístico do formato melhor-de-3 (que amplifica taxas ≠ 50%), e não
        apenas o ganho do sideboard.
        """
        return self.simulator.evaluate(())

    def close(self) -> None:
        if self._pool is not None:
            self._pool.shutdown()
            self._pool = None

    def __enter__(self) -> "FitnessEvaluator":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
