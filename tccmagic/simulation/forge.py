"""Integração headless com o MTG Forge (Java) via ``subprocess``.

Usa o modo de simulação da linha de comando do Forge:

    java -jar forge-gui-desktop-<versão>-jar-with-dependencies.jar \\
         sim -d <deck_a.dck> <deck_b.dck> -n <jogos>

e extrai o vencedor de cada jogo do ``stdout`` via expressão regular. O Forge
nomeia os jogadores IA como ``Ai(<n>)-<nome do deck>``; por isso gravamos os
decks com nomes-marcadores únicos e verificamos qual marcador aparece na linha
de vitória.

Limitações conhecidas (documentadas para o TCC):
* A CLI do Forge não permite escolher quem começa jogando; ``GameSpec.on_play``
  é ignorado por este motor.
* A IA do Forge não faz sideboarding entre jogos; por isso a orquestração do
  Bo3 é feita em Python (ver ``simulation/bo3.py``), jogando cada fase
  (G1, G2, G3) como um lote de jogos independentes com o deck apropriado.
* Os padrões de regex são configuráveis porque o texto de saída pode variar
  entre versões do Forge.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from tccmagic.cards import Deck, Opponent
from tccmagic.simulation.base import GameSpec, MatchEngine

PLAYER_TAG = "TCCPlayer"
OPPONENT_TAG = "TCCOpponent"


class ForgeError(RuntimeError):
    pass


@dataclass
class ForgeConfig:
    jar_path: str
    # Diretório de instalação do Forge (contém a pasta ``res/``); usado como cwd.
    forge_dir: str | None = None
    java_executable: str = "java"
    java_options: tuple[str, ...] = ("-Xmx4096m", "-Djava.awt.headless=true")
    # Formato passado com ``-f`` (ex.: "Constructed"); None omite a opção.
    game_format: str | None = None
    extra_args: tuple[str, ...] = ()
    timeout_per_game: float = 180.0
    startup_timeout: float = 120.0
    work_dir: str | None = None
    win_pattern: str = r"Game\s+(\d+)\s+ended in\s+\d+\s*ms\.\s*(.+?)\s+has won!"
    draw_pattern: str = r"Game\s+(\d+)\s+ended in a [Dd]raw"
    env: dict[str, str] = field(default_factory=dict)


def parse_forge_output(stdout: str, n_games: int, config: ForgeConfig) -> list[bool]:
    """Converte o ``stdout`` do Forge em uma lista de vitórias do nosso deck.

    Jogos empatados contam como não-vitória. Levanta ``ForgeError`` se o número
    de jogos reconhecidos for diferente do solicitado.
    """
    outcomes: dict[int, bool] = {}
    for match in re.finditer(config.win_pattern, stdout):
        game, winner = int(match.group(1)), match.group(2)
        if PLAYER_TAG in winner:
            outcomes[game] = True
        elif OPPONENT_TAG in winner:
            outcomes[game] = False
        else:
            raise ForgeError(f"Vencedor não reconhecido na saída do Forge: {winner!r}")
    for match in re.finditer(config.draw_pattern, stdout):
        outcomes[int(match.group(1))] = False

    if len(outcomes) != n_games:
        tail = "\n".join(stdout.strip().splitlines()[-20:])
        raise ForgeError(f"Esperados {n_games} resultados, encontrados {len(outcomes)}. Final da saída:\n{tail}")
    return [outcomes[g] for g in sorted(outcomes)]


class ForgeEngine(MatchEngine):
    name = "forge"

    def __init__(self, config: ForgeConfig):
        self.config = config
        if not Path(config.jar_path).is_file():
            raise ForgeError(f"JAR do Forge não encontrado: {config.jar_path}")
        if shutil.which(config.java_executable) is None:
            raise ForgeError(f"Executável Java não encontrado: {config.java_executable}")

    def build_command(self, deck_a: Path, deck_b: Path, n_games: int) -> list[str]:
        cfg = self.config
        cmd = [cfg.java_executable, *cfg.java_options, "-jar", str(Path(cfg.jar_path).resolve()),
               "sim", "-d", str(deck_a), str(deck_b), "-n", str(n_games)]
        if cfg.game_format:
            cmd += ["-f", cfg.game_format]
        return cmd + list(cfg.extra_args)

    def play_games(self, deck: Deck, opponent: Opponent, specs: Sequence[GameSpec]) -> list[bool]:
        if not specs:
            return []
        n_games = len(specs)
        with tempfile.TemporaryDirectory(dir=self.config.work_dir, prefix="forge_") as tmp:
            token = uuid.uuid4().hex[:8]
            deck_a = Path(tmp) / f"{PLAYER_TAG}_{token}.dck"
            deck_b = Path(tmp) / f"{OPPONENT_TAG}_{token}.dck"
            deck_a.write_text(Deck(PLAYER_TAG, deck.cards).to_forge_dck(), encoding="utf-8")
            deck_b.write_text(Deck(OPPONENT_TAG, opponent.deck.cards).to_forge_dck(), encoding="utf-8")

            try:
                proc = subprocess.run(
                    self.build_command(deck_a, deck_b, n_games),
                    cwd=self.config.forge_dir,
                    capture_output=True,
                    text=True,
                    timeout=self.config.startup_timeout + self.config.timeout_per_game * n_games,
                    env={**os.environ, **self.config.env},
                )
            except subprocess.TimeoutExpired as exc:
                raise ForgeError(f"Forge excedeu o tempo limite ({exc.timeout:.0f}s) vs {opponent.name}.") from exc

        if proc.returncode != 0:
            raise ForgeError(f"Forge terminou com código {proc.returncode}:\n{proc.stderr[-2000:]}")
        return parse_forge_output(proc.stdout, n_games, self.config)
