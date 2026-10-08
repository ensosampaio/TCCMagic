# 12 · Referência de API

Classes e funções públicas, por módulo. Nomes com `_` na frente são internos e aparecem só quando
ajudam a entender o fluxo. Todos os `dataclass` marcados como imutáveis são `frozen=True`.

## `attributes.py`

| Símbolo | Descrição |
|---|---|
| `ATTRIBUTES: tuple[str, ...]` | Os 9 nomes, na ordem dos genes |
| `N_ATTRIBUTES = 9` | Tamanho do cromossomo |
| `MAX_CMC_FOR_EFFICIENCY = 6.0` | CMC em que a eficiência de mana chega a 0 |
| `mana_efficiency(cmc) -> float` | `clip(1 − cmc/6, 0, 1)` |
| `build_vector(cmc, annotated) -> ndarray` | Vetor v(c) a partir do CMC e dos atributos 2–9 anotados. Valida nomes e intervalo |
| `vector_from_mapping(mapping) -> ndarray` | Dicionário com os 9 atributos → vetor ordenado (usado em afinidades e vulnerabilidades) |

## `cards.py`

Constantes: `MAINDECK_SIZE = 60`, `SIDEBOARD_SIZE = 15`, `MAX_COPIES = 4`, `BASIC_LANDS`,
`DATA_DIR`.

### `Card` (imutável)

`Card(name, cmc, vector=(0,)*9, is_land=False, flex=False)`

| Membro | Descrição |
|---|---|
| `v` | `vector` como `ndarray` |
| `Card.from_json(raw)` | Constrói a partir de uma entrada de JSON (terrenos ganham vetor nulo) |

### `SideboardSlot` (imutável)

`SideboardSlot(card, copy_index)`. A propriedade `label` devolve `"Nome #k"`.

### `Deck` (imutável)

`Deck(name, cards: tuple[(Card, quantidade), ...])`

| Membro | Descrição |
|---|---|
| `Deck.from_cards(name, cards)` | Agrupa uma sequência com repetição |
| `size` | Total de cartas |
| `counts() -> Counter` | `{nome: quantidade}` |
| `expanded()` | Itera uma entrada por cópia |
| `nonland_cards()` | Cópias que não são terreno |
| `flex_cards()` | Cópias que podem sair no sideboarding. **Nunca inclui terrenos** |
| `swap(cards_out, cards_in, name=None) -> Deck` | Novo deck com as trocas. Erro se uma carta a sair não existir |
| `to_forge_dck(sideboard=()) -> str` | Texto `.dck` do Forge |

### `Opponent` (imutável)

`Opponent(name, archetype, meta_share, deck, base_logit=0, postboard_penalty=0,
vulnerability=(0,)*9)`. A propriedade `vuln` devolve `vulnerability` como `ndarray`.

### `Database` (imutável)

`Database(maindeck, candidates, candidate_max_copies, opponents, archetype_affinity)`

| Membro | Descrição |
|---|---|
| `sideboard_slots() -> list[SideboardSlot]` | Pool expandido por cópia, respeitando a regra de 4 cópias com o maindeck |
| `affinity(archetype) -> ndarray` | Linha da tabela de afinidade. `KeyError` explicativo se não existir |

### Carregamento

| Função | Descrição |
|---|---|
| `load_database(data_dir=DATA_DIR, maindeck_file="maindeck_boros_energy.json")` | Carrega e valida tudo |
| `load_maindeck(path)` | 60 cartas, ≤ 4 cópias, terreno não pode ser flex |
| `load_card_pool(path)` | Cartas candidatas e `max_copies`. Recusa nomes repetidos |
| `load_opponents(path)` | Decks de 60 cartas e parâmetros do substituto |
| `load_archetypes(path)` | Tabela de afinidade |

## `decoder.py`

| Símbolo | Descrição |
|---|---|
| `WEIGHT_MIN = -10`, `WEIGHT_MAX = 10` | Faixa dos pesos |
| `keys_to_weights(keys)` | `20k − 10`. Exige 9 chaves |
| `DecodedSideboard` (imutável) | `weights`, `slots`, `scores`, mais `cards`, `key`, `weights_by_attribute()`, `card_counts()` |
| `SideboardDecoder(database, copy_penalty=1.0, sideboard_size=15)` | `chromosome_length` (9), `scores(weights)` e `decode(keys) -> DecodedSideboard` |

