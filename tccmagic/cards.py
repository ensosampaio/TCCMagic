"""Módulo 1 — Banco de dados de cartas, maindeck, pool de sideboard e oponentes.

As estruturas aqui são imutáveis (``frozen``) para que possam ser enviadas com
segurança a processos filhos (``multiprocessing``) e usadas como chave de cache.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, Mapping

import numpy as np

from tccmagic.attributes import ATTRIBUTES, N_ATTRIBUTES, build_vector, vector_from_mapping

DATA_DIR = Path(__file__).resolve().parent / "data"

MAINDECK_SIZE = 60
SIDEBOARD_SIZE = 15
MAX_COPIES = 4  # regra de construção do formato Modern

BASIC_LANDS = frozenset({"Plains", "Island", "Swamp", "Mountain", "Forest", "Wastes"})


@dataclass(frozen=True)
class Card:
    """Uma carta com seu vetor de atributos v(c) ∈ [0, 1]^9."""

    name: str
    cmc: float
    vector: tuple[float, ...] = field(default=(0.0,) * N_ATTRIBUTES)
    is_land: bool = False
    # Para cartas do maindeck: pode ser retirada no sideboarding (Games 2/3)?
    flex: bool = False

    @property
    def v(self) -> np.ndarray:
        return np.asarray(self.vector, dtype=float)

    @classmethod
    def from_json(cls, raw: Mapping) -> "Card":
        is_land = bool(raw.get("land", False))
        cmc = float(raw.get("cmc", 0.0))
        if is_land:
            vector = np.zeros(N_ATTRIBUTES)
        else:
            vector = build_vector(cmc, raw.get("attributes", {}))
        return cls(
            name=raw["name"],
            cmc=cmc,
            vector=tuple(float(x) for x in vector),
            is_land=is_land,
            flex=bool(raw.get("flex", False)),
        )


@dataclass(frozen=True)
class SideboardSlot:
    """Uma entrada do pool decodificável: a k-ésima cópia de uma carta candidata.

    Cópias são entradas distintas, então a seleção Top-15 nunca repete a mesma
    entrada e o número de cópias de uma carta nunca excede o permitido.
    """

    card: Card
    copy_index: int  # 1 = primeira cópia, 2 = segunda, ...

    @property
    def label(self) -> str:
        return f"{self.card.name} #{self.copy_index}"


@dataclass(frozen=True)
class Deck:
    """Lista de cartas com multiplicidade (maindeck de 60 ou deck pós-sideboard)."""

    name: str
    cards: tuple[tuple[Card, int], ...]

    @classmethod
    def from_cards(cls, name: str, cards: Iterable[Card]) -> "Deck":
        """Agrupa uma sequência de cartas (com repetição) em pares (carta, qtd)."""
        order: dict[str, Card] = {}
        counts: Counter[str] = Counter()
        for card in cards:
            order.setdefault(card.name, card)
            counts[card.name] += 1
        return cls(name=name, cards=tuple((order[n], counts[n]) for n in order))

    @property
    def size(self) -> int:
        return sum(count for _, count in self.cards)

    def counts(self) -> Counter[str]:
        return Counter({card.name: count for card, count in self.cards})

    def expanded(self) -> Iterator[Card]:
        """Itera sobre as cartas com repetição (uma entrada por cópia)."""
        for card, count in self.cards:
            for _ in range(count):
                yield card

    def nonland_cards(self) -> list[Card]:
        return [c for c in self.expanded() if not c.is_land]

    def flex_cards(self) -> list[Card]:
        """Cópias do maindeck elegíveis para sair no sideboarding.

        Terrenos nunca saem: a base de mana fica com a mesma quantidade de
        terrenos nos Games 2/3, como no sideboarding real.
        """
        return [c for c in self.expanded() if c.flex and not c.is_land]

    def swap(self, cards_out: Iterable[Card], cards_in: Iterable[Card], name: str | None = None) -> "Deck":
        """Retorna um novo deck com ``cards_out`` removidas e ``cards_in`` adicionadas."""
        remaining = list(self.expanded())
        for card in cards_out:
            for i, current in enumerate(remaining):
                if current.name == card.name:
                    del remaining[i]
                    break
            else:
                raise ValueError(f"Carta '{card.name}' não está no deck '{self.name}'.")
        return Deck.from_cards(name or self.name, [*remaining, *cards_in])

    def to_forge_dck(self, sideboard: Iterable[Card] = ()) -> str:
        """Serializa o deck no formato ``.dck`` usado pelo MTG Forge."""
        lines = ["[metadata]", f"Name={self.name}", "[Main]"]
        lines += [f"{count} {card.name}" for card, count in self.cards]
        side = Deck.from_cards("side", sideboard)
        if side.cards:
            lines.append("[Sideboard]")
            lines += [f"{count} {card.name}" for card, count in side.cards]
        return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class Opponent:
    """Um deck da suíte de oponentes do metajogo."""

    name: str
    archetype: str
    meta_share: float
    deck: Deck
    # Parâmetros usados apenas pelo simulador substituto (ver simulation/surrogate.py)
    base_logit: float = 0.0
    postboard_penalty: float = 0.0
    vulnerability: tuple[float, ...] = field(default=(0.0,) * N_ATTRIBUTES)

    @property
    def vuln(self) -> np.ndarray:
        return np.asarray(self.vulnerability, dtype=float)


@dataclass(frozen=True)
class Database:
    """Tudo o que o otimizador precisa: maindeck fixo, pool, oponentes e afinidades."""

    maindeck: Deck
    candidates: tuple[Card, ...]
    candidate_max_copies: tuple[int, ...]
    opponents: tuple[Opponent, ...]
    archetype_affinity: Mapping[str, tuple[float, ...]]

    def sideboard_slots(self) -> list[SideboardSlot]:
        """Expande o pool em entradas por cópia, respeitando a regra de 4 cópias.

        Ex.: se o maindeck já tem 3 cópias de uma carta, no máximo 1 pode ir
        para o sideboard.
        """
        main_counts = self.maindeck.counts()
        slots: list[SideboardSlot] = []
        for card, max_copies in zip(self.candidates, self.candidate_max_copies):
            allowed = max_copies
            if card.name not in BASIC_LANDS:
                allowed = min(allowed, MAX_COPIES - main_counts.get(card.name, 0))
            slots += [SideboardSlot(card, k) for k in range(1, allowed + 1)]
        return slots

    def affinity(self, archetype: str) -> np.ndarray:
        try:
            return np.asarray(self.archetype_affinity[archetype], dtype=float)
        except KeyError:
            raise KeyError(f"Arquétipo sem tabela de afinidade: '{archetype}'") from None


# --------------------------------------------------------------------------- #
# Carregamento a partir de JSON
# --------------------------------------------------------------------------- #

def _read_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_maindeck(path: Path) -> Deck:
    raw = _read_json(path)
    cards: list[Card] = []
    for entry in raw["cards"]:
        cards += [Card.from_json(entry)] * int(entry["count"])
    deck = Deck.from_cards(raw["name"], cards)
    if deck.size != MAINDECK_SIZE:
        raise ValueError(f"Maindeck '{deck.name}' tem {deck.size} cartas (esperado {MAINDECK_SIZE}).")
    for card, count in deck.cards:
        if card.name not in BASIC_LANDS and count > MAX_COPIES:
            raise ValueError(f"'{card.name}' excede {MAX_COPIES} cópias no maindeck.")
        if card.is_land and card.flex:
            raise ValueError(f"'{card.name}' é terreno e não pode ser 'flex': terrenos não saem no sideboarding.")
    return deck


def load_card_pool(path: Path) -> tuple[tuple[Card, ...], tuple[int, ...]]:
    raw = _read_json(path)
    names = [entry["name"] for entry in raw["cards"]]
    duplicated = {n for n in names if names.count(n) > 1}
    if duplicated:
        raise ValueError(f"Cartas repetidas no pool: {sorted(duplicated)}")
    cards = tuple(Card.from_json(entry) for entry in raw["cards"])
    max_copies = tuple(int(entry.get("max_copies", MAX_COPIES)) for entry in raw["cards"])
    return cards, max_copies


def load_opponents(path: Path) -> tuple[Opponent, ...]:
    raw = _read_json(path)
    opponents = []
    for entry in raw["opponents"]:
        deck_cards: list[Card] = []
        for name, count in entry["decklist"].items():
            deck_cards += [Card(name=name, cmc=0.0)] * int(count)
        deck = Deck.from_cards(entry["name"], deck_cards)
        if deck.size != MAINDECK_SIZE:
            raise ValueError(f"Deck do oponente '{deck.name}' tem {deck.size} cartas.")
        opponents.append(
            Opponent(
                name=entry["name"],
                archetype=entry["archetype"],
                meta_share=float(entry["meta_share"]),
                deck=deck,
                base_logit=float(entry["surrogate"]["base_logit"]),
                postboard_penalty=float(entry["surrogate"]["postboard_penalty"]),
                vulnerability=tuple(vector_from_mapping(entry["surrogate"]["vulnerability"])),
            )
        )
    return tuple(opponents)


def load_archetypes(path: Path) -> dict[str, tuple[float, ...]]:
    raw = _read_json(path)
    return {name: tuple(vector_from_mapping(vec)) for name, vec in raw["affinity"].items()}


def load_database(data_dir: Path = DATA_DIR, maindeck_file: str = "maindeck_boros_energy.json") -> Database:
    maindeck = load_maindeck(data_dir / maindeck_file)
    candidates, max_copies = load_card_pool(data_dir / "sideboard_pool.json")
    opponents = load_opponents(data_dir / "opponents.json")
    affinity = load_archetypes(data_dir / "archetypes.json")

    missing = {o.archetype for o in opponents} - set(affinity)
    if missing:
        raise ValueError(f"Arquétipos sem tabela de afinidade: {sorted(missing)}")
    if not maindeck.flex_cards():
        raise ValueError("O maindeck não tem cartas marcadas como 'flex' para o sideboarding.")

    db = Database(maindeck, candidates, max_copies, opponents, affinity)
    if len(db.sideboard_slots()) < SIDEBOARD_SIZE:
        raise ValueError(f"O pool precisa de pelo menos {SIDEBOARD_SIZE} entradas legais.")
    return db


__all__ = [
    "ATTRIBUTES",
    "BASIC_LANDS",
    "Card",
    "Database",
    "Deck",
    "MAINDECK_SIZE",
    "MAX_COPIES",
    "Opponent",
    "SIDEBOARD_SIZE",
    "SideboardSlot",
    "load_database",
]
