# TCCMagic: otimização de sideboard em MTG (Modern) via BRKGA-A

Pipeline em Python que otimiza um **sideboard de 15 cartas** para um **maindeck fixo de 60 cartas**
(Boros Energy, formato Modern). O cromossomo usa **codificação por atributos (BRKGA-A)**: o algoritmo
aprende pesos para 9 atributos de carta, e não IDs de cartas. O valor de cada sideboard é medido pela
taxa de vitória em séries **Melhor de 3** contra uma suíte de oponentes do metajogo.

## Execução rápida

```bash
pip install -r requirements.txt
python main.py                              # simulador substituto, 40 gerações
python main.py --generations 100 --workers 4 --stall 25
python -m pytest                            # testes
```

A saída mostra o progresso por geração, os pesos finais, as 15 cartas escolhidas, o plano de
sideboarding por confronto e os arquivos exportados (`resultados/resultado.json` e `.xlsx`).

Com o MTG Forge instalado:

```bash
python main.py --engine forge \
  --forge-jar /opt/forge/forge-gui-desktop-X.Y.Z-jar-with-dependencies.jar \
  --forge-dir /opt/forge --matches 10 --population 20 --generations 15 --workers 4
```

## Estrutura

| Arquivo | Papel |
|---|---|
| `tccmagic/attributes.py` | Os 9 atributos e a vetorização v(c) ∈ [0,1]^9 |
| `tccmagic/cards.py` | Banco de dados: `Card`, `Deck`, `Opponent`, `Database`, pool expandido por cópia |
| `tccmagic/data/*.json` | Maindeck, pool de candidatas, oponentes e tabela de afinidade por arquétipo |
| `tccmagic/decoder.py` | Chaves → pesos → Score → Top-15 |
| `tccmagic/brkga.py` | `BRKGA_Optimizer` genérico (elite 20%, mutantes 15%, cruzamento 65%, ρ = 0,70) |
| `tccmagic/sideboarding.py` | Plano de troca por afinidade para os Games 2/3 |
| `tccmagic/simulation/` | Motores (`SurrogateEngine`, `ForgeEngine`) e orquestração `Bo3Simulator` |
| `tccmagic/fitness.py` | Fitness com cache e `ProcessPoolExecutor` |
| `tccmagic/pipeline.py` | Experimento completo e histórico por geração |
| `tccmagic/export.py` | Exportação JSON / XLSX |
| `main.py` | Exemplo executável (`if __name__ == "__main__"`) |

## 1. Atributos (codificação)

| i | Atributo | Significado |
|---|---|---|
| 1 | `eficiencia_mana` | `max(0, 1 − CMC/6)`, **derivado** do custo |
| 2 | `remocao` | remoção pontual |
| 3 | `anti_aggro` | ganho de vida, sweepers, bloqueadores |
| 4 | `anti_combo` | hate pieces, taxação, Blood Moon |
| 5 | `anti_cemiterio` | exílio de cemitério |
| 6 | `anti_artefato_encantamento` | destruição de artefatos/encantamentos |
| 7 | `interacao_pilha` | counterspells / interação na pilha |
| 8 | `vantagem_cartas` | card advantage |
| 9 | `pressao` | ameaça / clock |

Os atributos 2–9 são anotados à mão em `tccmagic/data/sideboard_pool.json` e
`maindeck_boros_energy.json`. Atributo desconhecido ou valor fora de [0,1] gera erro no carregamento.

## 2. Decodificação

1. `w_i = 20·k_i − 10`, com `k_i ∈ [0,1]` e `w_i ∈ [−10, +10]`
2. `Score(c) = Σ w_i · v_i(c)`
3. Ordena por Score decrescente e seleciona as 15 primeiras entradas

**Cópias:** o pool é expandido em entradas por cópia ("Rest in Peace #1", "#2", …), limitadas por
`max_copies` e pela regra de 4 cópias somando o maindeck. O Top-15 nunca repete entrada e é sempre
legal. A k-ésima cópia recebe `Score − δ·(k−1)` (retornos decrescentes, `--copy-penalty`, padrão 1,0).
Com `δ = 0` a fórmula é a pura, e todas as cópias de uma carta empatam e entram juntas.

## 3. BRKGA

