"""Exportação do histórico de gerações, pesos finais e sideboard para JSON e XLSX."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from tccmagic.attributes import ATTRIBUTES
from tccmagic.pipeline import ExperimentResult
from tccmagic.simulation import EvaluationReport


def _report_dict(report: EvaluationReport) -> dict:
    return {
        "winrate_md1": report.winrate_md1,
        "winrate_bo3": report.winrate_bo3,
        "winrate_postboard": report.winrate_postboard,
        "delta_winrate": report.delta_winrate,
        "matchups": [{**asdict(m), "delta_winrate": m.delta_winrate} for m in report.matchups],
    }


def result_to_dict(result: ExperimentResult) -> dict:
    best = result.best
    return {
        "config": result.config_dict(),
        "maindeck": result.database.maindeck.name,
        "elapsed_seconds": result.elapsed_seconds,
        "stopped_early": result.stopped_early,
        "final": {
            "fitness": best.fitness,
            "keys": dict(zip(ATTRIBUTES, result.best_keys)),
            "weights": best.decoded.weights_by_attribute(),
            "sideboard": [
                {"rank": i, "card": slot.card.name, "copy": slot.copy_index, "score": score}
                for i, (slot, score) in enumerate(zip(best.decoded.slots, best.decoded.scores), start=1)
            ],
            "evaluation": _report_dict(best.report),
        },
        "baseline_no_sideboard": _report_dict(result.baseline_no_sideboard),
        "history": [asdict(rec) for rec in result.history],
    }


def export_json(result: ExperimentResult, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(result_to_dict(result), fh, ensure_ascii=False, indent=2)
    return path


def export_xlsx(result: ExperimentResult, path: str | Path) -> Path:
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font
    except ImportError as exc:  # pragma: no cover - depende do ambiente
        raise ImportError("Exportação .xlsx requer 'openpyxl' (pip install openpyxl).") from exc

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    best = result.best

    def sheet(title: str, header: list[str], rows: list[list], first: bool = False):
        ws = wb.active if first else wb.create_sheet()
        ws.title = title
        ws.append(header)
        for cell in ws[1]:
            cell.font = Font(bold=True)
        for row in rows:
            ws.append(row)
        for column in ws.columns:
            width = max(len(str(c.value)) if c.value is not None else 0 for c in column)
            ws.column_dimensions[column[0].column_letter].width = min(60, width + 2)
        return ws

    sheet(
        "Geracoes",
        ["geracao", "melhor_fitness", "fitness_medio", "fitness_desvio", "winrate_md1", "winrate_bo3",
         "winrate_pos_side", "delta_winrate", "sideboards_simulados", "tempo_s",
         *[f"w_{a}" for a in ATTRIBUTES]],
        [[r.generation, r.best_fitness, r.mean_fitness, r.std_fitness, r.winrate_md1, r.winrate_bo3,
          r.winrate_postboard, r.delta_winrate, r.simulated_sideboards, r.elapsed_seconds,
          *[r.weights[a] for a in ATTRIBUTES]] for r in result.history],
        first=True,
    )
    sheet(
        "Pesos_Finais",
        ["atributo", "chave", "peso"],
        [[a, k, w] for a, k, w in zip(ATTRIBUTES, result.best_keys, best.decoded.weights)],
    )
    sheet(
        "Sideboard",
        ["rank", "carta", "copia", "score"],
        [[i, s.card.name, s.copy_index, sc]
         for i, (s, sc) in enumerate(zip(best.decoded.slots, best.decoded.scores), start=1)],
    )
    matchup_header = ["oponente", "arquetipo", "meta_share", "series", "winrate_md1", "winrate_bo3",
                      "winrate_pos_side", "delta_winrate", "entram", "saem"]
    sheet(
        "Matchups",
        matchup_header,
        [[m.opponent, m.archetype, m.meta_share, m.n_matches, m.winrate_md1, m.winrate_bo3,
          m.winrate_postboard, m.delta_winrate, m.cards_in, m.cards_out] for m in best.report.matchups],
    )
    base = result.baseline_no_sideboard
    sheet(
        "Resumo",
        ["metrica", "valor"],
        [
            ["maindeck", result.database.maindeck.name],
            ["motor", result.config.engine],
            ["geracoes_executadas", len(result.history) - 1],
            ["fitness_final (winrate_bo3)", best.fitness],
            ["winrate_md1", best.report.winrate_md1],
            ["winrate_bo3", best.report.winrate_bo3],
            ["delta_winrate (bo3 - md1)", best.report.delta_winrate],
            ["winrate_bo3_sem_sideboard", base.winrate_bo3],
            ["ganho_do_sideboard (bo3 - bo3_sem_side)", best.report.winrate_bo3 - base.winrate_bo3],
            ["tempo_total_s", result.elapsed_seconds],
        ],
    )
    wb.save(path)
    return path
