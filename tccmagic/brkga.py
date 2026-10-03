"""Módulo 2 — BRKGA (Biased Random-Key Genetic Algorithm).

Implementação genérica e independente do problema: o otimizador só conhece
vetores de chaves em [0, 1)^n e uma função que devolve o fitness (a maximizar)
de uma população inteira. Toda a semântica de Magic fica no decodificador.

Ciclo de uma geração (Gonçalves & Resende, 2011):

    população ordenada por fitness
    ├── Elite     (20%) → copiada sem alteração para a próxima geração
    ├── Mutantes  (15%) → indivíduos novos, chaves ~ U[0,1)
    └── Cruzamento(65%) → filho de 1 pai elite × 1 pai não-elite;
                          cada gene vem do pai elite com prob. ρ = 0,70

Por padrão os elites mantêm o fitness já calculado (não são reavaliados), o que
é correto para um fitness determinístico. Com um fitness ruidoso (partidas
simuladas), use ``reevaluate_elites=True``: a população inteira é reavaliada a
cada geração, para que um indivíduo que teve sorte uma vez não fique na elite
para sempre.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

FitnessFunction = Callable[[np.ndarray], np.ndarray]


@dataclass
class BRKGAConfig:
    population_size: int = 50
    elite_fraction: float = 0.20
    mutant_fraction: float = 0.15
    elite_bias: float = 0.70           # ρ: prob. de herdar o gene do pai elite
    generations: int = 50
    # Para antes se o melhor fitness não melhorar por N gerações (None = nunca).
    max_stall_generations: int | None = None
    seed: int | None = 42

    def __post_init__(self) -> None:
        if self.population_size < 3:
            raise ValueError("population_size deve ser >= 3.")
        if not 0 < self.elite_fraction < 1 or not 0 <= self.mutant_fraction < 1:
            raise ValueError("Frações de elite/mutantes inválidas.")
        if self.n_elite + self.n_mutants >= self.population_size:
            raise ValueError("Elite + mutantes deve deixar espaço para o cruzamento.")
        if not 0.5 <= self.elite_bias <= 1.0:
            raise ValueError("elite_bias (ρ) deve estar em [0,5; 1,0].")

    @property
    def n_elite(self) -> int:
        return max(1, int(round(self.elite_fraction * self.population_size)))

    @property
    def n_mutants(self) -> int:
        return int(round(self.mutant_fraction * self.population_size))

    @property
    def n_offspring(self) -> int:
        return self.population_size - self.n_elite - self.n_mutants


@dataclass(frozen=True)
class GenerationStats:
    generation: int
    best_fitness: float
    mean_fitness: float
    std_fitness: float
    best_keys: np.ndarray
    elapsed_seconds: float


@dataclass
class BRKGAResult:
    best_keys: np.ndarray
    best_fitness: float
    history: list[GenerationStats] = field(default_factory=list)
    stopped_early: bool = False


class BRKGA_Optimizer:  # noqa: N801 — nome definido na especificação do TCC
    """Otimizador BRKGA genérico (maximização)."""

    def __init__(
        self,
        chromosome_length: int,
        fitness_function: FitnessFunction,
        config: BRKGAConfig | None = None,
        on_generation: Callable[[GenerationStats], None] | None = None,
        reevaluate_elites: bool = False,
    ):
        self.n = chromosome_length
        self.fitness_function = fitness_function
        self.config = config or BRKGAConfig()
        self.on_generation = on_generation
        self.reevaluate_elites = reevaluate_elites
        self.rng = np.random.default_rng(self.config.seed)
        self.population: np.ndarray = np.empty((0, self.n))
        self.fitness: np.ndarray = np.empty(0)

    # ------------------------------------------------------------------ #
    # Operadores
    # ------------------------------------------------------------------ #
    def random_individuals(self, count: int) -> np.ndarray:
        return self.rng.random((count, self.n))

    def crossover(self, elites: np.ndarray, non_elites: np.ndarray, count: int) -> np.ndarray:
        """Cruzamento uniforme parametrizado (viesado para o pai elite)."""
        elite_parents = elites[self.rng.integers(len(elites), size=count)]
        other_parents = non_elites[self.rng.integers(len(non_elites), size=count)]
        inherit_elite = self.rng.random((count, self.n)) < self.config.elite_bias
        return np.where(inherit_elite, elite_parents, other_parents)

    def _sort(self) -> None:
        order = np.argsort(-self.fitness, kind="stable")
        self.population = self.population[order]
        self.fitness = self.fitness[order]

    def _evaluate(self, individuals: np.ndarray) -> np.ndarray:
        fitness = np.asarray(self.fitness_function(individuals), dtype=float)
        if fitness.shape != (len(individuals),):
            raise ValueError("A função de fitness deve retornar um valor por indivíduo.")
        return fitness

    # ------------------------------------------------------------------ #
    # Ciclo evolutivo
    # ------------------------------------------------------------------ #
    def initialize(self) -> None:
        self.population = self.random_individuals(self.config.population_size)
        self.fitness = self._evaluate(self.population)
        self._sort()

    def step(self) -> None:
        """Produz a próxima geração a partir da população atual (já ordenada)."""
        cfg = self.config
        elites = self.population[: cfg.n_elite]
        non_elites = self.population[cfg.n_elite:]

        offspring = self.crossover(elites, non_elites, cfg.n_offspring)
        mutants = self.random_individuals(cfg.n_mutants)
        newcomers = np.vstack([offspring, mutants])

        self.population = np.vstack([elites, newcomers])
        if self.reevaluate_elites:
            self.fitness = self._evaluate(self.population)
        else:
            self.fitness = np.concatenate([self.fitness[: cfg.n_elite], self._evaluate(newcomers)])
        self._sort()

    def refresh_elites(self) -> None:
        """Reavalia só a elite e a reordena (desempate final sob fitness ruidoso).

        Logo após ``step`` o líder pode ser um recém-chegado avaliado uma única
        vez; esta rodada extra faz o melhor final ter sido confirmado ao menos
        uma vez.
        """
        n = self.config.n_elite
        fitness = self._evaluate(self.population[:n])
        order = np.argsort(-fitness, kind="stable")
        self.population[:n] = self.population[:n][order]
        self.fitness[:n] = fitness[order]

    def _stats(self, generation: int, start: float) -> GenerationStats:
        return GenerationStats(
            generation=generation,
            best_fitness=float(self.fitness[0]),
            mean_fitness=float(self.fitness.mean()),
            std_fitness=float(self.fitness.std()),
            best_keys=self.population[0].copy(),
            elapsed_seconds=time.perf_counter() - start,
        )

    def run(self) -> BRKGAResult:
        start = time.perf_counter()
        self.initialize()
        result = BRKGAResult(best_keys=self.population[0].copy(), best_fitness=float(self.fitness[0]))

        stall = 0
        for generation in range(self.config.generations + 1):
            if generation > 0:
                self.step()
            stats = self._stats(generation, start)
            result.history.append(stats)
            if self.on_generation:
                self.on_generation(stats)

            if self.reevaluate_elites:
                # Fitness ruidoso: vale a estimativa atual do líder (que pode cair
                # ao ser reavaliada); "melhora" significa troca de líder.
                improved = not np.array_equal(stats.best_keys, result.best_keys)
                result.best_fitness, result.best_keys = stats.best_fitness, stats.best_keys
            else:
                # O elitismo garante que o melhor nunca piora; ">" detecta melhora estrita.
                improved = stats.best_fitness > result.best_fitness
                if improved:
                    result.best_fitness, result.best_keys = stats.best_fitness, stats.best_keys
            if improved:
                stall = 0
            elif generation > 0:
                stall += 1
            limit = self.config.max_stall_generations
            if limit is not None and stall >= limit:
                result.stopped_early = True
                break

        if self.reevaluate_elites:
            self.refresh_elites()
            result.best_fitness, result.best_keys = float(self.fitness[0]), self.population[0].copy()
        return result
