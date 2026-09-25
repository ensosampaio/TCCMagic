"""Plano de sideboarding por afinidade (entre o Game 1 e os Games 2/3).

Para um oponente de arquétipo A, a relevância de uma carta c é

    Rel(c, A) = afinidade[A] · v(c)

As cartas do sideboard são ordenadas por relevância decrescente e as cópias
'flex' do maindeck por relevância crescente. Faz-se a troca par a par
(melhor do side ↔ pior do main) enquanto a carta que entra for mais relevante
que a que sai (por uma margem) e o limite de trocas não for atingido.

O plano é determinístico e explicável: para cada confronto sabe-se exatamente
o que entrou, o que saiu e por quê.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from tccmagic.cards import Card, Deck


@dataclass(frozen=True)
class SideboardPlan:
    archetype: str
    cards_in: tuple[Card, ...]
    cards_out: tuple[Card, ...]
    deck: Deck

    @property
    def n_swaps(self) -> int:
        return len(self.cards_in)

    def describe(self) -> tuple[str, str]:
        """Texto compacto '+2 Rest in Peace, +1 ...' / '-2 Lightning Bolt, ...'."""
        def fmt(cards: Sequence[Card], sign: str) -> str:
            counts: dict[str, int] = {}
            for card in cards:
                counts[card.name] = counts.get(card.name, 0) + 1
            return ", ".join(f"{sign}{n} {name}" for name, n in counts.items()) or "—"

        return fmt(self.cards_in, "+"), fmt(self.cards_out, "-")


def relevance(card: Card, affinity: np.ndarray) -> float:
    return float(affinity @ card.v)


def build_sideboard_plan(
    maindeck: Deck,
    sideboard: Sequence[Card],
    archetype: str,
    affinity: np.ndarray,
    max_swaps: int = 5,
    margin: float = 0.0,
) -> SideboardPlan:
    """Monta o deck pós-sideboard (60 cartas) para um arquétipo oponente."""
    # Ordenação estável com desempate por nome => plano determinístico.
    incoming = sorted(sideboard, key=lambda c: (-relevance(c, affinity), c.name))
    outgoing = sorted(maindeck.flex_cards(), key=lambda c: (relevance(c, affinity), c.name))

    cards_in: list[Card] = []
    cards_out: list[Card] = []
    for card_in, card_out in zip(incoming, outgoing):
        if len(cards_in) >= max_swaps:
            break
        if relevance(card_in, affinity) <= relevance(card_out, affinity) + margin:
            break  # listas ordenadas: nenhuma troca posterior seria vantajosa
        cards_in.append(card_in)
        cards_out.append(card_out)

    deck = maindeck.swap(cards_out, cards_in, name=f"{maindeck.name} (pós-side vs {archetype})")
    return SideboardPlan(archetype, tuple(cards_in), tuple(cards_out), deck)
