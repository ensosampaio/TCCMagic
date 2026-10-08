# 08 · Motores de partida

Um motor decide o vencedor de cada jogo. Todos implementam a interface `MatchEngine`
(`tccmagic/simulation/base.py`):

```python
class MatchEngine(ABC):
    name: str = "engine"
    deterministic: bool = False   # mesmo deck + mesmo GameSpec ⇒ mesmo resultado?

    def play_games(self, deck: Deck, opponent: Opponent, specs: Sequence[GameSpec]) -> list[bool]:
        """True se o nosso deck venceu (empate = False), um por GameSpec."""
```

`GameSpec(match_index, game_number, on_play)` descreve um jogo: índice da série, número do jogo
(1, 2 ou 3) e se o nosso deck começa jogando. Os jogos chegam **em lote**, para que o Forge execute
vários numa única chamada à JVM.

`deterministic` define o padrão da reamostragem: ela fica ligada quando o motor **não** é
determinístico.

| Motor | `name` | Determinístico | Uso |
|---|---|---|---|
| `SurrogateEngine` | `surrogate` | sim | Desenvolvimento, testes, experimentos rápidos |
| `ForgeEngine` | `forge` | não | Partidas reais da IA do MTG Forge |

## Simulador substituto (`SurrogateEngine`)

Módulo: `tccmagic/simulation/surrogate.py`. Modela cada jogo como um sorteio de Bernoulli.

### Modelo

```
força(deck, opp) = Σ_i vuln_i(opp) · sat_i(deck)

sat_1 = média de eficiencia_mana nas cartas não-terreno
sat_i = 1 − exp(−Σ_c v_i(c) / κ_i)          i = 2..9   (retornos decrescentes)

logit P(vitória) = base_logit(opp)
                 + β · [força(deck) − força(maindeck)]
                 ± play_bonus                   (+ se começamos jogando)
                 − postboard_penalty(opp)       (só nos Games 2 e 3)
```

- No Game 1 (deck = maindeck), a taxa depende só de `base_logit` e de quem começa.
- Nos Games 2/3, o ganho vem só das cartas que o plano colocou no deck.
- A saturação κ faz o primeiro *hate piece* valer mais que o quinto.

### Parâmetros (`SurrogateConfig`)

| Campo | Padrão | Significado |
|---|---|---|
| `beta` | 2,0 | Sensibilidade do logit à diferença de força |
| `play_bonus` | 0,2 | Vantagem, em logit, de começar jogando |
| `seed` | 12345 | Semente dos sorteios |
| `saturation` | ver abaixo | κ por atributo |

| Atributo | κ |
|---|---|
| `remocao` | 6 |
| `anti_aggro` | 6 |
| `anti_combo` | 3 |
| `anti_cemiterio` | 2 |
| `anti_artefato_encantamento` | 2 |
| `interacao_pilha` | 3 |
| `vantagem_cartas` | 10 |
| `pressao` | 15 |

`vuln`, `base_logit` e `postboard_penalty` vêm de `opponents.json` ([03](03-dados-de-entrada.md)).

### Números aleatórios comuns

O sorteio U ~ Uniforme(0, 1) de cada jogo é fixado por (semente, oponente, série, jogo).
Sideboards diferentes enfrentam a mesma "sorte", então o fitness é determinístico e as diferenças
refletem só a probabilidade de vitória.

> **Atenção:** os resultados do substituto refletem as vulnerabilidades anotadas à mão. Servem
> para validar o pipeline e não dizem nada sobre o desempenho real das cartas.

## Motor Forge (`ForgeEngine`)

Módulo: `tccmagic/simulation/forge.py`. Executa partidas reais entre IAs do MTG Forge.

### Como uma chamada funciona