## `brkga.py`

| Símbolo | Descrição |
|---|---|
| `BRKGAConfig(population_size=50, elite_fraction=0.2, mutant_fraction=0.15, elite_bias=0.7, generations=50, max_stall_generations=None, seed=42)` | Valida as frações. Propriedades `n_elite`, `n_mutants`, `n_offspring` |
| `GenerationStats` (imutável) | `generation`, `best_fitness`, `mean_fitness`, `std_fitness`, `best_keys`, `elapsed_seconds` |
| `BRKGAResult` | `best_keys`, `best_fitness`, `history`, `stopped_early` |
| `BRKGA_Optimizer(chromosome_length, fitness_function, config=None, on_generation=None, reevaluate_elites=False)` | Otimizador (maximização) |

Métodos de `BRKGA_Optimizer`:

| Método | Descrição |
|---|---|
| `run() -> BRKGAResult` | Ciclo completo |
| `initialize()` | População inicial aleatória, avaliada e ordenada |
| `step()` | Uma geração: elite + filhos + mutantes |
| `crossover(elites, non_elites, count)` | Cruzamento uniforme viesado |
| `random_individuals(count)` | Chaves U[0, 1) |
| `refresh_elites()` | Reavalia só a elite (desempate final com fitness ruidoso) |

`fitness_function` recebe a população (`ndarray` P × n) e devolve um `ndarray` com P valores.

## `sideboarding.py`

| Símbolo | Descrição |
|---|---|
| `SideboardPlan` (imutável) | `archetype`, `cards_in`, `cards_out`, `deck`, mais `n_swaps`, `signature`, `describe()` |
| `relevance(card, affinity) -> float` | `[Σ_{2..9} a_i v_i] · (1 + a_1 v_1)` |
| `build_sideboard_plan(maindeck, sideboard, archetype, affinity, max_swaps=5, margin=0.0)` | Plano por afinidade |
| `random_sideboard_plan(maindeck, sideboard, archetype, priority, n_swaps)` | Plano aleatório. `priority(rótulo) -> [0, 1)` define o sorteio |

## `simulation/base.py`

| Símbolo | Descrição |
|---|---|
| `GameSpec(match_index, game_number, on_play)` (imutável) | Um jogo |
| `MatchEngine` (abstrata) | `name`, `deterministic` e `play_games(deck, opponent, specs) -> list[bool]` |
| `stable_id(text) -> int` | CRC32, estável entre processos |

## `simulation/bo3.py`

