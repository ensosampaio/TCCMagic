"""Arquivo de jogos pós-side: guarda em disco os jogos de cada execução.

A análise das trocas (``tccmagic/analysis.py``) precisa de muitos jogos para
separar efeitos de poucos pontos percentuais. Sem o arquivo, os jogos de uma
execução se perdem quando ela termina. Com ele, cada execução grava os seus em
``<pasta>/<execução>.json`` e as seguintes somam esses jogos à própria análise.

Os jogos arquivados servem **só à análise das trocas**. Eles nunca entram no
cache do simulador: se entrassem, uma execução nova reaproveitaria os
resultados antigos em vez de jogar, e a validação deixaria de usar séries novas.

Só são somados jogos do mesmo **contexto** (motor, maindeck e listas dos
oponentes): mudar qualquer um deles muda o que um jogo mede.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Iterable, Mapping

from tccmagic.cards import Database
from tccmagic.simulation.bo3 import GameKey

GameRecord = tuple[GameKey, bool]


def context_fingerprint(database: Database, engine: str) -> str:
    """Identifica o que um jogo mede: motor, maindeck e listas dos oponentes."""
    payload = {
        "engine": engine,
        "maindeck": sorted(database.maindeck.counts().items()),
        "opponents": [[opp.name, sorted(opp.deck.counts().items())] for opp in database.opponents],
    }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.blake2b(text.encode("utf-8"), digest_size=8).hexdigest()


def _to_row(key: GameKey, won: bool) -> list:
    opponent, (cards_in, cards_out), match_index, game_number, on_play = key
    return [opponent, list(cards_in), list(cards_out), match_index, game_number, on_play, won]


def _from_row(row: list) -> GameRecord:
    opponent, cards_in, cards_out, match_index, game_number, on_play, won = row
    key = (opponent, (tuple(cards_in), tuple(cards_out)), int(match_index), int(game_number), bool(on_play))
    return key, bool(won)


class GameArchive:
    """Jogos de execuções anteriores (``previous``) e o arquivo da execução atual."""

    def __init__(self, directory: str | Path, context: str, engine: str = ""):
        self.directory = Path(directory)
        self.context = context
        self.engine = engine
        self.previous: list[GameRecord] = []
        self.skipped_runs = 0  # execuções de outro contexto, deixadas de fora
        for path in sorted(self.directory.glob("*.json")):
            with open(path, encoding="utf-8") as fh:
                run = json.load(fh)
            if run.get("context") != context:
                self.skipped_runs += 1
                continue
            self.previous += [_from_row(row) for row in run["games"]]
        # Escolhido depois da leitura: o arquivo desta execução nunca conta como anterior.
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.path = self.directory / f"{stamp}.json"
        suffix = 2
        while self.path.exists():
            self.path = self.directory / f"{stamp}-{suffix}.json"
            suffix += 1

    def save(self, games: Mapping[GameKey, bool]) -> Path | None:
        """Grava (ou regrava) os jogos desta execução; nada é escrito se não houver jogos."""
        if not games:
            return None
        self.directory.mkdir(parents=True, exist_ok=True)
        run = {
            "context": self.context,
            "engine": self.engine,
            "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "games": [_to_row(key, won) for key, won in games.items()],
        }
        partial = self.path.with_suffix(".tmp")
        with open(partial, "w", encoding="utf-8") as fh:
            json.dump(run, fh, ensure_ascii=False)
        os.replace(partial, self.path)  # nunca deixa um arquivo pela metade
        return self.path

    def merged(self, games: Mapping[GameKey, bool], deterministic: bool) -> Iterable[GameRecord]:
        """Jogos anteriores + os desta execução.

        Num motor determinístico, a mesma chave dá sempre o mesmo resultado:
        repeti-la seria contar o mesmo jogo duas vezes, então ela entra uma vez só.
        """
        if deterministic:
            return {**dict(self.previous), **games}.items()
        return [*self.previous, *games.items()]
