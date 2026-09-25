"""Exemplo executável: otimiza o sideboard de 15 cartas do Boros Energy via BRKGA-A.

Uso:
    python main.py                                   # simulador substituto (padrão)
    python main.py --generations 100 --workers 4
    python main.py --engine forge --forge-jar /opt/forge/forge-gui-desktop-...-jar-with-dependencies.jar \\
                   --forge-dir /opt/forge --matches 10 --workers 4
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from tccmagic.attributes import ATTRIBUTES
from tccmagic.brkga import BRKGAConfig
from tccmagic.export import export_json, export_xlsx
from tccmagic.pipeline import ExperimentConfig, ExperimentResult, GenerationRecord, run_experiment
from tccmagic.simulation import ForgeConfig, SurrogateConfig


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Otimização de sideboard (MTG Modern) via BRKGA-A")
    p.add_argument("--engine", choices=["surrogate", "forge"], default="surrogate")
    p.add_argument("--generations", type=int, default=40)
    p.add_argument("--population", type=int, default=50)
    p.add_argument("--elite", type=float, default=0.20)
    p.add_argument("--mutants", type=float, default=0.15)
    p.add_argument("--rho", type=float, default=0.70, help="viés do cruzamento para o pai elite")
    p.add_argument("--stall", type=int, default=None, help="parada antecipada após N gerações sem melhora")
    p.add_argument("--matches", type=int, default=100, help="séries Bo3 por oponente em cada avaliação")
    p.add_argument("--max-swaps", type=int, default=5)
    p.add_argument("--copy-penalty", type=float, default=1.0)
    p.add_argument("--workers", type=int, default=1, help="processos paralelos (use >1 com o Forge)")
    p.add_argument("--seed", type=int, default=42, help="semente do BRKGA")
    p.add_argument("--sim-seed", type=int, default=12345, help="semente do simulador substituto")
    p.add_argument("--forge-jar", default=os.environ.get("FORGE_JAR"))
    p.add_argument("--forge-dir", default=os.environ.get("FORGE_DIR"))
    p.add_argument("--out", default="resultados", help="pasta de saída (.json e .xlsx)")
    return p.parse_args()


def print_generation(rec: GenerationRecord) -> None:
    print(
        f"Geração {rec.generation:3d} | melhor={rec.best_fitness:.4f} "
        f"média={rec.mean_fitness:.4f} ±{rec.std_fitness:.4f} | "
        f"Md1={rec.winrate_md1:.3f} Bo3={rec.winrate_bo3:.3f} ΔWR={rec.delta_winrate:+.3f} | "
        f"sideboards simulados={rec.simulated_sideboards:4d} | {rec.elapsed_seconds:6.1f}s"
    )


def print_summary(result: ExperimentResult) -> None:
    best = result.best
    report = best.report
    base = result.baseline_no_sideboard
    line = "=" * 78

    print(f"\n{line}\nPESOS FINAIS CONVERGIDOS (w_i = 20·k_i − 10)\n{line}")
    for name, key, weight in zip(ATTRIBUTES, result.best_keys, best.decoded.weights):
        bar = "█" * int(round(abs(weight)))
        print(f"  {name:<28} k={key:.3f}  w={weight:+7.3f}  {'+' if weight >= 0 else '-'}{bar}")

    print(f"\n{line}\nSIDEBOARD OTIMIZADO (15 cartas, ordem do ranking)\n{line}")
    for i, (slot, score) in enumerate(zip(best.decoded.slots, best.decoded.scores), start=1):
        print(f"  {i:2d}. {slot.card.name:<32} cópia {slot.copy_index}   Score={score:+7.3f}")
    print("\n  Lista compacta:")
    for name, count in best.decoded.card_counts():
        print(f"    {count} {name}")

    print(f"\n{line}\nDESEMPENHO POR CONFRONTO\n{line}")
    print(f"  {'Oponente':<16}{'Arq.':<10}{'Md1':>7}{'Bo3':>7}{'Pós-G':>7}{'ΔWR':>8}")
    for m in report.matchups:
        print(f"  {m.opponent:<16}{m.archetype:<10}{m.winrate_md1:7.3f}{m.winrate_bo3:7.3f}"
              f"{m.winrate_postboard:7.3f}{m.delta_winrate:+8.3f}")
        print(f"      entram: {m.cards_in}\n      saem:   {m.cards_out}")

    print(f"\n{line}\nRESUMO (média ponderada pelo metajogo)\n{line}")
    print(f"  WinRate Md1 (Game 1, pré-side) ......... {report.winrate_md1:.4f}")
    print(f"  WinRate Bo3 (série, pós-side) .......... {report.winrate_bo3:.4f}")
    print(f"  ΔWinRate = Bo3 − Md1 ................... {report.delta_winrate:+.4f}")
    print(f"  WinRate Bo3 SEM sideboard (linha base) . {base.winrate_bo3:.4f}")
    print(f"  Ganho atribuível ao sideboard .......... {report.winrate_bo3 - base.winrate_bo3:+.4f}")
    print(f"  Gerações: {len(result.history) - 1}  |  tempo total: {result.elapsed_seconds:.1f}s"
          f"{'  |  parada antecipada' if result.stopped_early else ''}")


if __name__ == "__main__":
    args = parse_args()

    forge_config = None
    if args.engine == "forge":
        if not args.forge_jar:
            raise SystemExit("Informe --forge-jar (ou a variável FORGE_JAR) para usar o motor Forge.")
        forge_config = ForgeConfig(jar_path=args.forge_jar, forge_dir=args.forge_dir)

    config = ExperimentConfig(
        engine=args.engine,
        matches_per_opponent=args.matches,
        max_swaps=args.max_swaps,
        copy_penalty=args.copy_penalty,
        workers=args.workers,
        brkga=BRKGAConfig(
            population_size=args.population,
            elite_fraction=args.elite,
            mutant_fraction=args.mutants,
            elite_bias=args.rho,
            generations=args.generations,
            max_stall_generations=args.stall,
            seed=args.seed,
        ),
        surrogate=SurrogateConfig(seed=args.sim_seed),
        forge=forge_config,
    )

    print(f"BRKGA-A | motor={config.engine} | população={args.population} | gerações={args.generations} "
          f"| séries/oponente={args.matches} | workers={args.workers}\n")
    result = run_experiment(config, progress=print_generation)
    print_summary(result)

    out = Path(args.out)
    json_path = export_json(result, out / "resultado.json")
    xlsx_path = export_xlsx(result, out / "resultado.xlsx")
    print(f"\nArquivos exportados:\n  {json_path}\n  {xlsx_path}")