| Símbolo | Descrição |
|---|---|
| `wilson_interval(wins, n, z=1.96)` | IC de Wilson |
| `MatchupReport` (imutável) | Ver [06](06-simulacao-bo3.md#relatórios) |
| `EvaluationReport` (imutável) | Agregado ponderado. `stderr_bo3` e `merge()` |
| `PLAN_MODES = ("aleatorio", "afinidade")` | Modos aceitos |
| `GameKey`, `Batch`, `BatchRunner` | Tipos do cache de jogos e dos lotes |
| `Bo3Simulator(database, engine, matches_per_opponent=50, max_swaps=5, swap_margin=0.0, plan="aleatorio", plan_block=10, plan_seed=2024)` | Orquestrador |

Membros de `Bo3Simulator`:

| Membro | Descrição |
|---|---|
| `game1` | `{oponente: [bool]}` dos Games 1 da busca |
| `games` | Cache `{GameKey: bool}` de todos os jogos pós-side |
| `games_played`, `games_reused` | Contadores |
| `play_game1(opp, n_matches=None, match_offset=0)` | Games 1 com o maindeck |
| `prepare()` | Joga os Games 1 uma vez |
| `evaluate(sideboard, round_index=0)` | Avaliação serial de um sideboard |
| `plan_for(opp, sideboard, match_index)` | Plano da série |
| `play_postboard(jobs, game1, runner=None)` | Games 2/3 de vários sideboards, com cache e lotes por deck |
| `run_batches(batches)` | Executor serial dos lotes |

## `simulation/surrogate.py`

| Símbolo | Descrição |
|---|---|
| `DEFAULT_SATURATION` | κ por atributo |
| `SurrogateConfig(beta=2.0, play_bonus=0.2, seed=12345, saturation=...)` | Parâmetros |
| `SurrogateEngine(maindeck, config=None)` | `deck_features(deck)`, `strength(features, opp)`, `win_probability(deck, opp, game_number, on_play)` e `play_games(...)` |

## `simulation/forge.py`

| Símbolo | Descrição |
|---|---|
| `ForgeConfig(jar_path, ...)` | Ver [08](08-motores.md#configuração-forgeconfig) |
| `ForgeEngine(config)` | `build_command(a, b, n)` e `play_games(...)` |
| `ForgeError` | Falhas de execução ou de parsing |
| `parse_forge_output(stdout, n_games, config) -> list[bool]` | Extrai os vencedores |
| `PLAYER_TAG`, `OPPONENT_TAG` | Marcadores nos nomes dos decks |

## `fitness.py`

| Símbolo | Descrição |
|---|---|
| `VALIDATION_MATCH_OFFSET = 1_000_000_000` | Índice inicial das séries de validação |
| `Evaluation(decoded, report)` (imutável) | `fitness` = `report.winrate_bo3` |
| `FitnessEvaluator(decoder, simulator, workers=1, resample=False)` | Avaliador (gerenciador de contexto) |

Métodos de `FitnessEvaluator`:

| Método | Descrição |
|---|---|
| `__call__(population) -> ndarray` | Interface do BRKGA |
| `evaluate_population(population, sample=True) -> list[Evaluation]` | Com `sample=False`, só simula sideboards inéditos |
| `evaluate_one(keys) -> Evaluation` | Consulta sem rodadas extras |
| `play_game1(n_matches, match_offset=0)` | Games 1 (em paralelo, se houver workers) |
| `validate(sideboards, n_matches) -> list[EvaluationReport]` | Séries novas e Games 1 novos. `()` = linha de base |
| `close()` | Encerra o pool de processos |

Atributos: `cache`, `rounds`, `simulations`.

## `analysis.py`

| Símbolo | Descrição |
|---|---|
| `SwapEffect` (imutável) | `opponent`, `card`, `role`, `games`, `winrate`, `effect`, `stderr`, mais `ci95` e `significant` |
| `OpponentSwapAnalysis` (imutável) | `opponent`, `archetype`, `meta_share`, `games`, `winrate`, `no_swap_winrate`, `effects`, mais `role(r)` |
| `analyze_swaps(games, database) -> list[OpponentSwapAnalysis]` | Regressão por oponente sobre o cache de jogos |
| `analyze_opponent(rows, flex_counts, opponent, archetype, meta_share)` | Regressão de um oponente. `rows` = `(entram, saem, venceu)` |
| `metagame_effects(analyses) -> list[SwapEffect]` | Efeito de colocar cada carta, ponderado pelo metajogo |

## `pipeline.py`

### `ExperimentConfig`

| Campo | Padrão | Descrição |
|---|---|---|
| `engine` | `"surrogate"` | `"surrogate"` ou `"forge"` |
| `matches_per_opponent` | 50 | Séries por oponente por rodada (a CLI usa 100) |
| `validation_matches` | `None` | `None` = 5 × `matches_per_opponent` (propriedade `n_validation_matches`) |
| `resample` | `None` | `None` = ligado se o motor não for determinístico |
| `max_swaps` | 5 | Máximo de trocas |
| `swap_margin` | 0,0 | Margem do plano por afinidade |
| `plan` | `"aleatorio"` | Modo do plano |
| `plan_block` | 10 | Séries por sorteio |
| `plan_seed` | 2024 | Semente dos sorteios |
| `copy_penalty` | 1,0 | δ do decodificador |
| `workers` | 1 | Processos |
| `games_dir` | `None` | Pasta do arquivo de jogos (`None` = desligado; a CLI usa `resultados/jogos`) |
| `data_dir`, `maindeck_file` | `tccmagic/data`, `maindeck_boros_energy.json` | Dados |
| `brkga` | `BRKGAConfig()` | — |
| `surrogate` | `SurrogateConfig()` | — |
| `forge` | `None` | Obrigatório com `engine="forge"` |

### Outros

| Símbolo | Descrição |
|---|---|
| `GenerationRecord` (imutável) | Linha do histórico ([11](11-saidas-json-xlsx.md#history)) |
| `Validation` (imutável) | `n_matches`, `sideboard`, `baseline`, mais `gain`, `gain_stderr`, `gain_interval()`, `significant` |
| `ExperimentResult` | `config`, `database`, `history`, `best`, `best_keys`, `validation`, `swap_analysis`, `games_simulated`, `games_reused`, `resampled`, `stopped_early`, `elapsed_seconds`, mais `config_dict()` |
| `build_engine(config, database)` | Instancia o motor |
| `measure_game1(config, n_games) -> list[(Opponent, vitórias)]` | Diagnóstico do Game 1 |
| `run_experiment(config, progress=None, status=None) -> ExperimentResult` | Experimento completo. `progress` recebe cada `GenerationRecord`, e `status` recebe mensagens de texto |
| `VALIDATION_FACTOR = 5` | Multiplicador padrão das séries de validação |
| `compare_sideboards(config, sideboards, status=None) -> ComparisonResult` | Valida vários sideboards (`nome -> cartas`, uma por cópia) e a linha de base sobre os mesmos Games 1, sem busca |
| `ComparisonResult` | `config`, `database`, `n_matches`, `candidates`, `comparisons`, `swap_analysis`, `games_simulated`, `games_reused`, `games_archived`, `elapsed_seconds` |
| `Candidate` (imutável) | `name`, `cards`, `report`, `series_wins` (oponente → resultado de cada série) |
| `Comparison` (imutável) | `candidate`, `reference`, `gain`, `stderr`, mais `interval()` e `significant` |
| `paired_comparison(candidate, reference, block=1) -> Comparison` | Diferença pareada série a série, com erro por blocos de `block` séries |
| `sideboard_from_names(database, names)` | Nomes → cartas do pool; rejeita carta fora do pool, tamanho ≠ 15 e cópias em excesso |
| `random_sideboard(database, rng)` | 15 entradas sorteadas do pool |
| `NO_SIDEBOARD = "sem_sideboard"` | Nome da linha de base na comparação |

`ExperimentResult` tem também `games_archived` (jogos de execuções anteriores usados na análise).

## `archive.py`

| Símbolo | Descrição |
|---|---|
| `context_fingerprint(database, engine) -> str` | Identifica motor, maindeck e listas dos oponentes |
| `GameArchive(directory, context, engine="")` | Lê os jogos das execuções anteriores do mesmo contexto (`previous`, `skipped_runs`) e reserva o arquivo desta execução (`path`) |
| `GameArchive.save(games)` | Grava (ou regrava) os jogos desta execução |
| `GameArchive.merged(games, deterministic)` | Jogos anteriores + atuais; num motor determinístico, a mesma chave conta uma vez |

Em `fitness.py`, `FitnessEvaluator.validate_detailed(sideboards, n)` devolve os relatórios e o
resultado de cada série; em `simulation/bo3.py`, `Bo3Simulator.play_postboard_detailed` faz o
mesmo para `play_postboard`. Em `cards.py`, `load_reference_sideboard()` lê o sideboard de
referência. Em `export.py`, `export_comparison_json` e `export_comparison_xlsx` gravam a comparação.

## `export.py`

| Função | Descrição |
|---|---|
| `result_to_dict(result) -> dict` | Estrutura do JSON |
| `export_json(result, path) -> Path` | Grava o JSON (cria a pasta) |
| `export_xlsx(result, path) -> Path` | Grava o XLSX (exige `openpyxl`) |

## `main.py`

| Função | Descrição |
|---|---|
| `parse_args(argv=None)` | Opções da CLI ([02](02-instalacao-e-execucao.md#todas-as-opções)) |
| `run(args)` | Monta a configuração, roda, imprime e exporta |
| `menu()` | Menu interativo |
| `print_generation`, `print_summary`, `print_swap_analysis`, `print_game1_check` | Relatórios no terminal |
| `fitness_noise(matches, shares)` | Erro padrão máximo do fitness de uma rodada |
| `estimate_forge_hours(args, n_opponents)` | Estimativa de tempo no Forge (limite superior) |
| `DEFAULT_FORGE_DIR`, `DEFAULT_FORGE_JAR` | Instalação local do Forge |
| `FORGE_STARTUP_SECONDS = 16`, `FORGE_GAME_SECONDS = 3.5` | Tempos usados na estimativa |
