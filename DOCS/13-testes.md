# 13 · Testes

```bash
python -m pytest            # 40 testes, cerca de 3 s, sem precisar do Forge nem do Java
python -m pytest -k forge   # só os testes de integração com o Forge (simulada)
```

Os testes usam motores falsos para verificar propriedades do pipeline sem depender de partidas
reais:

| Motor de teste | Comportamento |
|---|---|
| `ScriptedEngine` | Resultado definido pelo número do jogo. Registra as chamadas |
| `CoinEngine` | Moeda viciada (p = 0,6): o deck não importa |
| `WearTearEngine` | Cada cópia de Wear // Tear soma 15 pp à chance de vitória, e nada mais importa |

## `tests/test_core.py`: dados, decodificador, BRKGA e plano por afinidade

| Teste | Garante que |
|---|---|
| `test_mana_efficiency_is_linear_and_clipped` | Eficiência = 1 em CMC 0, 0,5 em CMC 3, 0 em CMC ≥ 6 |
| `test_build_vector_rejects_unknown_and_out_of_range` | Atributo desconhecido, valor fora de [0, 1] e `eficiencia_mana` anotada geram erro |
| `test_database_decks_are_legal` | Todos os decks têm 60 cartas e as participações somam 1 |
| `test_sideboard_slots_respect_four_copy_rule` | Pool expandido respeita 4 cópias com o maindeck (Blood Moon: 3 no side) |
| `test_lands_never_leave_in_sideboarding` | Terrenos nunca são flex, e o carregamento recusa terreno marcado como flex |
| `test_keys_to_weights_maps_unit_interval_to_plus_minus_ten` | 0 → −10, 0,5 → 0, 1 → +10. Exige 9 chaves |
| `test_decode_returns_fifteen_legal_unique_slots` | 15 entradas distintas, ordenadas por Score, sempre legais |
| `test_decode_is_deterministic_and_matches_score_formula` | Mesmas chaves dão o mesmo sideboard, e Score = w · v |
| `test_copy_penalty_never_ranks_later_copy_first` | A cópia k+1 nunca vem antes da cópia k |
| `test_graveyard_weight_selects_graveyard_hate` | Peso só em `anti_cemiterio` seleciona Rest in Peace e Sanctifier |
| `test_population_partition_matches_specification` | P = 100 dá 20 elites, 15 mutantes e 65 filhos |
| `test_crossover_is_biased_towards_elite_parent` | Cerca de 70% dos genes vêm do pai elite |
| `test_brkga_is_elitist_reproducible_and_optimizes` | Melhor fitness nunca piora, mesma semente dá o mesmo resultado, e o BRKGA converge num problema-teste |
| `test_brkga_reevaluates_whole_population_under_noisy_fitness` | Com fitness ruidoso, toda a população é reavaliada mais uma rodada final da elite |
| `test_brkga_stops_early_on_stall` | Parada antecipada após N gerações sem melhora |
| `test_sideboard_plan_boards_in_graveyard_hate_against_combo` | Plano por afinidade põe Rest in Peace contra combo e só tira cartas flex |
| `test_relevance_needs_a_functional_attribute` | Custo baixo sozinho não dá relevância (Blood Moon vs. aggro = 0) |
| `test_blood_moon_stays_in_against_big_mana` | Blood Moon não sai contra Eldrazi Tron |
| `test_sideboard_plan_respects_max_swaps` | Limite de trocas respeitado e deck com 60 cartas |

## `tests/test_simulation.py`: Bo3, planos, cache, motores, análise e pipeline

### Orquestração Bo3

| Teste | Garante que |
|---|---|
| `test_bo3_plays_game3_only_when_tied_and_scores_matches` | G3 só em 1–1, perdedor do G2 começa o G3, e as taxas estão corretas |
| `test_bo3_skips_game3_after_two_wins` | 2–0 não joga G3 |
| `test_game1_alternates_play_draw_and_is_computed_once` | G1 alterna quem começa e é jogado uma vez por oponente |

### Plano aleatório e cache de jogos