1. Grava os dois decks como `.dck` na pasta de decks do perfil do Forge:

   | Sistema | Pasta |
   |---|---|
   | Windows | `%APPDATA%\Forge\decks\constructed` |
   | macOS | `~/Library/Application Support/Forge/decks/constructed` |
   | Linux | `~/.forge/decks/constructed` |

   Os nomes são marcadores únicos (`TCCPlayer_<token>` e `TCCOpponent_<token>`), e o campo `Name=`
   do `.dck` é idêntico ao nome do arquivo.
2. Executa, com o diretório do Forge como `cwd`:
   ```
   java -Xmx1536m -Djava.awt.headless=true -jar <forge.jar> sim -d <A>.dck <B>.dck -n <N> [-f formato]
   ```
3. Lê o `stdout` e extrai o vencedor de cada jogo por expressão regular.
4. Apaga os `.dck` temporários, mesmo em caso de erro.

### Configuração (`ForgeConfig`)

| Campo | Padrão | Significado |
|---|---|---|
| `jar_path` | — (obrigatório) | JAR do Forge |
| `forge_dir` | `None` | Diretório de instalação (contém `res/`), usado como `cwd` |
| `java_executable` | `java` | Executável Java |
| `java_options` | `-Xmx1536m -Djava.awt.headless=true` | Opções da JVM |
| `game_format` | `None` | Valor de `-f` (ex.: `Constructed`) |
| `extra_args` | `()` | Argumentos extras |
| `timeout_per_game` | 180 s | Tempo-limite por jogo |
| `startup_timeout` | 120 s | Tempo-limite de inicialização. Total = `startup + por_jogo × N` |
| `retries` | 3 | Repetições do lote quando o Forge sai com erro (ex.: JVM sem memória) |
| `retry_wait` | 30 s | Espera antes de repetir (cresce a cada tentativa: 30, 60, 90 s) |
| `win_pattern` | `Game\s+(\d+)\s+ended in\s+\d+\s*ms\.\s*(.+?)\s+has won!` | Regex de vitória |
| `draw_pattern` | `Game\s+(\d+)\s+ended in a [Dd]raw` | Regex de empate |
| `env` | `{}` | Variáveis de ambiente extras |

### Erros (`ForgeError`)

- JAR ou Java não encontrados (verificado na criação do motor);
- tempo-limite excedido;
- código de saída diferente de zero após todas as tentativas (mostra o final do `stdout` e do `stderr`);
- número de resultados diferente do pedido, ou vencedor não reconhecido (mostra as últimas 20
  linhas do `stdout`, para ajustar a regex).

### Limitações

- **Quem começa não pode ser escolhido** pela CLI do Forge, então `GameSpec.on_play` é ignorado. Os
  jogos de uma chamada formam um único *match* do Forge: o primeiro começa por sorteio e, nos
  seguintes, começa o perdedor do jogo anterior do lote (que pertence a outra série).
- **A IA do Forge não faz sideboard.** Por isso a série Bo3 é orquestrada em Python, com cada fase
  (G1, G2, G3) jogada como um lote separado com o deck correto.
- **A IA não pilota todos os decks bem**, em especial os de combo. Use `--game1-check` antes de
  confiar em um confronto.
- **Empates** contam como não-vitória.
- O `-d` com caminho arbitrário é ignorado pela versão 2.0.15, por isso os decks vão para a pasta
  do perfil. Eles são referenciados pelo nome do arquivo **com extensão**, para que o Forge leia só
  aquele arquivo e não a pasta inteira, o que quebraria com vários workers.

### Custos medidos (Forge 2.0.15, execução serial)

| Item | Tempo |
|---|---|
| Inicialização da JVM por chamada | ~16 s |
| Jogo | ~3,5 s |

## Escrevendo um motor novo

Basta herdar de `MatchEngine` e implementar `play_games`. Os testes usam motores falsos:

- `ScriptedEngine`: resultado por número do jogo;
- `CoinEngine`: moeda viciada, em que o deck não importa;
- `WearTearEngine`: só Wear // Tear muda a chance de vitória.

Esse padrão serve para verificar propriedades do pipeline sem o Forge.
