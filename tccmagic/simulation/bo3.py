"""Orquestração de séries Melhor-de-3 (Bo3) contra a suíte de oponentes.

Estrutura de cada série:

* **Game 1 (Md1)**: maindeck fixo vs. oponente. Quem começa alterna entre as
  séries (par: nós; ímpar: oponente), garantindo equilíbrio exato play/draw.
  Como o maindeck não muda, os resultados do Game 1 são calculados uma única
  vez (``prepare``) e reaproveitados por todos os indivíduos e rodadas.
* **Games 2 e 3 (pós-sideboard)**: deck montado pelo plano de sideboarding
  (sorteado ou por afinidade, ver ``sideboarding.py``). O perdedor do jogo
  anterior começa jogando. O Game 3 só é jogado se a série estiver 1–1.

Cada fase é enviada ao motor como lotes de jogos independentes, um lote por
deck pós-side distinto.

Os relatórios guardam contagens (e não só taxas), para que rodadas repetidas do
mesmo sideboard possam ser somadas (``merge``) em uma estimativa acumulada.

Métricas por confronto e agregadas pela participação no metajogo:

* ``winrate_md1``       – taxa de vitória no Game 1;
* ``winrate_bo3``       – taxa de vitória de séries (match win rate);
* ``winrate_postboard`` – taxa de vitória nos jogos 2 e 3;
* ``delta_winrate``     – ΔWinRate = WinRate_Bo3 − WinRate_Md1.
"""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from dataclasses import dataclass, replace
from functools import lru_cache
from typing import Callable, Sequence

from tccmagic.cards import Card, Database, Deck, Opponent
from tccmagic.sideboarding import SideboardPlan, build_sideboard_plan, random_sideboard_plan
from tccmagic.simulation.base import GameSpec, MatchEngine


