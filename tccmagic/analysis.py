"""Análise das trocas sorteadas: quanto cada carta que entra (ou sai) muda a taxa de vitória.

Com o plano de sideboarding ``aleatorio``, quais cartas entram e quais saem é
sorteado em cada bloco de séries. Por isso a associação entre trocar uma carta
e vencer pode ser lida como efeito causal (não há um jogador escolhendo as
cartas "certas" para cada confronto e enviesando a comparação).

Modelo por oponente (probabilidade linear), sobre todos os jogos pós-side
simulados (busca + validação, cada jogo contado uma única vez):

    P(vitória) = α + Σ_c β_c · nº de cópias de c que entraram
                   − Σ_f γ_f · nº de cópias de f que saíram

Como toda troca põe uma carta e tira outra, só diferenças entre cartas são
identificáveis (somar a mesma constante a todos os β e γ não muda nada). A
normalização adotada é que a média dos γ, ponderada pelas cópias flex do
maindeck, seja zero. Assim:

* ``entra``: β_c = ganho, em probabilidade de vitória por jogo, de colocar uma
  cópia de c no lugar de uma carta flex qualquer do maindeck;
* ``sai``:  −γ_f = ganho de tirar f em vez de uma carta flex qualquer
  (positivo: f é das que menos fazem falta contra aquele oponente).

Os erros padrão são robustos à heterocedasticidade (HC1), inevitável com
resposta binária. Eles tratam os jogos como independentes; G2 e G3 da mesma
série compartilham o plano, então os intervalos são um pouco otimistas.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

import numpy as np

from tccmagic.cards import Database
from tccmagic.simulation.bo3 import GameKey

Z95 = 1.96


@dataclass(frozen=True)
class SwapEffect:
    opponent: str
    card: str
    role: str        # "entra" ou "sai"
    games: int       # jogos pós-side em que ao menos uma cópia entrou/saiu
    winrate: float   # taxa de vitória bruta nesses jogos
    effect: float    # ganho estimado por cópia (ver docstring do módulo)
    stderr: float

    @property
    def ci95(self) -> tuple[float, float]:
        return self.effect - Z95 * self.stderr, self.effect + Z95 * self.stderr

    @property
    def significant(self) -> bool:
        low, high = self.ci95
        return low > 0 or high < 0


@dataclass(frozen=True)
class OpponentSwapAnalysis:
    opponent: str
    archetype: str
    meta_share: float
    games: int                 # jogos pós-side usados no ajuste
    winrate: float             # taxa de vitória pós-side bruta
    no_swap_winrate: float     # α: taxa estimada sem nenhuma troca
    effects: tuple[SwapEffect, ...]

    def role(self, role: str) -> list[SwapEffect]:
        """Efeitos de um papel ("entra"/"sai"), do maior para o menor."""
        return sorted((e for e in self.effects if e.role == role), key=lambda e: -e.effect)


def _fit(y: np.ndarray, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Mínimos quadrados com covariância HC1; NaN nos erros se o sistema for degenerado."""
    n, p = x.shape
    theta, *_ = np.linalg.lstsq(x, y, rcond=None)
    if np.linalg.matrix_rank(x) < p or n <= p:
        return theta, np.full((p, p), np.nan)
    bread = np.linalg.inv(x.T @ x)
    scores = x * (y - x @ theta)[:, None]
    return theta, bread @ (scores.T @ scores) @ bread * n / (n - p)