A cada geração a população é ordenada pelo fitness. Os 20% de elite passam intactos, 15% são mutantes
aleatórios e 65% são filhos de um pai elite com um não-elite; cada gene vem do pai elite com
probabilidade 0,70. Os elites não são reavaliados. Há parada antecipada opcional (`--stall N`).
O otimizador não sabe nada de Magic: recebe apenas uma função `população → fitness`.

## 4. Simulação Bo3 e fitness

- **Game 1**: maindeck vs. oponente. Quem começa alterna entre as séries (equilíbrio play/draw exato).
  É calculado uma única vez, porque o maindeck não muda.
- **Games 2 e 3**: deck pós-sideboard para o arquétipo do oponente. O perdedor do jogo anterior começa.
  O Game 3 só acontece em série 1–1.
- **Plano de sideboarding**: `Rel(c, A) = afinidade[A] · v(c)`. A melhor carta do side entra no lugar
  da pior carta `flex` do main enquanto `Rel(entra) > Rel(sai)`, até 5 trocas (`--max-swaps`).
- **Fitness** = WinRate_Bo3 ponderada pela participação no metajogo. Como WinRate_Md1 é constante
  entre indivíduos, maximizar Bo3 equivale a maximizar **ΔWinRate = WinRate_Bo3 − WinRate_Md1**.
- **Cache**: vários vetores de pesos geram o mesmo Top-15, e cada sideboard distinto é simulado uma
  única vez.
- **Paralelismo**: sideboards novos são distribuídos com `ProcessPoolExecutor` (`--workers`).

> **Cuidado ao interpretar ΔWinRate.** Mesmo sem sideboard, a taxa de vitória de séries Bo3 difere
> da taxa por jogo: o formato amplifica taxas diferentes de 50%, e o oponente também faz sideboard.
> Por isso o relatório inclui a linha de base **"Bo3 sem sideboard"** e o **ganho atribuível ao
> sideboard** (Bo3 com side − Bo3 sem side). Essa é a medida mais limpa do efeito das 15 cartas.

### Motor substituto (`--engine surrogate`)

Cada jogo é um sorteio de Bernoulli com

```
força(deck, opp) = Σ_i vuln_i(opp) · sat_i(deck)
  sat_1 = média de eficiencia_mana (não-terrenos)
  sat_i = 1 − exp(−Σ_c v_i(c) / κ_i)                 # retornos decrescentes
logit P(vitória) = base_logit(opp) + β·[força(deck) − força(maindeck)]
                   ± bônus de jogar primeiro − penalidade pós-side do oponente (G2/G3)
```

`vuln`, `base_logit` e `postboard_penalty` ficam em `opponents.json`; β, κ e o bônus ficam em
`SurrogateConfig`. O sorteio de cada jogo é fixado por (semente, oponente, série, jogo), ou seja,
usa *common random numbers*: sideboards diferentes enfrentam a mesma "sorte", e o fitness fica
determinístico e comparável. Esse motor serve para desenvolver e validar o pipeline. Os números
dele refletem as vulnerabilidades anotadas à mão e não substituem partidas reais.

### Motor Forge (`--engine forge`)

Grava os decks em `.dck`, executa `java -jar <forge.jar> sim -d A.dck B.dck -n N` via `subprocess`
(com o diretório do Forge como `cwd`) e extrai o vencedor de cada jogo do `stdout` por regex
(`ForgeConfig.win_pattern` / `draw_pattern`, configuráveis). Limitações:

- a CLI não permite escolher quem começa, então o play/draw é ignorado;
- a IA do Forge não faz sideboard, por isso cada fase (G1, G2, G3) roda como um lote separado
  com o deck correto;
- o texto de saída pode mudar entre versões do Forge. Se o parser falhar, `ForgeError` mostra o
  final do `stdout` para ajustar a regex;
- empates contam como não-vitória.

## Trocando dados

- **Outro maindeck:** crie um JSON no formato de `maindeck_boros_energy.json`, com 60 cartas e ao
  menos algumas marcadas como `"flex": true`, e passe `maindeck_file` em `ExperimentConfig`.
- **Pool / oponentes / afinidades:** edite os JSON em `tccmagic/data/`. As validações de 60 cartas,
  4 cópias e atributos válidos rodam no carregamento.
