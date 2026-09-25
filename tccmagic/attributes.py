"""Definição dos 9 atributos que vetorizam cada carta (codificação BRKGA-A).

Cada carta c é representada por um vetor v(c) ∈ [0, 1]^9. O cromossomo do
BRKGA tem exatamente um gene (chave aleatória) por atributo, de modo que o
algoritmo aprende *o quanto cada atributo vale* e não *quais IDs de carta*
escolher.

O atributo 1 (eficiência de mana) é derivado automaticamente do custo de mana
convertido (CMC); os demais 8 são anotados manualmente no banco de cartas
(``tccmagic/data/*.json``).
"""

from __future__ import annotations

from typing import Mapping

import numpy as np

# Ordem canônica dos atributos: o índice i aqui é o índice do gene i no
# cromossomo e do peso w_i no decodificador.
ATTRIBUTES: tuple[str, ...] = (
    "eficiencia_mana",             # 1 - custo baixo (derivado do CMC)
    "remocao",                     # 2 - remoção pontual de criaturas/permanentes
    "anti_aggro",                  # 3 - ganho de vida, sweepers, bloqueadores
    "anti_combo",                  # 4 - hate pieces, taxação, descarte
    "anti_cemiterio",              # 5 - exílio de cemitério
    "anti_artefato_encantamento",  # 6 - destruição de artefatos/encantamentos
    "interacao_pilha",             # 7 - counterspells e interação na pilha
    "vantagem_cartas",             # 8 - geração de valor / card advantage
    "pressao",                     # 9 - ameaça / clock
)

N_ATTRIBUTES: int = len(ATTRIBUTES)

# CMC a partir do qual a eficiência de mana é considerada nula.
MAX_CMC_FOR_EFFICIENCY: float = 6.0


def mana_efficiency(cmc: float) -> float:
    """Atributo 1: 1 para custo 0, decrescendo linearmente até 0 em CMC 6."""
    return float(np.clip(1.0 - cmc / MAX_CMC_FOR_EFFICIENCY, 0.0, 1.0))


def build_vector(cmc: float, annotated: Mapping[str, float]) -> np.ndarray:
    """Monta o vetor v(c) de 9 posições a partir do CMC e dos atributos anotados.

    Atributos ausentes em ``annotated`` valem 0. Nomes desconhecidos geram erro,
    para que erros de digitação no banco de dados não passem despercebidos.
    """
    unknown = set(annotated) - set(ATTRIBUTES)
    if unknown:
        raise ValueError(f"Atributos desconhecidos: {sorted(unknown)}")
    if "eficiencia_mana" in annotated:
        raise ValueError("'eficiencia_mana' é derivado do CMC; não o anote manualmente.")

    vector = np.zeros(N_ATTRIBUTES, dtype=float)
    vector[0] = mana_efficiency(cmc)
    for i, name in enumerate(ATTRIBUTES[1:], start=1):
        value = float(annotated.get(name, 0.0))
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"Atributo '{name}' fora de [0, 1]: {value}")
        vector[i] = value
    return vector


def vector_from_mapping(mapping: Mapping[str, float]) -> np.ndarray:
    """Converte um dicionário {atributo: valor} (todos os 9) em vetor ordenado."""
    missing = set(ATTRIBUTES) - set(mapping)
    unknown = set(mapping) - set(ATTRIBUTES)
    if missing or unknown:
        raise ValueError(f"Vetor inválido. Faltando: {sorted(missing)}; desconhecidos: {sorted(unknown)}")
    return np.array([float(mapping[name]) for name in ATTRIBUTES], dtype=float)
