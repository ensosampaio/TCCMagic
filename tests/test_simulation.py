import json
from typing import Sequence

import numpy as np
import pytest

from tccmagic.brkga import BRKGAConfig
from tccmagic.cards import Deck, Opponent, load_database
from tccmagic.decoder import SideboardDecoder
from tccmagic.export import export_json, export_xlsx
from tccmagic.fitness import FitnessEvaluator
from tccmagic.pipeline import ExperimentConfig, run_experiment
from tccmagic.simulation import Bo3Simulator, ForgeConfig, ForgeError, GameSpec, MatchEngine, SurrogateEngine
from tccmagic.simulation.forge import OPPONENT_TAG, PLAYER_TAG, parse_forge_output


@pytest.fixture(scope="module")
def db():
    return load_database()


class ScriptedEngine(MatchEngine):
    """Motor falso: resultado definido apenas pelo número do jogo."""

    def __init__(self, outcome_by_game: dict[int, bool]):
        self.outcome_by_game = outcome_by_game
        self.calls: list[list[GameSpec]] = []

    def play_games(self, deck: Deck, opponent: Opponent, specs: Sequence[GameSpec]) -> list[bool]:
        self.calls.append(list(specs))
        return [self.outcome_by_game[s.game_number] for s in specs]


# --------------------------------------------------------------------------- #
# Orquestração Bo3
# --------------------------------------------------------------------------- #

def test_bo3_plays_game3_only_when_tied_and_scores_matches(db):
    engine = ScriptedEngine({1: True, 2: False, 3: True})
    sim = Bo3Simulator(db, engine, matches_per_opponent=4)
    report = sim.evaluate(())
    for m in report.matchups:
        assert m.winrate_md1 == 1.0 and m.winrate_bo3 == 1.0 and m.winrate_postboard == 0.5
    # G3 é jogado em todas as séries, pois todas ficam 1–1; o perdedor do G2 (nós) começa.
    g3_calls = [c for c in engine.calls if c and c[0].game_number == 3]
    assert all(s.on_play for c in g3_calls for s in c)


def test_bo3_skips_game3_after_two_wins(db):
    engine = ScriptedEngine({1: True, 2: True, 3: False})
    report = Bo3Simulator(db, engine, matches_per_opponent=3).evaluate(())
    assert report.winrate_bo3 == 1.0
    assert not any(c and c[0].game_number == 3 for c in engine.calls)


def test_game1_alternates_play_draw_and_is_computed_once(db):
    engine = ScriptedEngine({1: False, 2: False, 3: False})
    sim = Bo3Simulator(db, engine, matches_per_opponent=4)
    sim.evaluate(())
    sim.evaluate(())
    g1_calls = [c for c in engine.calls if c and c[0].game_number == 1]
    assert len(g1_calls) == len(db.opponents)
    assert [s.on_play for s in g1_calls[0]] == [True, False, True, False]


# --------------------------------------------------------------------------- #
# Simulador substituto
# --------------------------------------------------------------------------- #

def test_surrogate_game1_probability_depends_only_on_base_logit(db):
    engine = SurrogateEngine(db.maindeck)
    engine.config.play_bonus = 0.0
    for opp in db.opponents:
        p = engine.win_probability(db.maindeck, opp, game_number=1, on_play=True)
        assert p == pytest.approx(1 / (1 + np.exp(-opp.base_logit)))


def test_surrogate_rewards_graveyard_hate_against_living_end(db):
    engine = SurrogateEngine(db.maindeck)
    living_end = next(o for o in db.opponents if o.name == "Living End")
    rip = next(c for c in db.candidates if c.name == "Rest in Peace")
    bolt = next(c for c, _ in db.maindeck.cards if c.name == "Lightning Bolt")
    boarded = db.maindeck.swap([bolt] * 3, [rip] * 3)
    assert engine.win_probability(boarded, living_end, 2, True) > engine.win_probability(
        db.maindeck, living_end, 2, True
    )


def test_surrogate_uses_common_random_numbers(db):
    a = Bo3Simulator(db, SurrogateEngine(db.maindeck), matches_per_opponent=30).evaluate(())
    b = Bo3Simulator(db, SurrogateEngine(db.maindeck), matches_per_opponent=30).evaluate(())
    assert a == b


