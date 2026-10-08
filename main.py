"""Exemplo executável: otimiza o sideboard de 15 cartas do Boros Energy via BRKGA-A.

Uso:
    python main.py                                   # menu interativo no console
    python main.py --engine surrogate                # simulador substituto, sem menu
    python main.py --generations 100 --workers 4
    python main.py --engine forge --matches 30 --workers 4
    python main.py --engine forge --game1-check 100 --workers 4   # só mede o Game 1
    python main.py --engine forge --compare resultados/resultado.json --validation-matches 300 --workers 4
                                                     # sem busca: compara o sideboard encontrado com outros
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

import numpy as np

from tccmagic.analysis import SwapEffect, metagame_effects
from tccmagic.attributes import ATTRIBUTES
from tccmagic.brkga import BRKGAConfig
from tccmagic.cards import load_database, load_reference_sideboard
from tccmagic.export import export_comparison_json, export_comparison_xlsx, export_json, export_xlsx
from tccmagic.pipeline import (
    VALIDATION_FACTOR,
    ComparisonResult,
    ExperimentConfig,
    ExperimentResult,
    GenerationRecord,
    compare_sideboards,
    measure_game1,
    random_sideboard,
    run_experiment,
)
from tccmagic.simulation import ForgeConfig, SurrogateConfig, wilson_interval

# Instalação local do Forge usada para desenvolvimento/testes neste ambiente.
DEFAULT_FORGE_DIR = r"C:\Users\Enso\Desktop\Artigo TCC\Forge"
DEFAULT_FORGE_JAR = str(Path(DEFAULT_FORGE_DIR) / "forge-gui-desktop-2.0.15-jar-with-dependencies.jar")

# Arquivo de jogos pós-side: fixo, e não dentro de --out, para acumular entre execuções.
DEFAULT_GAMES_DIR = str(Path("resultados") / "jogos")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Otimização de sideboard (MTG Modern) via BRKGA-A")
    p.add_argument("--engine", choices=["surrogate", "forge"], default="surrogate")
    p.add_argument("--generations", type=int, default=40)
    p.add_argument("--population", type=int, default=50)
    p.add_argument("--elite", type=float, default=0.20)
    p.add_argument("--mutants", type=float, default=0.15)
    p.add_argument("--rho", type=float, default=0.70, help="viés do cruzamento para o pai elite")
    p.add_argument("--stall", type=int, default=None, help="parada antecipada após N gerações sem melhora")
    p.add_argument("--matches", type=int, default=100, help="séries Bo3 por oponente em cada avaliação")
    p.add_argument("--validation-matches", type=int, default=None,
                   help=f"séries novas por oponente na validação final (padrão: {VALIDATION_FACTOR} × --matches)")
    p.add_argument("--resample", action=argparse.BooleanOptionalAction, default=None,
                   help="reavaliar a população a cada geração, acumulando séries (padrão: ligado no Forge)")
    p.add_argument("--game1-check", type=int, default=None, metavar="N",
                   help="apenas mede o Game 1: joga N jogos do maindeck contra cada oponente e sai")
    p.add_argument("--compare", default=None, metavar="RESULTADO.json",
                   help="não faz a busca: valida o sideboard final desse resultado contra o de referência, "
                        "sideboards sorteados do pool e a linha de base sem sideboard")
    p.add_argument("--random-sideboards", type=int, default=2, metavar="N",
                   help="sideboards sorteados do pool incluídos em --compare (semente: --seed)")
    p.add_argument("--games-dir", default=DEFAULT_GAMES_DIR,
                   help="pasta do arquivo de jogos pós-side; os jogos de execuções anteriores somam-se à "
                        "análise das trocas ('' desliga)")
    p.add_argument("--max-swaps", type=int, default=5)
    p.add_argument("--plan", choices=["aleatorio", "afinidade"], default="aleatorio",
                   help="plano de troca nos Games 2/3: sorteado (padrão) ou pela tabela de afinidade")
    p.add_argument("--plan-block", type=int, default=10,
                   help="séries consecutivas que compartilham o mesmo sorteio de trocas (plano aleatório)")
    p.add_argument("--plan-seed", type=int, default=2024, help="semente dos sorteios de troca")
    p.add_argument("--copy-penalty", type=float, default=1.0)
    p.add_argument("--workers", type=int, default=1, help="processos paralelos (use >1 com o Forge)")
    p.add_argument("--seed", type=int, default=42, help="semente do BRKGA")
    p.add_argument("--sim-seed", type=int, default=12345, help="semente do simulador substituto")
    p.add_argument("--forge-jar", default=os.environ.get("FORGE_JAR", DEFAULT_FORGE_JAR))
    p.add_argument("--forge-dir", default=os.environ.get("FORGE_DIR", DEFAULT_FORGE_DIR))
    p.add_argument("--out", default="resultados", help="pasta de saída (.json e .xlsx)")
    return p.parse_args(argv)


def print_generation(rec: GenerationRecord) -> None:
    print(
        f"Geração {rec.generation:3d} | melhor={rec.best_fitness:.4f} "
        f"média={rec.mean_fitness:.4f} ±{rec.std_fitness:.4f} | "
        f"Md1={rec.winrate_md1:.3f} Bo3={rec.winrate_bo3:.3f} ΔWR={rec.delta_winrate:+.3f} "
        f"(n={rec.best_n_matches}) | jogos={rec.games_simulated} (+{rec.games_reused} do cache) | "
        f"{rec.elapsed_seconds:6.1f}s"
    )


def print_summary(result: ExperimentResult) -> None:
    best = result.best
    validation = result.validation
    report = validation.sideboard
    base = validation.baseline
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

    print(f"\n{line}\nDESEMPENHO POR CONFRONTO (validação: {validation.n_matches} séries novas por oponente)"
          f"\n{line}")
    if result.config.plan == "aleatorio":
        print("  Trocas sorteadas a cada bloco de séries: 'entram/saem' = cópias médias por série.")
    print(f"  {'Oponente':<16}{'Arq.':<10}{'Md1':>7}{'Bo3':>7}{'Pós-G':>7}{'ΔWR':>8}{'Bo3 s/ side':>13}")
    for m, b in zip(report.matchups, base.matchups):
        print(f"  {m.opponent:<16}{m.archetype:<10}{m.winrate_md1:7.3f}{m.winrate_bo3:7.3f}"
              f"{m.winrate_postboard:7.3f}{m.delta_winrate:+8.3f}{b.winrate_bo3:13.3f}")
        print(f"      entram: {m.cards_in}\n      saem:   {m.cards_out}")

    low, high = validation.gain_interval()
    print(f"\n{line}\nRESUMO (média ponderada pelo metajogo)\n{line}")
    print(f"  Fitness na busca (otimista; n={best.report.n_matches} séries/oponente): {best.fitness:.4f}")
    print(f"  Validação com {validation.n_matches} séries novas por oponente:")
    print(f"  WinRate Md1 (Game 1, pré-side) ......... {report.winrate_md1:.4f}")
    print(f"  WinRate Bo3 (série, pós-side) .......... {report.winrate_bo3:.4f} ± {report.stderr_bo3:.4f}")
    print(f"  ΔWinRate = Bo3 − Md1 ................... {report.delta_winrate:+.4f}")
    print(f"  WinRate Bo3 SEM sideboard (linha base) . {base.winrate_bo3:.4f} ± {base.stderr_bo3:.4f}")
    print(f"  Ganho atribuível ao sideboard .......... {validation.gain:+.4f}  "
          f"(IC 95%: {low:+.4f} a {high:+.4f})")
    if validation.significant:
        print("  → O intervalo de confiança exclui zero: o efeito é distinguível do ruído.")
    else:
        print("  → O intervalo de confiança inclui zero: com estas séries o ganho NÃO é distinguível\n"
              "    do ruído. Aumente --matches / --validation-matches antes de tirar conclusões.")
    print(f"  Gerações: {len(result.history) - 1}  |  tempo total: {result.elapsed_seconds:.1f}s"
          f"{'  |  parada antecipada' if result.stopped_early else ''}")
    total = result.games_simulated + result.games_reused
    if total:
        print(f"  Jogos pós-side: {result.games_simulated} simulados, {result.games_reused} reaproveitados "
              f"do cache ({result.games_reused / total:.0%})")
    print_swap_analysis(result)


def print_swap_analysis(result: ExperimentResult | ComparisonResult) -> None:
    """Efeito estimado de cada carta trocada (só no plano aleatório)."""
    if not result.swap_analysis:
        return
    line = "=" * 78

    def fmt(e: SwapEffect) -> str:
        mark = " *" if e.significant else ""
        return f"{e.card:<30}{e.effect * 100:+7.1f} pp ± {1.96 * e.stderr * 100:4.1f}  ({e.games} jogos){mark}"

    print(f"\n{line}\nEFEITO DAS TROCAS SORTEADAS (todos os jogos pós-side desta execução)\n{line}")
    if result.games_archived:
        print(f"  Inclui também {result.games_archived} jogos de execuções anteriores (arquivo de jogos).")
    print("  entra: ganho por cópia ao colocar a carta no lugar de uma flex qualquer do maindeck\n"
          "  sai:   ganho ao tirar a carta em vez de uma flex qualquer (positivo = faz pouca falta)\n"
          "  ± = metade do IC 95%; * = intervalo exclui zero")
    for a in result.swap_analysis:
        print(f"\n  {a.opponent} ({a.archetype}) — {a.games} jogos, vitória pós-side {a.winrate:.3f}, "
              f"estimada sem trocas {a.no_swap_winrate:.3f}")
        print("    entra:")
        for e in a.role("entra"):
            print(f"      {fmt(e)}")
        outs = a.role("sai")
        if len(outs) > 6:
            print("    sai (as 3 que menos fazem falta e as 3 que mais fazem falta):")
            outs = outs[:3] + outs[-3:]
        else:
            print("    sai:")
        for e in outs:
            print(f"      {fmt(e)}")
    pooled = metagame_effects(result.swap_analysis)
    if pooled:
        print("\n  Metajogo (média ponderada pela participação de cada oponente), entra:")
        for e in pooled:
            print(f"      {fmt(e)}")


def fitness_noise(matches: int, shares: list[float]) -> float:
    """Erro padrão do fitness de uma rodada no pior caso (taxa de vitória de 50%)."""
    total = sum(shares)
    return 0.5 * math.sqrt(sum((s / total) ** 2 for s in shares) / matches)


def print_game1_check(config: ExperimentConfig, n_games: int) -> None:
    line = "=" * 78
    print(f"Medindo o Game 1: {n_games} jogos do maindeck contra cada oponente (motor={config.engine})...")
    results = measure_game1(config, n_games)
    print(f"\n{line}\nGAME 1 — MAINDECK vs. CADA OPONENTE ({n_games} jogos)\n{line}")
    print(f"  {'Oponente':<16}{'Arq.':<10}{'Vitórias':>9}{'Taxa':>8}   IC 95%")
    for opp, wins in results:
        low, high = wilson_interval(wins, n_games)
        print(f"  {opp.name:<16}{opp.archetype:<10}{wins:>9d}{wins / n_games:8.3f}   {low:.3f} a {high:.3f}")
    print("\n  Taxas muito altas ou muito baixas indicam um confronto que a IA do motor não pilota de\n"
          "  forma realista (ex.: decks de combo). Nesses confrontos o sideboard tem pouco espaço para\n"
          "  alterar o resultado, e a otimização tende a não encontrar sinal.")


def print_comparison(result: ComparisonResult) -> None:
    line = "=" * 78
    print(f"\n{line}\nSIDEBOARDS COMPARADOS ({result.n_matches} séries novas por oponente, mesmos Games 1)\n{line}")
    for c in result.candidates:
        print(f"  {c.name:<16} {', '.join(f'{n} {card}' for card, n in c.cards) or '—'}")
    opponents = [m.opponent for m in result.candidates[0].report.matchups]
    print(f"\n  {'WinRate Bo3':<16}{'Metajogo':>10}{'± erro':>8}" + "".join(f"{o[:13]:>15}" for o in opponents))
    for c in result.candidates:
        print(f"  {c.name:<16}{c.report.winrate_bo3:10.3f}{c.report.stderr_bo3:8.3f}"
              + "".join(f"{m.winrate_bo3:15.3f}" for m in c.report.matchups))

    print(f"\n{line}\nDIFERENÇAS DE WINRATE BO3 (pareadas série a série)\n{line}")
    print("  * = o intervalo de 95% exclui zero")
    for c in result.comparisons:
        low, high = c.interval()
        print(f"  {c.candidate:<16} − {c.reference:<16}{c.gain * 100:+7.1f} pp  "
              f"(IC 95%: {low * 100:+.1f} a {high * 100:+.1f}){' *' if c.significant else ''}")
    total = result.games_simulated + result.games_reused
    if total:
        print(f"\n  Jogos pós-side: {result.games_simulated} simulados, {result.games_reused} reaproveitados "
              f"do cache ({result.games_reused / total:.0%})  |  tempo total: {result.elapsed_seconds:.1f}s")
    print_swap_analysis(result)


def run_comparison(config: ExperimentConfig, args: argparse.Namespace) -> None:
    with open(args.compare, encoding="utf-8") as fh:
        optimized = [entry["card"] for entry in json.load(fh)["final"]["sideboard"]]
    sideboards = {"otimizado": optimized, "referencia": load_reference_sideboard()}
    database = load_database()
    rng = np.random.default_rng(args.seed)
    for k in range(1, args.random_sideboards + 1):
        sideboards[f"aleatorio_{k}"] = random_sideboard(database, rng)

    print(f"Comparação de sideboards | motor={config.engine} | séries/oponente={config.n_validation_matches} "
          f"| plano={config.plan} | workers={config.workers}\n")
    result = compare_sideboards(config, sideboards, status=print)
    print_comparison(result)
    out = Path(args.out)
    json_path = export_comparison_json(result, out / "comparacao.json")
    xlsx_path = export_comparison_xlsx(result, out / "comparacao.xlsx")
    print(f"\nArquivos exportados:\n  {json_path}\n  {xlsx_path}")


def save_partial(result: ExperimentResult, path: Path) -> None:
    """Grava o resultado da busca antes da validação final (que pode falhar)."""
    try:
        export_json(result, path)
    except OSError as exc:
        print(f"Aviso: não foi possível gravar o resultado parcial da busca ({exc}).")
    else:
        print(f"Busca concluída; resultado parcial gravado em {path}")


def run(args: argparse.Namespace) -> None:
    forge_config = None
    if args.engine == "forge":
        if not args.forge_jar:
            raise SystemExit("Informe --forge-jar (ou a variável FORGE_JAR) para usar o motor Forge.")
        forge_config = ForgeConfig(jar_path=args.forge_jar, forge_dir=args.forge_dir)

    config = ExperimentConfig(
        engine=args.engine,
        matches_per_opponent=args.matches,
        validation_matches=args.validation_matches,
        resample=args.resample,
        max_swaps=args.max_swaps,
        plan=args.plan,
        plan_block=args.plan_block,
        plan_seed=args.plan_seed,
        copy_penalty=args.copy_penalty,
        workers=args.workers,
        games_dir=args.games_dir or None,
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

    if args.game1_check:
        print_game1_check(config, args.game1_check)
        return
    if args.compare:
        run_comparison(config, args)
        return

    print(f"BRKGA-A | motor={config.engine} | população={args.population} | gerações={args.generations} "
          f"| séries/oponente={args.matches} | validação={config.n_validation_matches} "
          f"| plano={config.plan} | workers={args.workers}")
    if args.engine == "forge":
        noise = fitness_noise(args.matches, [o.meta_share for o in load_database().opponents])
        print(f"Ruído: erro padrão do fitness de até ±{noise:.3f} por rodada de {args.matches} séries/oponente.")
        if args.resample is not False:
            print("Diferenças entre sideboards menores que isso só aparecem com as séries acumuladas pela "
                  "reamostragem dos elites.")
    print()
    out = Path(args.out)
    partial_path = out / "resultado_parcial.json"
    result = run_experiment(config, progress=print_generation, status=print,
                            on_search_done=lambda partial: save_partial(partial, partial_path))
    print_summary(result)

    json_path = export_json(result, out / "resultado.json")
    xlsx_path = export_xlsx(result, out / "resultado.xlsx")
    partial_path.unlink(missing_ok=True)  # substituído pelo resultado completo
    print(f"\nArquivos exportados:\n  {json_path}\n  {xlsx_path}")


# --------------------------------------------------------------------------- #
# Menu interativo (quando o script é chamado sem argumentos)
# --------------------------------------------------------------------------- #

# Tempos medidos no Forge 2.0.15 (execução serial), usados só para a estimativa.
FORGE_STARTUP_SECONDS = 16.0
FORGE_GAME_SECONDS = 3.5


def ask(label: str, default, cast=str, minimum=None, maximum=None):
    """Pergunta um valor no console; Enter mantém o padrão."""
    while True:
        raw = input(f"  {label} [{default}]: ").strip()
        if not raw:
            return default
        try:
            value = cast(raw.replace(",", ".") if cast is float else raw)
        except ValueError:
            print("    Valor inválido, tente novamente.")
            continue
        if (minimum is not None and value < minimum) or (maximum is not None and value > maximum):
            limits = f"entre {minimum} e {maximum}" if maximum is not None else f">= {minimum}"
            print(f"    O valor deve ser {limits}.")
            continue
        return value


def ask_yes_no(label: str, default: bool) -> bool:
    hint = "S/n" if default else "s/N"
    while True:
        raw = input(f"  {label} [{hint}]: ").strip().lower()
        if not raw:
            return default
        if raw in ("s", "sim"):
            return True
        if raw in ("n", "nao", "não"):
            return False


def ask_plan(args: argparse.Namespace) -> None:
    while True:
        raw = input(f"  Plano de troca nos Games 2/3 (aleatorio = sorteia o que entra e o que sai; "
                    f"afinidade = tabela por arquétipo) [{args.plan}]: ").strip().lower()
        if not raw:
            return
        if raw in ("aleatorio", "afinidade"):
            args.plan = raw
            return
        print("    Digite 'aleatorio' ou 'afinidade'.")


def ask_surrogate(args: argparse.Namespace) -> None:
    args.matches = ask("Séries Bo3 por oponente", args.matches, int, 1)
    args.validation_matches = ask("Séries novas por oponente na validação final",
                                  VALIDATION_FACTOR * args.matches, int, 1)
    args.population = ask("Tamanho da população", args.population, int, 3)
    args.generations = ask("Gerações", args.generations, int, 1)
    args.workers = ask("Workers (processos paralelos)", args.workers, int, 1, os.cpu_count() or 1)
    ask_plan(args)
    args.stall = ask("Parada antecipada após N gerações sem melhora (0 = desligado)", 0, int, 0) or None
    args.seed = ask("Semente do BRKGA", args.seed, int)
    args.sim_seed = ask("Semente do simulador substituto", args.sim_seed, int)
    args.out = ask("Pasta de saída", args.out)
    if ask_yes_no("Ajustar parâmetros avançados?", False):
        args.elite = ask("Fração de elite", args.elite, float, 0.01, 0.99)
        args.mutants = ask("Fração de mutantes", args.mutants, float, 0.0, 0.99)
        args.rho = ask("Viés do cruzamento ρ", args.rho, float, 0.5, 1.0)
        args.max_swaps = ask("Máximo de trocas no sideboarding", args.max_swaps, int, 0, 15)
        args.copy_penalty = ask("Penalidade por cópia δ", args.copy_penalty, float, 0.0)


def ask_forge(args: argparse.Namespace) -> None:
    """Parâmetros do Forge, cada um com a explicação do que faz entre parênteses."""
    cpus = os.cpu_count() or 1
    args.matches = ask(
        "Séries Bo3 por oponente (quantas séries melhor-de-3 cada sideboard joga contra cada "
        "oponente a cada rodada; mais séries = taxa de vitória mais precisa, porém mais lento)",
        args.matches, int, 1)
    args.validation_matches = ask(
        "Séries de validação (ao final, o melhor sideboard e a linha de base sem sideboard jogam "
        "esta quantidade de séries novas por oponente; é daí que saem os números do relatório)",
        VALIDATION_FACTOR * args.matches, int, 1)
    args.population = ask(
        "Tamanho da população (quantos sideboards candidatos existem em cada geração; "
        "maior = busca mais ampla, porém mais lento)",
        args.population, int, 3)
    args.generations = ask(
        "Gerações (quantas vezes a população é evoluída; cada geração joga uma rodada nova para "
        "todos os sideboards da população, acumulando as séries dos que sobrevivem)",
        args.generations, int, 1)
    args.workers = ask(
        f"Workers (quantas instâncias do Forge rodam em paralelo; cada uma usa ~1,5 GB de RAM; "
        f"esta máquina tem {cpus} núcleos)",
        args.workers, int, 1, cpus)
    ask_plan(args)
    if args.plan == "aleatorio":
        args.plan_block = ask(
            "Séries por sorteio de trocas (as séries são agrupadas em blocos que usam o mesmo sorteio; "
            "cada deck distinto custa uma inicialização do Forge, ~16 s; menor = mais variedade de trocas, "
            "porém mais lento)",
            args.plan_block, int, 1)
    args.stall = ask(
        "Parada antecipada (encerra se o melhor sideboard não melhorar por N gerações seguidas; "
        "0 = desligado)",
        0, int, 0) or None
    args.seed = ask(
        "Semente do BRKGA (fixa a aleatoriedade do algoritmo; mesma semente = mesma sequência "
        "de populações)",
        args.seed, int)
    args.out = ask("Pasta de saída (onde resultado.json e resultado.xlsx serão gravados)", args.out)
    if ask_yes_no("Ajustar parâmetros avançados (BRKGA e sideboarding)?", False):
        args.elite = ask(
            "Fração de elite (parcela dos melhores sideboards copiada intacta para a próxima geração)",
            args.elite, float, 0.01, 0.99)
        args.mutants = ask(
            "Fração de mutantes (parcela de sideboards aleatórios inseridos a cada geração para "
            "manter a diversidade)",
            args.mutants, float, 0.0, 0.99)
        args.rho = ask(
            "Viés do cruzamento ρ (probabilidade de o filho herdar cada gene do pai elite)",
            args.rho, float, 0.5, 1.0)
        args.max_swaps = ask(
            "Máximo de trocas no sideboarding (quantas cartas podem entrar/sair do deck entre os jogos)",
            args.max_swaps, int, 0, 15)
        args.copy_penalty = ask(
            "Penalidade por cópia δ (reduz o valor de cópias repetidas da mesma carta no ranking)",
            args.copy_penalty, float, 0.0)


def estimate_forge_hours(args: argparse.Namespace, n_opponents: int) -> float:
    """Estimativa grosseira (limite superior: ignora sideboards repetidos na população)."""
    def call(games: float) -> float:
        return FORGE_STARTUP_SECONDS + games * FORGE_GAME_SECONDS

    def game1(n: int) -> float:
        return n_opponents * call(n)

    def postboard(n: int) -> float:
        # G2 + G3 nas séries empatadas (~40%); no plano aleatório, um lote por bloco de séries.
        blocks = math.ceil(n / args.plan_block) if args.plan == "aleatorio" else 1
        g2 = blocks * FORGE_STARTUP_SECONDS + n * FORGE_GAME_SECONDS
        g3 = blocks * FORGE_STARTUP_SECONDS + 0.4 * n * FORGE_GAME_SECONDS
        return n_opponents * (g2 + g3)

    n_elite = max(1, round(args.elite * args.population))
    if args.resample is False:
        rounds = args.population + args.generations * (args.population - n_elite)
    else:  # população inteira a cada geração + rodada final de desempate da elite
        rounds = args.population * (args.generations + 1) + n_elite
    n_val = args.validation_matches or VALIDATION_FACTOR * args.matches
    search = game1(args.matches) + rounds * postboard(args.matches)
    validation = game1(n_val) + 2 * postboard(n_val)  # sideboard escolhido + linha de base
    return (search + validation) / args.workers / 3600


def estimate_comparison_hours(args: argparse.Namespace, n_opponents: int) -> float:
    """Estimativa grosseira de --compare (limite superior: ignora jogos compartilhados pelo cache)."""
    n = args.validation_matches
    blocks = math.ceil(n / args.plan_block) if args.plan == "aleatorio" else 1
    game1 = n_opponents * (FORGE_STARTUP_SECONDS + n * FORGE_GAME_SECONDS)
    # G2 + G3 nas séries empatadas (~40%); a linha de base usa um único deck por oponente.
    with_side = n_opponents * (2 * blocks * FORGE_STARTUP_SECONDS + 1.4 * n * FORGE_GAME_SECONDS)
    baseline = n_opponents * (2 * FORGE_STARTUP_SECONDS + 1.4 * n * FORGE_GAME_SECONDS)
    return (game1 + (2 + args.random_sideboards) * with_side + baseline) / args.workers / 3600


def show_data() -> None:
    db = load_database()
    print(f"\nMaindeck: {db.maindeck.name}")
    for name, count in db.maindeck.counts().items():
        print(f"  {count} {name}")
    print("\nPool de sideboard:")
    for card, max_copies in zip(db.candidates, db.candidate_max_copies):
        print(f"  {card.name} (até {max_copies} cópias)")
    print(f"  → {len(db.sideboard_slots())} vagas para um sideboard de 15 cartas")
    print("\nOponentes:")
    for opp in db.opponents:
        print(f"  {opp.name:<16} {opp.archetype:<10} metajogo {opp.meta_share:.0%}")


def menu() -> argparse.Namespace | None:
    """Retorna os argumentos escolhidos no console, ou None para sair."""
    while True:
        print("\n" + "=" * 64)
        print("  OTIMIZAÇÃO DE SIDEBOARD — BRKGA-A (MTG Modern)")
        print("=" * 64)
        print("  1. Rodar com o simulador substituto (rápido: segundos a minutos)")
        print("  2. Rodar com o Forge (partidas reais da IA do Forge: horas)")
        print("  3. Teste rápido do Forge (só verifica a integração: ~15–25 min)")
        print("  4. Ver dados carregados (maindeck, pool de sideboard, oponentes)")
        print("  5. Medir o Game 1 no Forge (maindeck vs. cada oponente, antes de otimizar)")
        print("  6. Comparar sideboards no Forge (o de um resultado vs. referência, aleatórios e sem side)")
        print("  0. Sair")
        choice = input("\nEscolha uma opção: ").strip()

        args = parse_args([])
        if choice == "0":
            return None
        if choice == "4":
            show_data()
            continue
        if choice == "1":
            print("\nSimulador substituto — Enter mantém o valor entre colchetes.\n")
            ask_surrogate(args)
        elif choice in ("2", "3", "5", "6"):
            args.engine = "forge"
            if not Path(args.forge_jar).is_file():
                print(f"\nJAR do Forge não encontrado: {args.forge_jar}")
                continue
            if choice == "6":
                cpus = os.cpu_count() or 1
                print("\nComparação de sideboards — Enter mantém o valor entre colchetes.\n")
                args.compare = ask("Resultado com o sideboard a comparar",
                                   str(Path("resultados") / "resultado.json"))
                if not Path(args.compare).is_file():
                    print(f"\nArquivo não encontrado: {args.compare}")
                    continue
                args.validation_matches = ask(
                    "Séries novas por oponente (cada sideboard e a linha de base jogam esta quantidade)",
                    300, int, 1)
                args.random_sideboards = ask("Sideboards sorteados do pool incluídos na comparação",
                                             args.random_sideboards, int, 0)
                args.workers = ask(f"Workers (instâncias do Forge em paralelo; esta máquina tem {cpus} núcleos)",
                                   min(4, cpus), int, 1, cpus)
                args.out = ask("Pasta de saída (comparacao.json e comparacao.xlsx)", "resultados_comparacao")
                hours = estimate_comparison_hours(args, len(load_database().opponents))
                print(f"\nTempo estimado: até ~{hours:.1f} h (aproximado; sideboards parecidos compartilham "
                      "jogos pelo cache).\n")
                if ask_yes_no("Iniciar a comparação?", True):
                    return args
                continue
            if choice == "5":
                cpus = os.cpu_count() or 1
                print("\nMedição do Game 1 — Enter mantém o valor entre colchetes.\n")
                args.game1_check = ask("Jogos contra cada oponente", 100, int, 1)
                args.workers = ask(f"Workers (instâncias do Forge em paralelo; esta máquina tem {cpus} núcleos)",
                                   min(4, cpus), int, 1, cpus)
                n_opponents = len(load_database().opponents)
                seconds = n_opponents * (FORGE_STARTUP_SECONDS + args.game1_check * FORGE_GAME_SECONDS)
                print(f"\nTempo estimado: ~{seconds / min(args.workers, n_opponents) / 60:.0f} min.\n")
                if ask_yes_no("Iniciar a medição?", True):
                    return args
                continue
            if choice == "3":
                args.matches, args.population, args.generations = 2, 4, 1
                args.workers, args.out = min(4, os.cpu_count() or 1), "resultados_teste"
                print(f"\nTeste rápido: 2 séries/oponente, população 4, 1 geração, "
                      f"{args.workers} workers, saída em '{args.out}'.\n"
                      "Serve apenas para verificar a integração com o Forge: com tão poucas séries os "
                      "números\nsão ruído e não têm valor estatístico.")
            else:
                args.matches, args.population, args.generations, args.workers = 30, 16, 8, 4
                print("\nForge — Enter mantém o valor entre colchetes.\n")
                ask_forge(args)
            hours = estimate_forge_hours(args, len(load_database().opponents))
            print(f"\nTempo estimado: até ~{hours:.1f} h (aproximado; o cache de jogos de decks "
                  "repetidos costuma reduzir esse valor).")
        else:
            print("Opção inválida.")
            continue

        try:
            BRKGAConfig(population_size=args.population, elite_fraction=args.elite,
                        mutant_fraction=args.mutants, elite_bias=args.rho)
        except ValueError as exc:
            print(f"\nConfiguração inválida: {exc}")
            continue
        print()
        if ask_yes_no("Iniciar a execução?", True):
            return args


if __name__ == "__main__":
    if len(sys.argv) > 1:
        run(parse_args())
    else:
        try:
            chosen = menu()
        except (KeyboardInterrupt, EOFError):
            chosen = None
            print("\nEncerrado.")
        if chosen is not None:
            run(chosen)