| Teste | Garante que |
|---|---|
| `test_random_plan_draws_from_sideboard_and_keeps_lands` | Entram só cartas do side, saem só flex, nunca a mesma carta, deck com 60 cartas e mesmo nº de terrenos, 1 a 5 trocas, e a ordem do side não importa |
| `test_random_plan_is_uniform_over_sideboard_copies` | Cada cópia do side entra em cerca de 3/15 das séries (sorteio uniforme) |
| `test_random_plan_is_shared_by_sideboards_holding_the_drawn_cards` | Trocar uma carta não sorteada não muda o plano (números aleatórios comuns) |
| `test_game_cache_simulates_each_deck_once` | Dois sideboards com o mesmo deck compartilham os jogos, reavaliar não simula nada, e há um lote por (oponente, deck) |
| `test_affinity_plan_is_the_same_in_every_series` | Plano por afinidade é fixo por oponente, e modo inválido gera erro |
| `test_swap_analysis_recovers_the_effect_of_a_card` | A regressão recupera +15 pp para Wear // Tear (significativo), efeitos perto de zero para as outras cartas e Wear // Tear em 1º no metajogo |

### Simulador substituto

| Teste | Garante que |
|---|---|
| `test_surrogate_game1_probability_depends_only_on_base_logit` | No G1, P(vitória) = sigmoide(`base_logit`) |
| `test_surrogate_rewards_enchantment_hate_against_bogles` | Wear // Tear aumenta a chance contra Bogles |
| `test_surrogate_uses_common_random_numbers` | Duas execuções independentes dão resultados idênticos |

### Fitness

| Teste | Garante que |
|---|---|
| `test_fitness_cache_and_parallel_evaluation_match_serial` | Cache de sideboards funciona, e a execução com 2 workers dá o mesmo resultado que a serial, inclusive na validação |
| `test_resampling_accumulates_series_per_sideboard` | Cada reavaliação soma uma rodada, o G1 é reaproveitado, e `evaluate_one` não joga rodadas extras |
| `test_noise_alone_is_not_reported_as_sideboard_gain` | Com um motor em que o deck não importa, a validação não aponta ganho significativo |

### Forge (sem Java)

| Teste | Garante que |
|---|---|
| `test_parse_forge_output` | Vitórias, derrotas e empates são lidos, e uma contagem errada gera `ForgeError` |
| `test_forge_engine_runs_subprocess_and_parses` | Um "java" falso que imita o Forge é chamado corretamente, e os `.dck` temporários são apagados |
| `test_forge_dck_format` | Formato `.dck` correto e 60 cartas |

### Pipeline e exportação

| Teste | Garante que |
|---|---|
| `test_small_experiment_and_export` | Experimento pequeno de ponta a ponta. JSON com 15 cartas e histórico. XLSX com as 7 abas, incluindo `Efeito_Trocas` com dados |
| `test_experiment_validates_best_and_baseline_on_fresh_series` | Validação com séries novas, mesmos G1 para os dois candidatos, linha de base sem trocas, IC consistente |
| `test_measure_game1_reports_wins_per_opponent` | Diagnóstico do Game 1 devolve vitórias por oponente |

### Arquivo de jogos e comparação de sideboards

| Teste | Garante que |
|---|---|
| `test_game_archive_round_trip_and_context` | Os jogos gravados voltam iguais, a execução atual não se lê a si mesma, outro contexto é ignorado, e só o motor determinístico deduplica chaves |
| `test_archived_games_feed_the_swap_analysis_but_not_the_results` | Com o arquivo ligado, busca e validação saem idênticas às de uma execução isolada, e a análise das trocas ganha jogos |
| `test_paired_comparison_uses_differences_between_series` | Candidatos iguais dão ganho e erro zero; o erro por blocos confere com a conta feita à mão |
| `test_compare_sideboards_shares_game1_and_exports` | Mesmos G1 para todos, linha de base por último, pares comparados corretos, sideboards ilegais rejeitados, JSON e XLSX exportados |
| `test_compare_command_reads_the_sideboard_of_a_previous_result` | `main.py --compare` lê o sideboard de um `resultado.json` e grava `comparacao.json` |

## Escrevendo testes novos

- Use a fixture `db` (`load_database()`, escopo de módulo).
- Para propriedades do pipeline, prefira um motor falso ao substituto: o resultado esperado fica
  explícito no teste.
- O substituto é determinístico, então comparações exatas entre execuções são válidas.