# --------------------------------------------------------------------------- #
# Fitness: cache e paralelismo
# --------------------------------------------------------------------------- #

def test_fitness_cache_and_parallel_evaluation_match_serial(db):
    decoder = SideboardDecoder(db)
    population = np.random.default_rng(3).random((12, 9))

    serial = FitnessEvaluator(decoder, Bo3Simulator(db, SurrogateEngine(db.maindeck), 20))
    f1 = serial(population)
    simulated = serial.simulations
    np.testing.assert_array_equal(serial(population), f1)
    assert serial.simulations == simulated  # tudo veio do cache

    with FitnessEvaluator(decoder, Bo3Simulator(db, SurrogateEngine(db.maindeck), 20), workers=2) as par:
        np.testing.assert_array_equal(par(population), f1)


# --------------------------------------------------------------------------- #
# Forge (apenas parsing / montagem de comando — não requer Java)
# --------------------------------------------------------------------------- #

FORGE_STDOUT = f"""
Simulation mode
Game 1 ended in 51234 ms. Ai(1)-{PLAYER_TAG} has won!
Game 2 ended in 40211 ms. Ai(2)-{OPPONENT_TAG} has won!
Game 3 ended in a Draw! Took 9999 ms.
"""


def test_parse_forge_output():
    cfg = ForgeConfig(jar_path="forge.jar")
    assert parse_forge_output(FORGE_STDOUT, 3, cfg) == [True, False, False]
    with pytest.raises(ForgeError):
        parse_forge_output(FORGE_STDOUT, 4, cfg)


def test_forge_engine_runs_subprocess_and_parses(db, tmp_path):
    """Substitui 'java' por um script que imita a saída do Forge."""
    import stat
    import sys

    from tccmagic.simulation import ForgeEngine

    fake_java = tmp_path / "fake_java"
    fake_java.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        "args = sys.argv[1:]\n"
        "decks = args[args.index('-d') + 1: args.index('-d') + 3]\n"
        "assert all(open(d).read().startswith('[metadata]') for d in decks)\n"
        "n = int(args[args.index('-n') + 1])\n"
        "for g in range(1, n + 1):\n"
        f"    who = '{PLAYER_TAG}' if g % 2 else '{OPPONENT_TAG}'\n"
        "    print(f'Game {g} ended in 10 ms. Ai(1)-{who} has won!')\n"
    )
    fake_java.chmod(fake_java.stat().st_mode | stat.S_IEXEC)
    jar = tmp_path / "forge.jar"
    jar.write_text("")

    engine = ForgeEngine(ForgeConfig(jar_path=str(jar), java_executable=str(fake_java)))
    specs = [GameSpec(m, 1, True) for m in range(4)]
    assert engine.play_games(db.maindeck, db.opponents[0], specs) == [True, False, True, False]


def test_forge_dck_format(db):
    text = db.maindeck.to_forge_dck()
    assert text.startswith("[metadata]\nName=Boros Energy\n[Main]\n")
    assert "4 Ragavan, Nimble Pilferer" in text
    assert sum(int(line.split(" ", 1)[0]) for line in text.splitlines()[3:]) == 60


# --------------------------------------------------------------------------- #
# Pipeline + exportação
# --------------------------------------------------------------------------- #

def test_small_experiment_and_export(tmp_path):
    cfg = ExperimentConfig(matches_per_opponent=20, brkga=BRKGAConfig(population_size=12, generations=3, seed=1))
    result = run_experiment(cfg)
    assert len(result.history) == 4
    assert len(result.best.decoded.slots) == 15
    assert result.best.fitness == max(h.best_fitness for h in result.history)

    data = json.loads(export_json(result, tmp_path / "r.json").read_text(encoding="utf-8"))
    assert len(data["final"]["sideboard"]) == 15 and len(data["history"]) == 4

    from openpyxl import load_workbook

    wb = load_workbook(export_xlsx(result, tmp_path / "r.xlsx"))
    assert wb.sheetnames == ["Geracoes", "Pesos_Finais", "Sideboard", "Matchups", "Resumo"]
    assert wb["Sideboard"].max_row == 16
