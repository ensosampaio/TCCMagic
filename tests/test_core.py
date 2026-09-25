from collections import Counter

import numpy as np
import pytest

from tccmagic.attributes import ATTRIBUTES, N_ATTRIBUTES, build_vector, mana_efficiency
from tccmagic.brkga import BRKGA_Optimizer, BRKGAConfig
from tccmagic.cards import BASIC_LANDS, MAX_COPIES, SIDEBOARD_SIZE, load_database
from tccmagic.decoder import SideboardDecoder, keys_to_weights
from tccmagic.sideboarding import build_sideboard_plan


@pytest.fixture(scope="module")
def db():
    return load_database()


# --------------------------------------------------------------------------- #
# Atributos e banco de dados
# --------------------------------------------------------------------------- #

def test_mana_efficiency_is_linear_and_clipped():
    assert mana_efficiency(0) == 1.0
    assert mana_efficiency(3) == pytest.approx(0.5)
    assert mana_efficiency(9) == 0.0


def test_build_vector_rejects_unknown_and_out_of_range():
    with pytest.raises(ValueError):
        build_vector(1, {"remocoa": 1.0})
    with pytest.raises(ValueError):
        build_vector(1, {"remocao": 1.5})
    with pytest.raises(ValueError):
        build_vector(1, {"eficiencia_mana": 0.3})


def test_database_decks_are_legal(db):
    assert db.maindeck.size == 60
    for opp in db.opponents:
        assert opp.deck.size == 60
    assert sum(o.meta_share for o in db.opponents) == pytest.approx(1.0)


def test_sideboard_slots_respect_four_copy_rule(db):
    main = db.maindeck.counts()
    per_card = Counter(slot.card.name for slot in db.sideboard_slots())
    for name, n in per_card.items():
        if name not in BASIC_LANDS:
            assert n + main.get(name, 0) <= MAX_COPIES
    assert per_card["Seasoned Pyromancer"] == 1  # 3 no maindeck


# --------------------------------------------------------------------------- #
# Decodificador
# --------------------------------------------------------------------------- #

def test_keys_to_weights_maps_unit_interval_to_plus_minus_ten():
    np.testing.assert_allclose(keys_to_weights(np.array([0.0] * 9)), -10.0)
    np.testing.assert_allclose(keys_to_weights(np.array([1.0] * 9)), 10.0)
    np.testing.assert_allclose(keys_to_weights(np.array([0.5] * 9)), 0.0)
    with pytest.raises(ValueError):
        keys_to_weights(np.zeros(8))


def test_decode_returns_fifteen_legal_unique_slots(db):
    decoder = SideboardDecoder(db)
    rng = np.random.default_rng(0)
    main = db.maindeck.counts()
    for _ in range(200):
        decoded = decoder.decode(rng.random(N_ATTRIBUTES))
        assert len(decoded.slots) == SIDEBOARD_SIZE
        assert len(set(decoded.slots)) == SIDEBOARD_SIZE
        assert list(decoded.scores) == sorted(decoded.scores, reverse=True)
        for name, n in Counter(c.name for c in decoded.cards).items():
            assert n + main.get(name, 0) <= MAX_COPIES


def test_decode_is_deterministic_and_matches_score_formula(db):
    decoder = SideboardDecoder(db, copy_penalty=0.0)
    keys = np.random.default_rng(1).random(N_ATTRIBUTES)
    a, b = decoder.decode(keys), decoder.decode(keys)
    assert a == b
    weights = keys_to_weights(keys)
    for slot, score in zip(a.slots, a.scores):
        assert score == pytest.approx(float(weights @ slot.card.v))


def test_copy_penalty_never_ranks_later_copy_first(db):
    decoder = SideboardDecoder(db, copy_penalty=1.0)
    for keys in np.random.default_rng(2).random((100, N_ATTRIBUTES)):
        seen: dict[str, int] = {}
        for slot in decoder.decode(keys).slots:
            assert slot.copy_index == seen.get(slot.card.name, 0) + 1
            seen[slot.card.name] = slot.copy_index


def test_graveyard_weight_selects_graveyard_hate(db):
    keys = np.full(N_ATTRIBUTES, 0.5)  # todos os pesos 0...
    keys[ATTRIBUTES.index("anti_cemiterio")] = 1.0  # ...exceto anti_cemiterio = +10
    names = {c.name for c in SideboardDecoder(db).decode(keys).cards}
    assert {"Rest in Peace", "Relic of Progenitus", "Tormod's Crypt"} <= names


# --------------------------------------------------------------------------- #
# BRKGA
# --------------------------------------------------------------------------- #

def test_population_partition_matches_specification():
    cfg = BRKGAConfig(population_size=100)
    assert (cfg.n_elite, cfg.n_mutants, cfg.n_offspring) == (20, 15, 65)


def test_crossover_is_biased_towards_elite_parent():
    opt = BRKGA_Optimizer(1000, lambda pop: pop.sum(axis=1), BRKGAConfig(seed=0))
    elite, other = np.ones((1, 1000)), np.zeros((1, 1000))
    child = opt.crossover(elite, other, 1)
    assert child.mean() == pytest.approx(0.70, abs=0.05)


def test_brkga_is_elitist_reproducible_and_optimizes():
    target = np.linspace(0.1, 0.9, N_ATTRIBUTES)

    def fitness(pop):
        return -np.abs(pop - target).sum(axis=1)

    cfg = BRKGAConfig(population_size=40, generations=60, seed=7)
    r1 = BRKGA_Optimizer(N_ATTRIBUTES, fitness, cfg).run()
    r2 = BRKGA_Optimizer(N_ATTRIBUTES, fitness, cfg).run()
    best = [h.best_fitness for h in r1.history]
    assert all(b2 >= b1 for b1, b2 in zip(best, best[1:]))
    np.testing.assert_array_equal(r1.best_keys, r2.best_keys)
    assert r1.best_fitness > -0.3


def test_brkga_stops_early_on_stall():
    cfg = BRKGAConfig(population_size=10, generations=100, max_stall_generations=3, seed=0)
    result = BRKGA_Optimizer(N_ATTRIBUTES, lambda pop: np.zeros(len(pop)), cfg).run()
    assert result.stopped_early and len(result.history) == 4


# --------------------------------------------------------------------------- #
# Plano de sideboarding
# --------------------------------------------------------------------------- #

def test_sideboard_plan_boards_in_graveyard_hate_against_combo(db):
    side = [c for c in db.candidates if c.name in {"Rest in Peace", "Anger of the Gods"}] * 2
    plan = build_sideboard_plan(db.maindeck, side, "combo", db.affinity("combo"), max_swaps=5)
    assert {c.name for c in plan.cards_in} == {"Rest in Peace"}
    assert plan.deck.size == 60
    assert all(c.flex for c in plan.cards_out)


def test_sideboard_plan_respects_max_swaps(db):
    plan = build_sideboard_plan(db.maindeck, list(db.candidates), "combo", db.affinity("combo"), max_swaps=3)
    assert plan.n_swaps <= 3 and plan.deck.size == 60
