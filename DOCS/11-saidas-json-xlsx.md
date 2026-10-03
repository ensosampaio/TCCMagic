# 11 · Saídas: JSON e XLSX

Módulo: `tccmagic/export.py`. Ao final de cada execução, `main.py` grava em `--out` (padrão
`resultados/`):

- `resultado.json`: tudo, inclusive a configuração completa;
- `resultado.xlsx`: as mesmas informações em abas, para gráficos e tabelas do TCC.

## `resultado.json`

### Topo

| Chave | Conteúdo |
|---|---|
| `config` | `ExperimentConfig` completo, incluindo `brkga`, `surrogate` e `forge` |
| `maindeck` | Nome do maindeck |
| `elapsed_seconds` | Tempo total |
| `stopped_early` | Houve parada antecipada |
| `resampled` | A reamostragem estava ativa |
| `games_simulated` | Jogos pós-side simulados pelo motor |
| `games_reused` | Jogos pós-side reaproveitados do cache |
| `final` | Melhor indivíduo da busca (estimativa **otimista**) |
| `validation` | Validação com séries novas (os números que valem) |
| `swap_analysis` | Efeito das trocas sorteadas |
| `history` | Uma entrada por geração |

### `final`

| Chave | Conteúdo |
|---|---|
| `fitness` | WinRate_Bo3 acumulada na busca |
| `keys` | `{atributo: chave}` |
| `weights` | `{atributo: peso}` |
| `sideboard` | Lista de `{rank, card, copy, score}` com as 15 entradas |
| `evaluation` | Relatório de avaliação (formato abaixo) |

### Relatório de avaliação

Usado em `final.evaluation`, `validation.sideboard` e `validation.baseline_no_sideboard`:

| Chave | Conteúdo |
|---|---|
| `winrate_md1`, `winrate_bo3`, `winrate_postboard`, `delta_winrate` | Agregados pelo metajogo |
| `n_matches` | Séries por oponente |
| `stderr_bo3` | Só na validação |
| `matchups` | Lista por oponente, abaixo |

Cada item de `matchups` tem `opponent`, `archetype`, `meta_share`, `n_matches`, `game1_wins`,
`match_wins`, `postboard_games`, `postboard_wins`, `swaps_in` e `swaps_out` (pares
`[carta, cópias somadas]`), `cards_in` e `cards_out` (texto com cópias por série), `winrate_md1`,
`winrate_bo3`, `winrate_postboard` e `delta_winrate`.

### `validation`

| Chave | Conteúdo |
|---|---|
| `n_matches` | Séries novas por oponente |
| `sideboard` | Relatório do sideboard escolhido |
| `baseline_no_sideboard` | Relatório sem sideboard (`cards_in` = "—") |
| `gain` | Bo3 com side − Bo3 sem side |
| `gain_stderr`, `gain_ci95` | Erro padrão e IC de 95% |
| `significant` | O IC exclui zero |

### `swap_analysis`

```json
{
  "method": "probabilidade linear por oponente; ...",
  "opponents": [
    {"opponent": "Bogles", "archetype": "auras", "meta_share": 0.2, "games": 926,
     "winrate_postboard": 0.497, "no_swap_winrate": 0.450,
     "effects": [
       {"card": "Wear // Tear", "role": "entra", "games": 258, "winrate": 0.52,
        "effect": 0.043, "stderr": 0.043, "ci95": [-0.042, 0.128], "significant": false}
     ]}
  ],
  "metagame": [{"card": "...", "role": "entra", "...": "..."}]
}
```

`opponents` e `metagame` ficam vazios no plano `afinidade`. O significado de `effect` está em
[10](10-validacao-e-analise-de-trocas.md#interpretação).

### `history[]`

| Chave | Conteúdo |
|---|---|
| `generation` | 0 = população inicial |
| `best_fitness`, `mean_fitness`, `std_fitness` | Estatísticas da população |
| `winrate_md1`, `winrate_bo3`, `winrate_postboard`, `delta_winrate` | Do melhor indivíduo |
| `best_n_matches` | Séries por oponente acumuladas pelo melhor |
| `weights`, `sideboard` | Pesos e lista compacta `[carta, cópias]` do melhor |
| `simulated_sideboards` | Rodadas de sideboard avaliadas até aqui |
| `games_simulated`, `games_reused` | Jogos pós-side simulados e reaproveitados até aqui |
| `elapsed_seconds` | Tempo decorrido |

## `resultado.xlsx`

| Aba | Linhas | Colunas |
|---|---|---|
| `Geracoes` | Uma por geração | `geracao`, `melhor_fitness`, `fitness_medio`, `fitness_desvio`, `winrate_md1`, `winrate_bo3`, `winrate_pos_side`, `delta_winrate`, `series_do_melhor`, `sideboards_simulados`, `jogos_simulados`, `jogos_reaproveitados`, `tempo_s`, `w_<atributo>` × 9 |
| `Pesos_Finais` | 9 | `atributo`, `chave`, `peso` |
| `Sideboard` | 15 | `rank`, `carta`, `copia`, `score` |
| `Matchups` | Uma por oponente (busca) | `oponente`, `arquetipo`, `meta_share`, `series`, `winrate_md1`, `winrate_bo3`, `winrate_pos_side`, `delta_winrate`, `entram (copias por serie)`, `saem (copias por serie)` |
| `Validacao` | 2 × oponentes | `deck` (`com_sideboard` / `sem_sideboard`) e as colunas de `Matchups` |
| `Efeito_Trocas` | Uma por (oponente, carta, papel), mais as linhas "Metajogo" | `oponente`, `carta`, `papel`, `jogos`, `winrate_bruta`, `efeito_por_copia`, `erro_padrao`, `ic95_inferior`, `ic95_superior`, `significativo` |
| `Resumo` | Métrica / valor | Maindeck, motor, plano, jogos simulados e reaproveitados, gerações, fitness da busca, validação (Md1, Bo3, erro, ΔWR, sem side), ganho e IC, significância, tempo |

Valores em `Efeito_Trocas` estão em **proporção** (0,05 = 5 pp).

## Qual número usar no texto

| Pergunta | Onde |
|---|---|
| O sideboard melhora o deck? | `validation.gain`, `gain_ci95`, `significant` |
| Desempenho por confronto | `validation.sideboard.matchups` comparado com `validation.baseline_no_sideboard.matchups` |
| Que cartas trocar contra cada oponente | `swap_analysis.opponents[].effects` |
| Que cartas mais valem no metajogo | `swap_analysis.metagame` |
| Convergência do algoritmo | `history` / aba `Geracoes` |
| Composição final | `final.sideboard` / aba `Sideboard` |

Não use `final.fitness` como resultado: é a estimativa otimista da busca.
