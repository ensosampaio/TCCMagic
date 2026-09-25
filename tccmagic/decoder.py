"""Decodificação do cromossomo BRKGA-A em um sideboard legal de 15 cartas.

Passos (seção 4 da especificação):

1. Chave aleatória k_i ∈ [0, 1]  ⟹  w_i = 20·k_i − 10  ∈ [−10, +10].
2. Score(c) = Σ_{i=1..9} w_i · v_i(c) para cada entrada do pool.
3. Ordena por Score decrescente e seleciona as 15 primeiras entradas.

O pool é expandido em entradas por cópia (``SideboardSlot``), portanto a
seleção Top-15 é sempre legal: nenhuma entrada se repete e o limite de 4 cópias
(somando o maindeck) é respeitado por construção.

Retornos decrescentes por cópia: a k-ésima cópia de uma carta recebe
Score − δ·(k − 1). Com δ = 0 obtém-se a fórmula pura (todas as cópias empatam e
entram juntas); com δ > 0 o algoritmo só inclui uma cópia extra se ela ainda
superar as alternativas, o que produz sideboards mais diversificados.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from tccmagic.attributes import ATTRIBUTES, N_ATTRIBUTES
from tccmagic.cards import SIDEBOARD_SIZE, Card, Database, SideboardSlot

WEIGHT_MIN = -10.0
WEIGHT_MAX = 10.0


def keys_to_weights(keys: np.ndarray) -> np.ndarray:
    """Mapeamento determinístico k ∈ [0,1] → w ∈ [−10, +10]."""
    keys = np.asarray(keys, dtype=float)
    if keys.shape[-1] != N_ATTRIBUTES:
        raise ValueError(f"Cromossomo deve ter {N_ATTRIBUTES} chaves, recebeu {keys.shape[-1]}.")
    return keys * (WEIGHT_MAX - WEIGHT_MIN) + WEIGHT_MIN


@dataclass(frozen=True)
class DecodedSideboard:
    """Resultado da decodificação de um cromossomo."""

    weights: tuple[float, ...]
    slots: tuple[SideboardSlot, ...]
    scores: tuple[float, ...]

    @property
    def cards(self) -> list[Card]:
        return [slot.card for slot in self.slots]

    @property
    def key(self) -> tuple[str, ...]:
        """Identidade do sideboard (independe da ordem); usada como chave de cache."""
        return tuple(sorted(slot.label for slot in self.slots))

    def weights_by_attribute(self) -> dict[str, float]:
        return dict(zip(ATTRIBUTES, self.weights))

    def card_counts(self) -> list[tuple[str, int]]:
        """Lista compacta 'N x Carta' na ordem do ranking."""
        counts: dict[str, int] = {}
        for slot in self.slots:
            counts[slot.card.name] = counts.get(slot.card.name, 0) + 1
        return list(counts.items())


class SideboardDecoder:
    """Transforma cromossomos (vetores de 9 chaves) em sideboards de 15 cartas."""

    def __init__(self, database: Database, copy_penalty: float = 1.0, sideboard_size: int = SIDEBOARD_SIZE):
        if copy_penalty < 0:
            raise ValueError("copy_penalty deve ser >= 0.")
        self.slots: list[SideboardSlot] = database.sideboard_slots()
        if len(self.slots) < sideboard_size:
            raise ValueError("Pool menor que o tamanho do sideboard.")
        self.sideboard_size = sideboard_size
        self.copy_penalty = copy_penalty
        # Matriz V (n_slots × 9) e vetor de penalidades por cópia, pré-computados.
        self._vectors = np.vstack([slot.card.v for slot in self.slots])
        self._penalties = np.array([copy_penalty * (slot.copy_index - 1) for slot in self.slots])
        # Critério de desempate determinístico: nome da carta, depois índice da cópia.
        self._tiebreak = np.array(
            sorted(range(len(self.slots)), key=lambda i: (self.slots[i].card.name, self.slots[i].copy_index))
        ).argsort()

    @property
    def chromosome_length(self) -> int:
        return N_ATTRIBUTES

    def scores(self, weights: np.ndarray) -> np.ndarray:
        """Score de cada entrada do pool para um vetor de pesos."""
        return self._vectors @ np.asarray(weights, dtype=float) - self._penalties

    def decode(self, keys: Sequence[float] | np.ndarray) -> DecodedSideboard:
        weights = keys_to_weights(np.asarray(keys, dtype=float))
        scores = self.scores(weights)
        # np.lexsort usa a última chave como primária: Score decrescente, depois desempate.
        order = np.lexsort((self._tiebreak, -scores))[: self.sideboard_size]
        return DecodedSideboard(
            weights=tuple(float(w) for w in weights),
            slots=tuple(self.slots[i] for i in order),
            scores=tuple(float(scores[i]) for i in order),
        )