def analyze_opponent(rows: Sequence[tuple[Sequence[str], Sequence[str], bool]], flex_counts: Counter[str],
                     opponent: str, archetype: str, meta_share: float) -> OpponentSwapAnalysis | None:
    """Ajusta o modelo para um oponente; ``rows`` = (cartas que entraram, que saíram, venceu)."""
    if not rows:
        return None
    ins = sorted({c for cards_in, _, _ in rows for c in cards_in})
    outs = sorted({c for _, cards_out, _ in rows for c in cards_out})
    y = np.array([float(won) for _, _, won in rows])
    if not ins or not outs:
        return OpponentSwapAnalysis(opponent, archetype, meta_share, len(rows), float(y.mean()),
                                    float(y.mean()), ())

    # Colunas: α, β (uma por carta que entra), γ (uma por carta que sai, exceto a 1ª: γ_ref = 0).
    n_in, n_out = len(ins), len(outs)
    x = np.zeros((len(rows), 1 + n_in + n_out - 1))
    x[:, 0] = 1.0
    for r, (cards_in, cards_out, _) in enumerate(rows):
        for c in cards_in:
            x[r, 1 + ins.index(c)] += 1.0
        for f in cards_out:
            k = outs.index(f)
            if k > 0:
                x[r, n_in + k] -= 1.0
    theta, cov = _fit(y, x)

    # Reparametrização para Σ w_f γ_f = 0 (w = cópias flex no maindeck): β' = β − m, γ' = γ − m.
    w = np.array([flex_counts.get(f, 1) for f in outs], dtype=float)
    w /= w.sum()
    m_row = np.zeros(x.shape[1])
    m_row[1 + n_in:] = w[1:]                       # m = Σ_{f>ref} w_f γ_f  (γ_ref = 0)
    rows_l = [np.eye(x.shape[1])[0]]
    rows_l += [np.eye(x.shape[1])[1 + i] - m_row for i in range(n_in)]
    for k in range(n_out):
        gamma = np.zeros(x.shape[1]) if k == 0 else np.eye(x.shape[1])[n_in + k]
        rows_l.append(-(gamma - m_row))            # efeito de tirar f = −γ'_f
    lin = np.vstack(rows_l)
    est = lin @ theta
    se = np.sqrt(np.clip(np.diag(lin @ cov @ lin.T), 0.0, None))

    def raw(role_index: int, card: str) -> tuple[int, float]:
        hits = [row[2] for row in rows if card in row[role_index]]
        return len(hits), (sum(hits) / len(hits) if hits else float("nan"))

    effects = []
    for i, card in enumerate(ins):
        games, winrate = raw(0, card)
        effects.append(SwapEffect(opponent, card, "entra", games, winrate, float(est[1 + i]), float(se[1 + i])))
    for k, card in enumerate(outs):
        games, winrate = raw(1, card)
        idx = 1 + n_in + k
        effects.append(SwapEffect(opponent, card, "sai", games, winrate, float(est[idx]), float(se[idx])))
    return OpponentSwapAnalysis(opponent, archetype, meta_share, len(rows), float(y.mean()),
                                float(est[0]), tuple(effects))


def analyze_swaps(games: Mapping[GameKey, bool] | Iterable[tuple[GameKey, bool]],
                  database: Database) -> list[OpponentSwapAnalysis]:
    """Efeito de cada carta trocada, por oponente, a partir de todos os jogos pós-side simulados.

    ``games`` é o cache do simulador ou uma sequência de (chave, venceu); a
    sequência permite somar jogos de várias execuções (ver ``tccmagic/archive.py``).
    """
    flex_counts = Counter(c.name for c in database.maindeck.flex_cards())
    by_opponent: dict[str, list[tuple[Sequence[str], Sequence[str], bool]]] = {}
    records = games.items() if isinstance(games, Mapping) else games
    for (opponent, (cards_in, cards_out), _, game_number, _), won in records:
        if game_number >= 2:
            by_opponent.setdefault(opponent, []).append((cards_in, cards_out, won))
    results = []
    for opp in database.opponents:
        analysis = analyze_opponent(by_opponent.get(opp.name, []), flex_counts,
                                    opp.name, opp.archetype, opp.meta_share)
        if analysis is not None:
            results.append(analysis)
    return results


def metagame_effects(analyses: Sequence[OpponentSwapAnalysis]) -> list[SwapEffect]:
    """Efeito de colocar cada carta, ponderado pela participação de cada oponente no metajogo.

    Só inclui cartas estimadas contra todos os oponentes; o erro padrão supõe
    oponentes independentes (os jogos de cada um são distintos).
    """
    total = sum(a.meta_share for a in analyses)
    if not analyses or total <= 0:
        return []
    per_card: dict[str, list[tuple[float, SwapEffect]]] = {}
    for a in analyses:
        for e in a.role("entra"):
            per_card.setdefault(e.card, []).append((a.meta_share / total, e))
    pooled = []
    for card, items in per_card.items():
        if len(items) != len(analyses):
            continue
        games = sum(e.games for _, e in items)
        wins = sum(e.winrate * e.games for _, e in items)
        effect = sum(s * e.effect for s, e in items)
        stderr = math.sqrt(sum((s * e.stderr) ** 2 for s, e in items))
        pooled.append(SwapEffect("Metajogo", card, "entra", games, wins / games if games else float("nan"),
                                 effect, stderr))
    return sorted(pooled, key=lambda e: -e.effect)
