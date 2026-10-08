"""Gráficos para a análise dos resultados (a partir de resultado.json e, se existir, comparacao.json).

Uso:
    python estatistica.py                                  # lê resultados/ e grava em resultados/graficos/
    python estatistica.py --resultado outra/resultado.json --saida figuras --formato pdf
    python estatistica.py --comparacao resultados_comparacao/comparacao.json
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # só grava arquivos; não abre janela
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.ticker import FuncFormatter, MaxNLocator

from tccmagic.attributes import ATTRIBUTES
from tccmagic.simulation import wilson_interval

Z95 = 1.96

# Cores: duas séries categóricas (seguras para daltonismo) e um par divergente com meio neutro.
BLUE, ORANGE, RED = "#2a78d6", "#eb6834", "#e34948"
INK, INK_2, MUTED, GRID, AXIS = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
DIVERGING = LinearSegmentedColormap.from_list("vermelho_azul", [RED, "#f0efec", BLUE])

plt.rcParams.update({
    "font.family": ["Segoe UI", "DejaVu Sans"],
    "font.size": 10,
    "text.color": INK,
    "axes.titlesize": 12,
    "axes.titleweight": "bold",
    "axes.titlelocation": "left",
    "axes.titlepad": 12,
    "axes.labelcolor": INK_2,
    "axes.edgecolor": AXIS,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.axisbelow": True,
    "axes.grid": True,
    "grid.color": GRID,
    "grid.linewidth": 0.8,
    "xtick.color": INK_2,
    "ytick.color": INK_2,
    "xtick.major.size": 0,
    "ytick.major.size": 0,
    "legend.frameon": False,
    "figure.facecolor": "white",
    "savefig.facecolor": "white",
    "savefig.bbox": "tight",
    "savefig.dpi": 200,
})


def num(value: float, decimals: int = 1) -> str:
    """Número com vírgula decimal."""
    return f"{value:.{decimals}f}".replace(".", ",")


def signed(value: float, decimals: int = 1) -> str:
    """Número com sinal explícito; o que arredonda para zero fica sem sinal."""
    text = num(abs(value), decimals)
    if not float(text.replace(",", ".")):
        return text
    return ("+" if value > 0 else "−") + text


# Fundo branco para rótulos que cruzam linhas de referência.
LABEL_BOX = {"facecolor": "white", "edgecolor": "none", "pad": 0.6}


PERCENT = FuncFormatter(lambda v, _: f"{num(v, 0)}%")
POINTS = FuncFormatter(lambda v, _: signed(v, 0) if v else "0")


def attribute_label(name: str) -> str:
    return name.replace("_", " ")


def agresti_coull_stderr(wins: int, n: int) -> float:
    """Erro padrão de uma proporção, com o mesmo ajuste usado em EvaluationReport.stderr_bo3."""
    p = (wins + 2) / (n + 4)
    return math.sqrt(p * (1 - p) / (n + 4))


def forest(ax, labels: list[str], values: list[float], intervals: list[tuple[float, float]],
           significant: list[bool]) -> None:
    """Pontos com IC de 95% em pontos percentuais; marcador cheio = o intervalo exclui zero."""
    ys = np.arange(len(labels))[::-1]
    for y, value, (low, high), sig in zip(ys, values, intervals, significant):
        ax.plot([low * 100, high * 100], [y, y], color=BLUE, linewidth=2, solid_capstyle="round")
        ax.plot(value * 100, y, "o", markersize=8, color=BLUE, markerfacecolor=BLUE if sig else "white",
                markeredgewidth=2)
        ax.annotate(signed(value * 100), (value * 100, y), xytext=(0, 9), textcoords="offset points",
                    ha="center", fontsize=9, color=INK_2, bbox=LABEL_BOX)
    ax.axvline(0, color=INK_2, linewidth=1, zorder=0)
    ax.set_yticks(ys, labels)
    ax.set_ylim(-0.6, len(labels) - 0.3)
    ax.xaxis.set_major_formatter(POINTS)
    ax.grid(axis="y", visible=False)
    handles = [plt.Line2D([], [], marker="o", color=BLUE, markerfacecolor=face, markeredgewidth=2,
                          markersize=8, linewidth=2) for face in (BLUE, "white")]
    ax.legend(handles, ["IC 95% exclui zero", "IC 95% inclui zero"], loc="upper center",
              bbox_to_anchor=(0.5, -0.16), ncols=2)


# --------------------------------------------------------------------------- #
# Busca (history / final)
# --------------------------------------------------------------------------- #

def plot_convergence(data: dict):
    history = data["history"]
    gens = [h["generation"] for h in history]
    best = np.array([h["best_fitness"] for h in history]) * 100
    mean = np.array([h["mean_fitness"] for h in history]) * 100
    std = np.array([h["std_fitness"] for h in history]) * 100

    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.fill_between(gens, mean - std, mean + std, color=ORANGE, alpha=0.15, linewidth=0)
    ax.plot(gens, mean, color=ORANGE, linewidth=2, marker="o", markersize=5, label="Média da população (± 1 desvio)")
    ax.plot(gens, best, color=BLUE, linewidth=2, marker="o", markersize=5, label="Melhor indivíduo")
    validation = data.get("validation")
    if validation:
        for key, text in (("sideboard", "validação"), ("baseline_no_sideboard", "sem sideboard")):
            value = validation[key]["winrate_bo3"] * 100
            ax.axhline(value, color=INK_2, linewidth=1, linestyle=(0, (4, 3)))
            ax.annotate(f"{text}: {num(value)}%", (1, value), xycoords=("axes fraction", "data"),
                        xytext=(6, 0), textcoords="offset points", va="center", fontsize=9, color=INK_2)
    ax.set_title("Convergência do BRKGA: fitness (WinRate Bo3) por geração")
    ax.set_xlabel("Geração (0 = população inicial)")
    ax.set_ylabel("WinRate Bo3 estimada na busca")
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax.yaxis.set_major_formatter(PERCENT)
    ax.grid(axis="x", visible=False)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.16), ncols=2)
    return fig


def plot_weight_evolution(data: dict):
    history = data["history"]
    matrix = np.array([[h["weights"][a] for h in history] for a in ATTRIBUTES])

    fig, ax = plt.subplots(figsize=(1.6 + 0.75 * len(history), 4.8))
    image = ax.imshow(matrix, cmap=DIVERGING, vmin=-10, vmax=10, aspect="auto")
    for (row, col), value in np.ndenumerate(matrix):
        ax.text(col, row, signed(value), ha="center", va="center", fontsize=8, color=INK)
    ax.set_xticks(range(len(history)), [h["generation"] for h in history])
    ax.set_yticks(range(len(ATTRIBUTES)), [attribute_label(a) for a in ATTRIBUTES])
    ax.set_xticks(np.arange(-0.5, len(history)), minor=True)
    ax.set_yticks(np.arange(-0.5, len(ATTRIBUTES)), minor=True)
    ax.grid(visible=False)
    ax.grid(which="minor", color="white", linewidth=2)
    ax.tick_params(which="minor", length=0)
    ax.spines[:].set_visible(False)
    ax.set_title("Pesos do melhor indivíduo a cada geração")
    ax.set_xlabel("Geração")
    fig.colorbar(image, ax=ax, label="Peso (−10 a +10)", format=POINTS, fraction=0.04, pad=0.02).outline.set_visible(False)
    return fig


def plot_final_weights(data: dict):
    weights = sorted(data["final"]["weights"].items(), key=lambda item: item[1])
    names = [attribute_label(a) for a, _ in weights]
    values = [w for _, w in weights]

    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    ax.barh(names, values, height=0.6, color=[BLUE if v >= 0 else RED for v in values])
    for y, value in enumerate(values):
        ax.annotate(signed(value, 2), (value, y), xytext=(4 if value >= 0 else -4, 0),
                    textcoords="offset points", va="center", ha="left" if value >= 0 else "right",
                    fontsize=9, color=INK_2)
    ax.axvline(0, color=INK_2, linewidth=1)
    ax.set_xlim(-11.5, 11.5)
    ax.set_title("Pesos finais dos atributos (melhor indivíduo)")
    ax.set_xlabel("Peso  (negativo = o atributo penaliza a carta; positivo = favorece)")
    ax.grid(axis="y", visible=False)
    return fig


def plot_sideboard(data: dict):
    """Score de cada carta escolhida (a cópia mais bem colocada), com o número de cópias."""
    cards: dict[str, list[float]] = {}
    for slot in data["final"]["sideboard"]:
        cards.setdefault(slot["card"], []).append(slot["score"])
    ordered = sorted(cards.items(), key=lambda item: max(item[1]))
    names = [f"{len(scores)}× {card}" for card, scores in ordered]
    top = [max(scores) for _, scores in ordered]

    fig, ax = plt.subplots(figsize=(7.5, 0.42 * len(names) + 1.4))
    ax.barh(names, top, height=0.6, color=BLUE)
    for y, value in enumerate(top):
        ax.annotate(signed(value, 2), (max(value, 0), y), xytext=(4, 0), textcoords="offset points",
                    va="center", fontsize=9, color=INK_2)
    ax.set_title("Sideboard otimizado: cópias e score da melhor cópia de cada carta")
    ax.set_xlabel("Score no ranking do decodificador")
    ax.margins(x=0.1)
    ax.grid(axis="y", visible=False)
    return fig


def plot_games(data: dict):
    history = data["history"]
    gens = [h["generation"] for h in history]
    simulated = np.array([h["games_simulated"] for h in history])
    reused = np.array([h["games_reused"] for h in history])

    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.bar(gens, simulated, width=0.6, color=BLUE, edgecolor="white", linewidth=1.5, label="Simulados no motor")
    ax.bar(gens, reused, width=0.6, bottom=simulated, color=ORANGE, edgecolor="white", linewidth=1.5,
           label="Reaproveitados do cache")
    share = reused[-1] / (simulated[-1] + reused[-1])
    ax.annotate(f"{num(share * 100, 0)}% do cache", (gens[-1], simulated[-1] + reused[-1]), xytext=(0, 5),
                textcoords="offset points", ha="center", fontsize=9, color=INK_2)
    ax.set_title("Jogos pós-side acumulados durante a busca")
    ax.set_xlabel("Geração (0 = população inicial)")
    ax.set_ylabel("Jogos acumulados")
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}".replace(",", ".")))
    ax.grid(axis="x", visible=False)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.16), ncols=2)
    return fig


# --------------------------------------------------------------------------- #
# Validação (séries novas)
# --------------------------------------------------------------------------- #

def plot_validation_matchups(data: dict):
    validation = data["validation"]
    side, base = validation["sideboard"], validation["baseline_no_sideboard"]
    labels = [f"{m['opponent']}\n{m['archetype']} · {num(m['meta_share'] * 100, 0)}%" for m in side["matchups"]]
    labels.append("Metajogo\n(média ponderada)")
    xs = np.arange(len(labels))

    fig, ax = plt.subplots(figsize=(9, 4.8))
    for offset, report, color, label in ((-0.2, base, ORANGE, "Sem sideboard"), (0.2, side, BLUE, "Com sideboard")):
        rates = [m["winrate_bo3"] for m in report["matchups"]] + [report["winrate_bo3"]]
        bounds = [wilson_interval(m["match_wins"], m["n_matches"]) for m in report["matchups"]]
        bounds.append((report["winrate_bo3"] - Z95 * report["stderr_bo3"],
                       report["winrate_bo3"] + Z95 * report["stderr_bo3"]))
        rates = np.array(rates) * 100
        low, high = np.array(bounds).T * 100
        ax.bar(xs + offset, rates, width=0.36, color=color, label=label)
        ax.errorbar(xs + offset, rates, yerr=[rates - low, high - rates], fmt="none", ecolor=INK_2,
                    elinewidth=1.2, capsize=3)
        for x, rate, top in zip(xs + offset, rates, high):
            ax.annotate(num(rate), (x, top), xytext=(0, 3), textcoords="offset points", ha="center",
                        fontsize=8.5, color=INK_2, bbox=LABEL_BOX)
    ax.axhline(50, color=INK_2, linewidth=1, linestyle=(0, (4, 3)), zorder=0.5)
    ax.axvline(len(labels) - 1.5, color=AXIS, linewidth=1)
    ax.set_xticks(xs, labels)
    ax.set_ylim(0, 100)
    ax.yaxis.set_major_formatter(PERCENT)
    ax.set_title(f"Validação: WinRate Bo3 por confronto ({validation['n_matches']} séries novas por oponente)")
    ax.set_ylabel("WinRate Bo3 (barras de erro: IC 95%)")
    ax.grid(axis="x", visible=False)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.18), ncols=2)
    return fig


def plot_gain(data: dict):
    validation = data["validation"]
    labels, gains, intervals = [], [], []
    for m, b in zip(validation["sideboard"]["matchups"], validation["baseline_no_sideboard"]["matchups"]):
        gain = m["winrate_bo3"] - b["winrate_bo3"]
        # conservador, como ValidationResult.gain_stderr: ignora os Games 1 compartilhados
        stderr = math.hypot(agresti_coull_stderr(m["match_wins"], m["n_matches"]),
                            agresti_coull_stderr(b["match_wins"], b["n_matches"]))
        labels.append(m["opponent"])
        gains.append(gain)
        intervals.append((gain - Z95 * stderr, gain + Z95 * stderr))
    labels.append("Metajogo")
    gains.append(validation["gain"])
    intervals.append(tuple(validation["gain_ci95"]))

    fig, ax = plt.subplots(figsize=(8, 4.2))
    forest(ax, labels, gains, intervals, [low > 0 or high < 0 for low, high in intervals])
    ax.axhline(0.5, color=AXIS, linewidth=1)
    ax.set_title("Ganho atribuível ao sideboard (Bo3 com sideboard − Bo3 sem sideboard)")
    ax.set_xlabel("Ganho em pontos percentuais (IC 95%)")
    return fig


def plot_md1_bo3(data: dict):
    report = data["validation"]["sideboard"]
    rows = [(m["opponent"], m["winrate_md1"], m["winrate_bo3"]) for m in report["matchups"]]
    rows.append(("Metajogo", report["winrate_md1"], report["winrate_bo3"]))
    ys = np.arange(len(rows))[::-1]

    fig, ax = plt.subplots(figsize=(8, 4.2))
    for y, (_, md1, bo3) in zip(ys, rows):
        ax.plot([md1 * 100, bo3 * 100], [y, y], color=AXIS, linewidth=2, zorder=1)
        ax.annotate(f"ΔWR {signed((bo3 - md1) * 100)}", (max(md1, bo3) * 100, y), xytext=(10, 0),
                    textcoords="offset points", va="center", fontsize=9, color=INK_2, bbox=LABEL_BOX)
    ax.scatter([r[1] * 100 for r in rows], ys, s=70, color=ORANGE, edgecolor="white", linewidth=1.5,
               label="Md1 (Game 1, pré-side)", zorder=2)
    ax.scatter([r[2] * 100 for r in rows], ys, s=70, color=BLUE, edgecolor="white", linewidth=1.5,
               label="Bo3 (série, pós-side)", zorder=3)
    ax.axvline(50, color=INK_2, linewidth=1, linestyle=(0, (4, 3)), zorder=0)
    ax.axhline(0.5, color=AXIS, linewidth=1)
    ax.set_yticks(ys, [r[0] for r in rows])
    ax.set_ylim(-0.6, len(rows) - 0.4)
    ax.margins(x=0.15)
    ax.xaxis.set_major_formatter(PERCENT)
    ax.set_title("Validação: do Game 1 à série (ΔWinRate = Bo3 − Md1, com sideboard)")
    ax.set_xlabel("Taxa de vitória")
    ax.grid(axis="y", visible=False)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.16), ncols=2)
    return fig


# --------------------------------------------------------------------------- #
# Efeito das trocas (plano aleatório)
# --------------------------------------------------------------------------- #

def plot_metagame_effects(data: dict):
    effects = data["swap_analysis"]["metagame"]
    games = sum(a["games"] for a in data["swap_analysis"]["opponents"])

    fig, ax = plt.subplots(figsize=(8, 0.45 * len(effects) + 1.8))
    forest(ax, [e["card"] for e in effects], [e["effect"] for e in effects],
           [tuple(e["ci95"]) for e in effects], [e["significant"] for e in effects])
    ax.set_title(f"Efeito por cópia de cada carta que entra, no metajogo ({games} jogos pós-side)")
    ax.set_xlabel("Efeito na taxa de vitória pós-side, em pontos percentuais (IC 95%)")
    return fig


def plot_swap_heatmap(data: dict, role: str):
    opponents = data["swap_analysis"]["opponents"]
    table = {(e["card"], a["opponent"]): e for a in opponents for e in a["effects"] if e["role"] == role}
    cards = sorted({card for card, _ in table},
                   key=lambda c: -sum(a["meta_share"] * table[c, a["opponent"]]["effect"]
                                      for a in opponents if (c, a["opponent"]) in table))
    matrix = np.array([[table[c, a["opponent"]]["effect"] * 100 if (c, a["opponent"]) in table else np.nan
                        for a in opponents] for c in cards])
    limit = max(1.0, float(np.nanmax(np.abs(matrix))))

    fig, ax = plt.subplots(figsize=(2.6 + 1.3 * len(opponents), 0.45 * len(cards) + 1.8))
    image = ax.imshow(matrix, cmap=DIVERGING, vmin=-limit, vmax=limit, aspect="auto")
    for (row, col), value in np.ndenumerate(matrix):
        if np.isnan(value):
            continue
        sig = table[cards[row], opponents[col]["opponent"]]["significant"]
        ax.text(col, row, signed(value) + (" *" if sig else ""), ha="center", va="center", fontsize=9,
                color=INK, fontweight="bold" if sig else "normal")
    ax.set_xticks(range(len(opponents)), [f"{a['opponent']}\n{a['archetype']}" for a in opponents])
    ax.set_yticks(range(len(cards)), cards)
    ax.set_xticks(np.arange(-0.5, len(opponents)), minor=True)
    ax.set_yticks(np.arange(-0.5, len(cards)), minor=True)
    ax.grid(visible=False)
    ax.grid(which="minor", color="white", linewidth=2)
    ax.tick_params(which="minor", length=0)
    ax.spines[:].set_visible(False)
    ax.set_title("Efeito por cópia de cada carta que entra, por oponente" if role == "entra"
                 else "Efeito de tirar cada carta do maindeck, por oponente")
    ax.set_xlabel("pontos percentuais na taxa de vitória pós-side  ·  * = IC 95% exclui zero"
                  + ("" if role == "entra" else "\npositivo = a carta faz pouca falta; negativo = faz falta"))
    fig.colorbar(image, ax=ax, format=POINTS, fraction=0.04, pad=0.02).outline.set_visible(False)
    return fig


# --------------------------------------------------------------------------- #
# Comparação de sideboards (comparacao.json)
# --------------------------------------------------------------------------- #

def plot_comparison_candidates(data: dict):
    candidates = data["candidates"]
    names = [c["name"].replace("_", " ") for c in candidates]
    rates = np.array([c["winrate_bo3"] for c in candidates]) * 100
    errors = np.array([c["stderr_bo3"] for c in candidates]) * 100 * Z95

    fig, ax = plt.subplots(figsize=(1.5 + 1.3 * len(names), 4.5))
    ax.bar(names, rates, width=0.55, color=BLUE)
    ax.errorbar(names, rates, yerr=errors, fmt="none", ecolor=INK_2, elinewidth=1.2, capsize=3)
    for x, (rate, error) in enumerate(zip(rates, errors)):
        ax.annotate(num(rate), (x, rate + error), xytext=(0, 3), textcoords="offset points", ha="center",
                    fontsize=9, color=INK_2)
    ax.axhline(50, color=INK_2, linewidth=1, linestyle=(0, (4, 3)))
    ax.set_ylim(0, 100)
    ax.yaxis.set_major_formatter(PERCENT)
    ax.set_title(f"WinRate Bo3 no metajogo por sideboard ({data['n_matches']} séries por oponente)")
    ax.set_ylabel("WinRate Bo3 (barras de erro: IC 95%)")
    ax.grid(axis="x", visible=False)
    return fig


def plot_comparison_differences(data: dict):
    comparisons = data["comparisons"]
    labels = [f"{c['candidate']} − {c['reference']}".replace("_", " ") for c in comparisons]

    fig, ax = plt.subplots(figsize=(8, 0.5 * len(labels) + 1.8))
    forest(ax, labels, [c["gain"] for c in comparisons], [tuple(c["ci95"]) for c in comparisons],
           [c["significant"] for c in comparisons])
    ax.set_title("Diferenças de WinRate Bo3 entre sideboards (pareadas série a série)")
    ax.set_xlabel("Diferença em pontos percentuais (IC 95%)")
    return fig


# --------------------------------------------------------------------------- #

def result_figures(data: dict) -> dict:
    """Figuras de resultado.json; as que dependem de dados ausentes ficam de fora."""
    figures = {
        "convergencia": plot_convergence,
        "pesos_evolucao": plot_weight_evolution,
        "pesos_finais": plot_final_weights,
        "sideboard": plot_sideboard,
        "jogos_acumulados": plot_games,
    }
    if data.get("validation"):  # ausente em resultado_parcial.json
        figures |= {
            "validacao_confrontos": plot_validation_matchups,
            "ganho_sideboard": plot_gain,
            "md1_vs_bo3": plot_md1_bo3,
        }
    if data["swap_analysis"]["opponents"]:  # vazio no plano por afinidade
        figures |= {
            "efeito_trocas_metajogo": plot_metagame_effects,
            "efeito_trocas_entra": lambda d: plot_swap_heatmap(d, "entra"),
            "efeito_trocas_sai": lambda d: plot_swap_heatmap(d, "sai"),
        }
    return figures


def comparison_figures(data: dict) -> dict:
    figures = {"comparacao_sideboards": plot_comparison_candidates}
    if data["comparisons"]:
        figures["comparacao_diferencas"] = plot_comparison_differences
    if data["swap_analysis"]["opponents"]:
        figures |= {
            "comparacao_efeito_trocas_metajogo": plot_metagame_effects,
            "comparacao_efeito_trocas_entra": lambda d: plot_swap_heatmap(d, "entra"),
            "comparacao_efeito_trocas_sai": lambda d: plot_swap_heatmap(d, "sai"),
        }
    return figures


def save_figures(data: dict, figures: dict, out: Path, fmt: str) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, plot in figures.items():
        fig = plot(data)
        path = out / f"{name}.{fmt}"
        fig.savefig(path)
        plt.close(fig)
        paths.append(path)
    return paths


def load(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Gráficos para a análise dos resultados do BRKGA-A")
    p.add_argument("--resultado", default=str(Path("resultados") / "resultado.json"))
    p.add_argument("--comparacao", default=None, metavar="COMPARACAO.json",
                   help="saída de --compare (padrão: comparacao.json ao lado do resultado, se existir)")
    p.add_argument("--saida", default=None, help="pasta dos gráficos (padrão: graficos/ ao lado do resultado)")
    p.add_argument("--formato", choices=["png", "pdf", "svg"], default="png")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    result_path = Path(args.resultado)
    comparison_path = Path(args.comparacao) if args.comparacao else result_path.with_name("comparacao.json")
    out = Path(args.saida) if args.saida else result_path.parent / "graficos"

    paths = []
    if result_path.is_file():
        data = load(result_path)
        paths += save_figures(data, result_figures(data), out, args.formato)
    elif not args.comparacao:
        raise SystemExit(f"Arquivo não encontrado: {result_path}")
    if comparison_path.is_file():
        data = load(comparison_path)
        paths += save_figures(data, comparison_figures(data), out, args.formato)
    elif args.comparacao:
        raise SystemExit(f"Arquivo não encontrado: {comparison_path}")

    print("Gráficos gravados:")
    for path in paths:
        print(f"  {path}")


if __name__ == "__main__":
    main()
