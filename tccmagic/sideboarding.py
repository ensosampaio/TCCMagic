"""Planos de sideboarding (o que entra e o que sai entre o Game 1 e os Games 2/3).

Há dois modos (``Bo3Simulator.plan``):

* **aleatorio** (padrão): as cartas que entram são sorteadas entre as 15 do
  sideboard e as que saem entre as cópias 'flex' do maindeck (nunca terrenos).
  Nenhuma regra fixa decide a troca; o efeito de cada carta é estimado depois,
  a partir dos resultados (ver ``tccmagic/analysis.py``).
* **afinidade**: plano determinístico pela tabela arquétipo × atributo, abaixo.

Plano por afinidade: para um oponente de arquétipo A, a relevância de uma carta c é

    Rel(c, A) = [Σ_{i=2..9} a_i · v_i(c)] · (1 + a_1 · v_1(c))

onde a = afinidade[A]. Os atributos funcionais (2..9) dizem *se* a carta faz
algo contra o arquétipo; a eficiência de mana (atributo 1) apenas amplifica
esse valor. Assim, uma carta barata que não faz nada no confronto tem
relevância zero, em vez de ganhar pontos só por custar pouco.

As cartas do sideboard são ordenadas por relevância decrescente e as cópias
'flex' do maindeck por relevância crescente. Faz-se a troca par a par
(melhor do side ↔ pior do main) enquanto a carta que entra for mais relevante
que a que sai (por uma margem) e o limite de trocas não for atingido.

O plano é determinístico e explicável: para cada confronto sabe-se exatamente
o que entrou, o que saiu e por quê.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Callable, Sequence

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

    @property
    def signature(self) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Identidade do deck pós-side (o maindeck é fixo): nomes que entram e que saem."""
        return tuple(sorted(c.name for c in self.cards_in)), tuple(sorted(c.name for c in self.cards_out))

    def describe(self) -> tuple[str, str]:
        """Texto compacto '+2 Rest in Peace, +1 ...' / '-2 Lightning Bolt, ...'."""
        def fmt(cards: Sequence[Card], sign: str) -> str:
            counts: dict[str, int] = {}
            for card in cards:
                counts[card.name] = counts.get(card.name, 0) + 1
            return ", ".join(f"{sign}{n} {name}" for name, n in counts.items()) or "—"

        return fmt(self.cards_in, "+"), fmt(self.cards_out, "-")


def relevance(card: Card, affinity: np.ndarray) -> float:
    v = card.v
    return float(affinity[1:] @ v[1:]) * (1.0 + float(affinity[0] * v[0]))


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


def _copy_labels(cards: Sequence[Card]) -> list[tuple[str, Card]]:
    """Rotula cada cópia ("Blood Moon #1", "Blood Moon #2", ...) na ordem em que aparece."""
    seen: Counter[str] = Counter()
    labeled = []
    for card in cards:
        seen[card.name] += 1
        labeled.append((f"{card.name} #{seen[card.name]}", card))
    return labeled


def random_sideboard_plan(
    maindeck: Deck,
    sideboard: Sequence[Card],
    archetype: str,
    priority: Callable[[str], float],
    n_swaps: int,
) -> SideboardPlan:
    """Troca ``n_swaps`` cartas sorteadas do sideboard por cópias 'flex' sorteadas do maindeck.

    ``priority`` dá um número aleatório em [0, 1) para cada rótulo de cópia
    ("in:Blood Moon #2", "out:Ragavan, Nimble Pilferer #1"); entram as cópias
    do sideboard de menor prioridade e saem as cópias flex de menor prioridade.
    Para um sideboard fixo isso é um sorteio uniforme de ``n_swaps`` das suas
    cópias. Como a prioridade depende só do rótulo (e não do sideboard), dois
    sideboards que contêm as cartas sorteadas recebem exatamente o mesmo plano,
    o que permite reaproveitar os jogos já simulados para aquele deck.

    Uma carta nunca sai para dar lugar a ela mesma (ex.: Blood Moon do side no
    lugar do Blood Moon do main), e terrenos nunca saem.
    """
    incoming = sorted(_copy_labels(sideboard), key=lambda lc: priority("in:" + lc[0]))[:n_swaps]
    names_in = {card.name for _, card in incoming}
    candidates = [lc for lc in _copy_labels(maindeck.flex_cards()) if lc[1].name not in names_in]
    outgoing = sorted(candidates, key=lambda lc: priority("out:" + lc[0]))[: len(incoming)]
    incoming = incoming[: len(outgoing)]

    cards_in = [card for _, card in incoming]
    cards_out = [card for _, card in outgoing]
    deck = maindeck.swap(cards_out, cards_in, name=f"{maindeck.name} (pós-side vs {archetype})")
    return SideboardPlan(archetype, tuple(cards_in), tuple(cards_out), deck)
