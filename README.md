# TCCMagic: otimização de sideboard em MTG (Modern) via BRKGA-A

Pipeline em Python que otimiza um **sideboard de 15 cartas** para um **maindeck fixo de 60 cartas**
(Boros Energy, formato Modern). O cromossomo usa **codificação por atributos (BRKGA-A)**: o algoritmo
aprende pesos para 9 atributos de carta, e não IDs de cartas. O valor de cada sideboard é medido pela
taxa de vitória em séries **Melhor de 3** contra uma suíte de oponentes do metajogo.

> Documentação completa, organizada por tema: [DOCS/README.md](DOCS/README.md).

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
  --forge-dir /opt/forge --matches 30 --population 16 --generations 8 --workers 4

# Antes de otimizar: mede só o Game 1 (maindeck vs. cada oponente), com IC de 95%
python main.py --engine forge --game1-check 100 --workers 4
```

Opções ligadas ao ruído das partidas simuladas:

| Opção | Efeito |
|---|---|
| `--matches N` | séries Bo3 por oponente em cada rodada de avaliação |
| `--validation-matches N` | séries novas por oponente na validação final (padrão: 5 × `--matches`) |
| `--resample` / `--no-resample` | reavaliar a população a cada geração (padrão: ligado no Forge) |
| `--game1-check N` | joga N Games 1 contra cada oponente e sai, sem otimizar |
| `--plan aleatorio\|afinidade` | plano de troca nos Games 2/3 (padrão: `aleatorio`) |
| `--plan-block N` | séries consecutivas que compartilham o mesmo sorteio de trocas (padrão: 10) |
| `--plan-seed N` | semente dos sorteios de troca |

## Estrutura

| Arquivo | Papel |
|---|---|
| `tccmagic/attributes.py` | Os 9 atributos e a vetorização v(c) ∈ [0,1]^9 |
| `tccmagic/cards.py` | Banco de dados: `Card`, `Deck`, `Opponent`, `Database`, pool expandido por cópia |
| `tccmagic/data/*.json` | Maindeck, pool de candidatas, oponentes e tabela de afinidade por arquétipo |
| `tccmagic/decoder.py` | Chaves → pesos → Score → Top-15 |
| `tccmagic/brkga.py` | `BRKGA_Optimizer` genérico (elite 20%, mutantes 15%, cruzamento 65%, ρ = 0,70) |
| `tccmagic/sideboarding.py` | Planos de troca para os Games 2/3 (sorteado ou por afinidade) |
| `tccmagic/analysis.py` | Efeito estimado de cada carta que entra/sai, a partir das trocas sorteadas |
| `tccmagic/simulation/` | Motores (`SurrogateEngine`, `ForgeEngine`) e orquestração `Bo3Simulator` |
| `tccmagic/fitness.py` | Fitness com cache, reamostragem e `ProcessPoolExecutor` |
| `tccmagic/pipeline.py` | Experimento completo, histórico por geração e validação final |
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
probabilidade 0,70. Há parada antecipada opcional (`--stall N`).
O otimizador não sabe nada de Magic: recebe apenas uma função `população → fitness`.

Com fitness determinístico (motor substituto) os elites não são reavaliados. Com fitness ruidoso
(Forge), `reevaluate_elites=True` reavalia a população inteira a cada geração e, ao final, joga uma
rodada extra só para a elite antes de escolher o melhor. Nesse modo o melhor fitness pode cair de
uma geração para a outra, e a parada antecipada conta gerações sem troca de líder.

## 4. Simulação Bo3 e fitness

- **Game 1**: maindeck vs. oponente. Quem começa alterna entre as séries (equilíbrio play/draw exato).
  É calculado uma única vez, porque o maindeck não muda.
- **Games 2 e 3**: deck pós-sideboard montado pelo plano de troca. O perdedor do jogo anterior
  começa. O Game 3 só acontece em série 1–1.
- **Terrenos nunca saem.** Só cartas marcadas `"flex": true` podem sair, e um terreno marcado como
  flex é recusado no carregamento: a base de mana mantém a mesma quantidade de terrenos.
- **Plano aleatório** (`--plan aleatorio`, padrão): nenhuma regra fixa decide a troca. Para cada
  bloco de `--plan-block` séries sorteia-se o número de trocas (1 a `--max-swaps`), quais cópias
  do sideboard entram (sorteio uniforme entre as 15) e quais cópias flex do maindeck saem. Uma
  carta nunca sai para dar lugar a ela mesma. O sorteio depende só de (semente, oponente, bloco),
  e não do sideboard: dois sideboards que contêm as cartas sorteadas recebem o mesmo plano
  (números aleatórios comuns). O fitness passa a medir quanto o sideboard rende quando as trocas
  são feitas às cegas, e o efeito de cada carta é estimado depois (seção abaixo).
- **Plano por afinidade** (`--plan afinidade`):
  `Rel(c, A) = [Σ_{i=2..9} a_i · v_i(c)] · (1 + a_1 · v_1(c))`, com `a = afinidade[A]`. A melhor
  carta do side entra no lugar da pior carta `flex` do main enquanto `Rel(entra) > Rel(sai)`, até
  `--max-swaps` trocas. O plano é o mesmo em todas as séries contra o oponente.
- **Fitness** = WinRate_Bo3 ponderada pela participação no metajogo. Como WinRate_Md1 é constante
  entre indivíduos, maximizar Bo3 equivale a maximizar **ΔWinRate = WinRate_Bo3 − WinRate_Md1**.
- **Cache de sideboards**: vários vetores de pesos geram o mesmo Top-15, e os resultados de cada
  sideboard distinto são guardados e reaproveitados.
- **Cache de jogos**: o resultado de um jogo depende só do deck pós-side, e não do sideboard que o
  originou. Cada jogo fica guardado por (oponente, deck, série, jogo, quem começa), e sideboards
  diferentes que levam ao mesmo deck reaproveitam os jogos em vez de simulá-los de novo. Em cada
  fase (todos os G2, depois todos os G3) os jogos que faltam são agrupados em um lote por
  (oponente, deck), ou seja, uma chamada ao Forge por deck distinto.
- **Reamostragem** (motores estocásticos): a cada geração, todo sideboard da população joga mais uma
  rodada de `--matches` séries, somada às anteriores. O fitness é a taxa acumulada, então um
  sideboard que teve sorte em poucas séries regride à sua taxa real em vez de ficar no topo.
- **Paralelismo**: os lotes de jogos são distribuídos com `ProcessPoolExecutor` (`--workers`).

### Efeito das trocas sorteadas

Com o plano aleatório, todos os jogos pós-side simulados (busca e validação, cada jogo contado uma
vez) formam um experimento aleatorizado. Para cada oponente ajusta-se

```
P(vitória) = α + Σ_c β_c · (cópias de c que entraram) − Σ_f γ_f · (cópias de f que saíram)
```

com a média dos γ (ponderada pelas cópias flex) fixada em zero, já que toda troca põe uma carta e
tira outra. O relatório, o JSON (`swap_analysis`) e a aba `Efeito_Trocas` do XLSX trazem:

- **entra**: β_c, o ganho por jogo ao colocar uma cópia de c no lugar de uma carta flex qualquer;
- **sai**: −γ_f, o ganho ao tirar f em vez de uma flex qualquer (positivo = f faz pouca falta);
- erro padrão robusto (HC1), IC de 95% e a média ponderada pelo metajogo de cada carta.

Os intervalos tratam os jogos como independentes. G2 e G3 da mesma série compartilham o plano, então
os intervalos são um pouco otimistas.

**Custo no Forge.** Cada deck distinto custa uma inicialização da JVM (~16 s). Com `--plan-block 10`
e 30 séries, cada sideboard joga 3 decks por oponente e rodada, em vez de 1. O cache de jogos
compensa parte disso, porque sideboards parecidos sorteiam os mesmos decks.

### Validação final

O fitness do melhor indivíduo da busca é **otimista por construção**: é o máximo de muitas
estimativas ruidosas. Por isso os números do relatório não saem da busca. Ao final, o sideboard
escolhido e a linha de base **sem sideboard** (Games 2/3 com o maindeck) jogam
`--validation-matches` séries novas por oponente, sobre os mesmos Games 1, e o relatório traz:

- WinRate Md1, Bo3 e ΔWinRate da validação, com erro padrão;
- o **ganho atribuível ao sideboard** (Bo3 com side − Bo3 sem side) com intervalo de confiança de
  95% (conservador: ignora que os Games 1 são compartilhados);
- se o intervalo inclui zero, o ganho não é distinguível do ruído com aquelas séries.

O erro padrão do fitness de uma rodada é de até `0,5 · sqrt(Σ share² / n)`, cerca de `0,22/√n`
com cinco oponentes de peso parecido: ±0,16 com 2 séries, ±0,04 com 30, ±0,02 com 100.

> **Cuidado ao interpretar ΔWinRate.** Mesmo sem sideboard, a taxa de vitória de séries Bo3 difere
> da taxa por jogo: o formato amplifica taxas diferentes de 50%, e o oponente também faz sideboard.
> Por isso a medida mais limpa do efeito das 15 cartas é o ganho sobre a linha de base
> "Bo3 sem sideboard", e não o ΔWinRate.

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

- a CLI não permite escolher quem começa, então o play/draw é ignorado. Os jogos de uma chamada
  `-n` formam um único *match* do Forge: o primeiro começa por sorteio e, nos seguintes, começa o
  perdedor do jogo anterior do lote;
- a IA do Forge não pilota bem todos os decks (em especial os de combo). Use `--game1-check` para
  ver a taxa de vitória do Game 1 por oponente antes de confiar em um confronto;
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
