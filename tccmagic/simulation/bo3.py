"""Orquestração de séries Melhor-de-3 (Bo3) contra a suíte de oponentes.

Estrutura de cada série:

* **Game 1 (Md1)**: maindeck fixo vs. oponente. Quem começa alterna entre as
  séries (par: nós; ímpar: oponente), garantindo equilíbrio exato play/draw.
  Como o maindeck não muda, os resultados do Game 1 são calculados uma única
  vez (``prepare``) e reaproveitados por todos os indivíduos.
* **Games 2 e 3 (pós-sideboard)**: deck montado pelo plano de sideboarding
  para o arquétipo do oponente. O perdedor do jogo anterior começa jogando.
  O Game 3 só é jogado se a série estiver 1–1.

Cada fase é enviada ao motor como um lote de jogos independentes.

Métricas por confronto e agregadas pela participação no metajogo:

* ``winrate_md1``       – taxa de vitória no Game 1;
* ``winrate_bo3``       – taxa de vitória de séries (match win rate);
* ``winrate_postboard`` – taxa de vitória nos jogos 2 e 3;
* ``delta_winrate``     – ΔWinRate = WinRate_Bo3 − WinRate_Md1.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from tccmagic.cards import Card, Database, Opponent
from tccmagic.sideboarding import build_sideboard_plan
from tccmagic.simulation.base import GameSpec, MatchEngine


@dataclass(frozen=True)
class MatchupReport:
    opponent: str
    archetype: str
    meta_share: float
    n_matches: int
    winrate_md1: float
    winrate_bo3: float
    winrate_postboard: float
    cards_in: str
    cards_out: str

    @property
    def delta_winrate(self) -> float:
        return self.winrate_bo3 - self.winrate_md1


@dataclass(frozen=True)
class EvaluationReport:
    matchups: tuple[MatchupReport, ...]
    winrate_md1: float
    winrate_bo3: float
    winrate_postboard: float

    @property
    def delta_winrate(self) -> float:
        return self.winrate_bo3 - self.winrate_md1


class Bo3Simulator:
    def __init__(
        self,
        database: Database,
        engine: MatchEngine,
        matches_per_opponent: int = 50,
        max_swaps: int = 5,
        swap_margin: float = 0.0,
    ):
        if matches_per_opponent < 1:
            raise ValueError("matches_per_opponent deve ser >= 1.")
        self.db = database
        self.engine = engine
        self.matches_per_opponent = matches_per_opponent
        self.max_swaps = max_swaps
        self.swap_margin = swap_margin
        shares = np.array([o.meta_share for o in database.opponents], dtype=float)
        self._weights = shares / shares.sum()
        self._game1: dict[str, list[bool]] | None = None

    # ------------------------------------------------------------------ #
    def prepare(self) -> None:
        """Joga (uma única vez) os Games 1 com o maindeck contra cada oponente."""
        if self._game1 is not None:
            return
        self._game1 = {}
        for opp in self.db.opponents:
            specs = [GameSpec(m, 1, on_play=(m % 2 == 0)) for m in range(self.matches_per_opponent)]
            self._game1[opp.name] = self.engine.play_games(self.db.maindeck, opp, specs)

    def evaluate(self, sideboard: Sequence[Card]) -> EvaluationReport:
        """Avalia um sideboard jogando séries Bo3 contra toda a suíte de oponentes."""
        self.prepare()
        matchups = tuple(self._play_matchup(opp, sideboard) for opp in self.db.opponents)
        w = self._weights
        return EvaluationReport(
            matchups=matchups,
            winrate_md1=float(w @ [m.winrate_md1 for m in matchups]),
            winrate_bo3=float(w @ [m.winrate_bo3 for m in matchups]),
            winrate_postboard=float(w @ [m.winrate_postboard for m in matchups]),
        )

    # ------------------------------------------------------------------ #
    def _play_matchup(self, opp: Opponent, sideboard: Sequence[Card]) -> MatchupReport:
        assert self._game1 is not None
        plan = build_sideboard_plan(
            self.db.maindeck, sideboard, opp.archetype, self.db.affinity(opp.archetype),
            max_swaps=self.max_swaps, margin=self.swap_margin,
        )
        n = self.matches_per_opponent
        g1 = self._game1[opp.name]

        # Game 2: o perdedor do Game 1 começa jogando.
        g2_specs = [GameSpec(m, 2, on_play=not g1[m]) for m in range(n)]
        g2 = self.engine.play_games(plan.deck, opp, g2_specs)

        # Game 3: apenas nas séries empatadas em 1–1.
        tied = [m for m in range(n) if g1[m] != g2[m]]
        g3_specs = [GameSpec(m, 3, on_play=not g2[m]) for m in tied]
        g3 = dict(zip(tied, self.engine.play_games(plan.deck, opp, g3_specs)))

        match_wins = sum(1 for m in range(n) if (g1[m] and g2[m]) or g3.get(m, False))
        postboard_games = n + len(tied)
        postboard_wins = sum(g2) + sum(g3.values())
        cards_in, cards_out = plan.describe()
        return MatchupReport(
            opponent=opp.name,
            archetype=opp.archetype,
            meta_share=opp.meta_share,
            n_matches=n,
            winrate_md1=sum(g1) / n,
            winrate_bo3=match_wins / n,
            winrate_postboard=postboard_wins / postboard_games,
            cards_in=cards_in,
            cards_out=cards_out,
        )
