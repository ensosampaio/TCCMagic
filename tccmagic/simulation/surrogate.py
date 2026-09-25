"""Simulador substituto (surrogate) de partidas, sem dependência do Forge.

Modela cada jogo como um evento de Bernoulli cuja probabilidade depende dos
atributos agregados do deck e das vulnerabilidades do oponente:

    força(deck, opp) = Σ_i vuln_i(opp) · sat_i(deck)

    sat_1  = média de ``eficiencia_mana`` nas cartas não-terreno
    sat_i  = 1 − exp(−Σ_c v_i(c) / κ_i)        (i = 2..9, retornos decrescentes)

    logit P(vitória) = base_logit(opp)
                     + β · [força(deck) − força(maindeck)]
                     ± bônus_de_jogar_primeiro
                     − penalidade_pós_side(opp)       (apenas Games 2 e 3)

Assim, no Game 1 (deck = maindeck) a taxa de vitória depende só de
``base_logit``, e nos Games 2/3 o ganho vem exclusivamente das cartas que o
plano de sideboarding colocou no deck. A saturação κ_i faz com que o 1º
*hate piece* valha mais que o 5º, incentivando sideboards diversificados.

Variância controlada: o sorteio U ~ Uniforme(0,1) de cada jogo é fixado por
(semente, oponente, partida, número do jogo) — *common random numbers*. Dois
sideboards avaliados com a mesma semente enfrentam exatamente a mesma
"sorte", então diferenças de fitness refletem diferenças de probabilidade de
vitória e não ruído, o que estabiliza a seleção do BRKGA.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

from tccmagic.attributes import ATTRIBUTES, N_ATTRIBUTES
from tccmagic.cards import Deck, Opponent
from tccmagic.simulation.base import GameSpec, MatchEngine, stable_id

# κ_i por atributo (índice 0 = eficiência de mana, que usa média e ignora κ).
DEFAULT_SATURATION = {
    "remocao": 6.0,
    "anti_aggro": 6.0,
    "anti_combo": 3.0,
    "anti_cemiterio": 2.0,
    "anti_artefato_encantamento": 2.0,
    "interacao_pilha": 3.0,
    "vantagem_cartas": 10.0,
    "pressao": 15.0,
}


@dataclass
class SurrogateConfig:
    beta: float = 2.0             # sensibilidade do logit à diferença de força
    play_bonus: float = 0.2       # vantagem (em logit) de começar jogando
    seed: int = 12345
    saturation: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_SATURATION))


class SurrogateEngine(MatchEngine):
    name = "surrogate"

    def __init__(self, maindeck: Deck, config: SurrogateConfig | None = None):
        self.config = config or SurrogateConfig()
        self._kappa = np.array([np.nan] + [self.config.saturation[a] for a in ATTRIBUTES[1:]])
        self._main_features = self.deck_features(maindeck)
        self._uniform_cache: dict[tuple[int, int], np.ndarray] = {}

    # ------------------------------------------------------------------ #
    def deck_features(self, deck: Deck) -> np.ndarray:
        """Vetor sat(deck) ∈ [0,1]^9 dos atributos agregados do deck."""
        nonland = deck.nonland_cards()
        if not nonland:
            return np.zeros(N_ATTRIBUTES)
        matrix = np.vstack([c.v for c in nonland])
        features = np.empty(N_ATTRIBUTES)
        features[0] = matrix[:, 0].mean()
        features[1:] = 1.0 - np.exp(-matrix[:, 1:].sum(axis=0) / self._kappa[1:])
        return features

    def strength(self, features: np.ndarray, opponent: Opponent) -> float:
        return float(opponent.vuln @ features)

    def win_probability(self, deck: Deck, opponent: Opponent, game_number: int, on_play: bool) -> float:
        return self._probability(self.deck_features(deck), opponent, game_number, on_play)

    def _probability(self, features: np.ndarray, opponent: Opponent, game_number: int, on_play: bool) -> float:
        cfg = self.config
        delta = self.strength(features, opponent) - self.strength(self._main_features, opponent)
        logit = opponent.base_logit + cfg.beta * delta + (cfg.play_bonus if on_play else -cfg.play_bonus)
        if game_number > 1:
            logit -= opponent.postboard_penalty
        return float(1.0 / (1.0 + np.exp(-logit)))

    def _uniforms(self, opponent: Opponent, match_index: int) -> np.ndarray:
        key = (stable_id(opponent.name), match_index)
        if key not in self._uniform_cache:
            rng = np.random.default_rng([self.config.seed, key[0], match_index])
            self._uniform_cache[key] = rng.random(3)
        return self._uniform_cache[key]

    # ------------------------------------------------------------------ #
    def play_games(self, deck: Deck, opponent: Opponent, specs: Sequence[GameSpec]) -> list[bool]:
        features = self.deck_features(deck)
        results = []
        for spec in specs:
            p = self._probability(features, opponent, spec.game_number, spec.on_play)
            u = self._uniforms(opponent, spec.match_index)[spec.game_number - 1]
            results.append(bool(u < p))
        return results
