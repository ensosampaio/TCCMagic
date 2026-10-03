"""Interface comum dos motores de partida (Forge ou simulador substituto)."""

from __future__ import annotations

import zlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Sequence

from tccmagic.cards import Deck, Opponent


@dataclass(frozen=True)
class GameSpec:
    """Descrição de um jogo individual dentro de uma série Bo3."""

    match_index: int
    game_number: int  # 1 = pré-sideboard; 2 e 3 = pós-sideboard
    on_play: bool     # True se o nosso deck começa jogando


class MatchEngine(ABC):
    """Joga lotes de jogos independentes entre ``deck`` e ``opponent``.

    Receber os jogos em lote permite que o motor Forge execute vários jogos numa
    única chamada à JVM, amortizando o custo de inicialização.
    """

    #: nome exibido nos relatórios
    name: str = "engine"
    #: True se repetir o mesmo jogo (mesmo deck e ``GameSpec``) dá sempre o mesmo resultado
    deterministic: bool = False

    @abstractmethod
    def play_games(self, deck: Deck, opponent: Opponent, specs: Sequence[GameSpec]) -> list[bool]:
        """Retorna, para cada ``GameSpec``, True se o nosso deck venceu (empate = False)."""


def stable_id(text: str) -> int:
    """Hash estável entre processos/execuções (``hash()`` do Python é aleatorizado)."""
    return zlib.crc32(text.encode("utf-8"))