def wilson_interval(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Intervalo de confiança de Wilson para uma proporção (95% com z = 1,96)."""
    if n == 0:
        return 0.0, 1.0
    p = wins / n
    center = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, center - half), min(1.0, center + half)


Swaps = tuple[tuple[str, int], ...]  # (carta, cópias trocadas somadas sobre as séries)


def _add_swaps(a: Swaps, b: Swaps) -> Swaps:
    total = Counter(dict(a))
    total.update(dict(b))
    return tuple(sorted(total.items(), key=lambda item: (-item[1], item[0])))


@dataclass(frozen=True)
class MatchupReport:
    opponent: str
    archetype: str
    meta_share: float
    n_matches: int
    game1_wins: int
    match_wins: int
    postboard_games: int
    postboard_wins: int
    swaps_in: Swaps = ()
    swaps_out: Swaps = ()

    @property
    def winrate_md1(self) -> float:
        return self.game1_wins / self.n_matches

    @property
    def winrate_bo3(self) -> float:
        return self.match_wins / self.n_matches

    @property
    def winrate_postboard(self) -> float:
        return self.postboard_wins / self.postboard_games

    @property
    def delta_winrate(self) -> float:
        return self.winrate_bo3 - self.winrate_md1

    def _describe(self, swaps: Swaps, sign: str) -> str:
        """Cópias por série: inteiro no plano por afinidade (igual em toda série), média no aleatório."""
        def fmt(total: int) -> str:
            per_series = total / self.n_matches
            return f"{per_series:g}" if per_series == int(per_series) else f"{per_series:.2f}"

        return ", ".join(f"{sign}{fmt(total)} {name}" for name, total in swaps) or "—"

    @property
    def cards_in(self) -> str:
        return self._describe(self.swaps_in, "+")

    @property
    def cards_out(self) -> str:
        return self._describe(self.swaps_out, "-")

    def merge(self, other: "MatchupReport") -> "MatchupReport":
        """Soma as séries de outra rodada do mesmo confronto."""
        return replace(
            self,
            n_matches=self.n_matches + other.n_matches,
            game1_wins=self.game1_wins + other.game1_wins,
            match_wins=self.match_wins + other.match_wins,
            postboard_games=self.postboard_games + other.postboard_games,
            postboard_wins=self.postboard_wins + other.postboard_wins,
            swaps_in=_add_swaps(self.swaps_in, other.swaps_in),
            swaps_out=_add_swaps(self.swaps_out, other.swaps_out),
        )


@dataclass(frozen=True)
class EvaluationReport:
    matchups: tuple[MatchupReport, ...]

    def _weighted(self, values: Sequence[float]) -> float:
        shares = [m.meta_share for m in self.matchups]
        return sum(s * v for s, v in zip(shares, values)) / sum(shares)

    @property
    def winrate_md1(self) -> float:
        return self._weighted([m.winrate_md1 for m in self.matchups])

    @property
    def winrate_bo3(self) -> float:
        return self._weighted([m.winrate_bo3 for m in self.matchups])

    @property
    def winrate_postboard(self) -> float:
        return self._weighted([m.winrate_postboard for m in self.matchups])

    @property
    def delta_winrate(self) -> float:
        return self.winrate_bo3 - self.winrate_md1

    @property
    def n_matches(self) -> int:
        """Séries jogadas contra cada oponente."""
        return min(m.n_matches for m in self.matchups)

    @property
    def stderr_bo3(self) -> float:
        """Erro padrão da WinRate_Bo3 agregada, supondo séries independentes.

        Usa a proporção ajustada de Agresti–Coull, para que confrontos com
        0% ou 100% em poucas séries não aparentem ter erro zero.
        """
        total = sum(m.meta_share for m in self.matchups)
        variance = 0.0
        for m in self.matchups:
            n = m.n_matches + 4
            p = (m.match_wins + 2) / n
            variance += (m.meta_share / total) ** 2 * p * (1 - p) / n
        return math.sqrt(variance)

    def merge(self, other: "EvaluationReport") -> "EvaluationReport":
        return EvaluationReport(tuple(a.merge(b) for a, b in zip(self.matchups, other.matchups)))


PLAN_MODES = ("aleatorio", "afinidade")

# Jogo pós-side já simulado: (oponente, assinatura do deck, série, jogo, começa jogando).
GameKey = tuple[str, tuple[tuple[str, ...], tuple[str, ...]], int, int, bool]
# Lote de jogos para o motor: (índice do oponente, deck, jogos).
Batch = tuple[int, Deck, list[GameSpec]]
BatchRunner = Callable[[list[Batch]], list[list[bool]]]


@lru_cache(maxsize=1 << 16)
def _hash_unit(text: str) -> float:
    """Número pseudoaleatório em [0, 1) fixado pelo texto (estável entre processos e execuções)."""
    digest = hashlib.blake2b(text.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") / 2.0**64


class Bo3Simulator:
    """Joga séries Bo3 e guarda cada jogo pós-side simulado.

    **Plano por série.** No modo ``aleatorio`` o plano (quantas e quais cartas
    entram e saem) é sorteado por bloco de ``plan_block`` séries consecutivas.
    O sorteio depende de (``plan_seed``, oponente, bloco), e não do sideboard:
    sideboards que contêm as cartas sorteadas recebem o mesmo plano (números
    aleatórios comuns). Os blocos existem por custo: cada deck distinto exige
    uma chamada separada ao Forge (~16 s só de inicialização da JVM).

    **Cache de jogos.** O resultado de um jogo depende só do deck pós-side,
    do oponente e da série, e não do sideboard de 15 cartas que o originou. Os
    jogos ficam em ``games``, indexados por (oponente, deck, série, jogo,
    quem começa); sideboards diferentes que geram o mesmo deck reaproveitam os
    jogos já simulados em vez de jogá-los de novo.
    """

    def __init__(
        self,
        database: Database,
        engine: MatchEngine,
        matches_per_opponent: int = 50,
        max_swaps: int = 5,
        swap_margin: float = 0.0,
        plan: str = "aleatorio",
        plan_block: int = 10,
        plan_seed: int = 2024,
    ):
        if matches_per_opponent < 1:
            raise ValueError("matches_per_opponent deve ser >= 1.")
        if plan not in PLAN_MODES:
            raise ValueError(f"Plano de sideboarding desconhecido: {plan!r} (use {' ou '.join(PLAN_MODES)}).")
        if plan_block < 1:
            raise ValueError("plan_block deve ser >= 1.")
        self.db = database
        self.engine = engine
        self.matches_per_opponent = matches_per_opponent
        self.max_swaps = max_swaps
        self.swap_margin = swap_margin
        self.plan = plan
        self.plan_block = plan_block
        self.plan_seed = plan_seed
        # Resultados do Game 1 por oponente; preenchido por ``prepare`` (ou por
        # quem os jogou em paralelo, ver ``FitnessEvaluator``).
        self.game1: dict[str, list[bool]] | None = None
        self.games: dict[GameKey, bool] = {}
        self.games_played = 0   # jogos pós-side efetivamente simulados pelo motor
        self.games_reused = 0   # jogos pós-side atendidos pelo cache
        self._plans: dict[tuple, SideboardPlan] = {}

    # ------------------------------------------------------------------ #
    def play_game1(self, opp: Opponent, n_matches: int | None = None, match_offset: int = 0) -> list[bool]:
        """Joga o Game 1 de ``n_matches`` séries com o maindeck."""
        n = self.matches_per_opponent if n_matches is None else n_matches
        specs = [GameSpec(match_offset + m, 1, on_play=(m % 2 == 0)) for m in range(n)]
        return self.engine.play_games(self.db.maindeck, opp, specs)

    def prepare(self) -> None:
        """Joga (uma única vez) os Games 1 com o maindeck contra cada oponente."""
        if self.game1 is None:
            self.game1 = {opp.name: self.play_game1(opp) for opp in self.db.opponents}

    def evaluate(self, sideboard: Sequence[Card], round_index: int = 0) -> EvaluationReport:
        """Avalia um sideboard jogando séries Bo3 contra toda a suíte de oponentes.

        ``round_index`` distingue rodadas repetidas do mesmo sideboard: cada
        rodada joga Games 2/3 novos sobre os mesmos resultados de Game 1.
        """
        self.prepare()
        assert self.game1 is not None
        return self.play_postboard([(sideboard, round_index * self.matches_per_opponent)], self.game1)[0]

    # ------------------------------------------------------------------ #
    # Planos
    # ------------------------------------------------------------------ #
    def plan_for(self, opp: Opponent, sideboard: Sequence[Card], match_index: int) -> SideboardPlan:
        """Plano de sideboarding usado na série ``match_index`` contra ``opp``."""
        side_key = tuple(sorted(c.name for c in sideboard))
        if self.plan == "afinidade":
            key: tuple = (opp.name, side_key)
        else:
            key = (opp.name, side_key, match_index // self.plan_block)
        plan = self._plans.get(key)
        if plan is None:
            if self.plan == "afinidade":
                plan = build_sideboard_plan(
                    self.db.maindeck, sideboard, opp.archetype, self.db.affinity(opp.archetype),
                    max_swaps=self.max_swaps, margin=self.swap_margin,
                )
            else:
                prefix = f"{self.plan_seed}|{opp.name}|{match_index // self.plan_block}|"
                # Nº de trocas uniforme em 1..max_swaps.
                n_swaps = 1 + int(_hash_unit(prefix + "n_swaps") * self.max_swaps) if self.max_swaps else 0
                plan = random_sideboard_plan(
                    self.db.maindeck, sideboard, opp.archetype, lambda label: _hash_unit(prefix + label), n_swaps
                )
            self._plans[key] = plan
        return plan

    # ------------------------------------------------------------------ #
    # Jogos pós-side
    # ------------------------------------------------------------------ #
    def run_batches(self, batches: list[Batch]) -> list[list[bool]]:
        """Executor serial dos lotes (o ``FitnessEvaluator`` usa um paralelo)."""
        return [self.engine.play_games(deck, self.db.opponents[i], specs) for i, deck, specs in batches]

    def _play_phase(self, requests: list[tuple[int, SideboardPlan, GameSpec]], runner: BatchRunner) -> list[bool]:
        """Resolve uma fase (todos os G2 ou todos os G3): cache primeiro, o resto em lotes por deck."""
        opponents = self.db.opponents
        keys: list[GameKey] = [
            (opponents[i].name, plan.signature, spec.match_index, spec.game_number, spec.on_play)
            for i, plan, spec in requests
        ]
        pending: dict[tuple, tuple[int, Deck, dict[GameKey, GameSpec]]] = {}
        for key, (i, plan, spec) in zip(keys, requests):
            if key not in self.games:
                pending.setdefault((i, plan.signature), (i, plan.deck, {}))[2].setdefault(key, spec)
        batches = [(i, deck, list(specs.values())) for i, deck, specs in pending.values()]
        for (_, _, specs), outcomes in zip(pending.values(), runner(batches) if batches else []):
            self.games.update(zip(specs, outcomes))
        played = sum(len(specs) for _, _, specs in pending.values())
        self.games_played += played
        self.games_reused += len(requests) - played
        return [self.games[key] for key in keys]

    def play_postboard(
        self,
        jobs: Sequence[tuple[Sequence[Card], int]],
        game1: dict[str, list[bool]],
        runner: BatchRunner | None = None,
    ) -> list[EvaluationReport]:
        """Joga os Games 2/3 de cada (sideboard, índice inicial das séries) contra cada oponente.

        As séries de todos os sideboards passam juntas por fase (todos os G2,
        depois todos os G3), para que um deck repetido entre sideboards seja
        simulado uma única vez.
        """
        runner = runner or self.run_batches
        opponents = self.db.opponents
        # (sideboard j, oponente i, série local m, índice global da série, plano)
        series = [
            (j, i, m, offset + m, self.plan_for(opp, sideboard, offset + m))
            for j, (sideboard, offset) in enumerate(jobs)
            for i, opp in enumerate(opponents)
            for m in range(len(game1[opp.name]))
        ]
        g1 = [game1[opponents[i].name][m] for _, i, m, _, _ in series]

        # Game 2: o perdedor do Game 1 começa jogando.
        g2 = self._play_phase(
            [(i, plan, GameSpec(idx, 2, on_play=not won)) for (_, i, _, idx, plan), won in zip(series, g1)],
            runner,
        )
        # Game 3: apenas nas séries empatadas em 1–1.
        tied = [s for s in range(len(series)) if g1[s] != g2[s]]
        g3_results = self._play_phase(
            [(series[s][1], series[s][4], GameSpec(series[s][3], 3, on_play=not g2[s])) for s in tied], runner
        )
        g3 = dict(zip(tied, g3_results))

        grouped: dict[tuple[int, int], list[int]] = {}
        for s, (j, i, *_) in enumerate(series):
            grouped.setdefault((j, i), []).append(s)

        reports = []
        for j in range(len(jobs)):
            matchups = []
            for i, opp in enumerate(opponents):
                rows = grouped[(j, i)]
                plans = [series[s][4] for s in rows]
                matchups.append(MatchupReport(
                    opponent=opp.name,
                    archetype=opp.archetype,
                    meta_share=opp.meta_share,
                    n_matches=len(rows),
                    game1_wins=sum(g1[s] for s in rows),
                    match_wins=sum(1 for s in rows if (g1[s] and g2[s]) or g3.get(s, False)),
                    postboard_games=len(rows) + sum(1 for s in rows if s in g3),
                    postboard_wins=sum(g2[s] for s in rows) + sum(g3.get(s, False) for s in rows),
                    swaps_in=_add_swaps((), tuple(Counter(c.name for p in plans for c in p.cards_in).items())),
                    swaps_out=_add_swaps((), tuple(Counter(c.name for p in plans for c in p.cards_out).items())),
                ))
            reports.append(EvaluationReport(tuple(matchups)))
        return reports
