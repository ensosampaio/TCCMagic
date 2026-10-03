# 02 · Instalação e execução

## Requisitos

| Item | Versão | Uso |
|---|---|---|
| Python | 3.10 ou mais recente (testado com 3.13) | Todo o projeto |
| `numpy` | ≥ 1.24 | Vetores, regressão, BRKGA |
| `openpyxl` | ≥ 3.1 | Exportação `.xlsx` |
| `pytest` | ≥ 7.0 | Testes |
| Java + MTG Forge | Forge 2.0.15 testado | Apenas para `--engine forge` |

```bash
pip install -r requirements.txt
python -m pytest            # 40 testes, cerca de 3 s
```

## Modos de execução

### Menu interativo

```bash
python main.py
```

| Opção | O que faz |
|---|---|
| 1 | Roda com o simulador substituto (segundos a minutos) |
| 2 | Roda com o Forge. Sugere 30 séries por oponente, população 16, 8 gerações e 4 workers, e pergunta cada parâmetro com explicação |
| 3 | Teste rápido do Forge: 2 séries, população 4, 1 geração, saída em `resultados_teste`. Serve só para verificar a integração |
| 4 | Mostra os dados carregados (maindeck, pool, oponentes) |
| 5 | Mede só o Game 1 no Forge (maindeck vs. cada oponente), com IC de 95% |
| 0 | Sair |

Antes de iniciar uma execução com o Forge, o menu mostra uma **estimativa de tempo** (limite
superior, que ignora o cache). Ela usa 16 s de inicialização da JVM por chamada e 3,5 s por jogo.

### Linha de comando

Com qualquer argumento, o menu é pulado:

```bash
python main.py --engine surrogate --generations 100 --workers 4
python main.py --engine forge --matches 30 --population 16 --generations 8 --workers 4
python main.py --engine forge --game1-check 100 --workers 4     # só mede o Game 1
python main.py --engine forge --plan afinidade                  # plano de troca antigo
```

## Todas as opções

### Motor e saída

| Opção | Padrão | Descrição |
|---|---|---|
| `--engine {surrogate,forge}` | `surrogate` | Motor de partidas |
| `--forge-jar CAMINHO` | variável `FORGE_JAR` ou a instalação local | JAR do Forge (`forge-gui-desktop-*-jar-with-dependencies.jar`) |
| `--forge-dir CAMINHO` | variável `FORGE_DIR` ou a instalação local | Diretório de instalação do Forge (usado como `cwd`) |
| `--workers N` | 1 | Processos paralelos. Com o Forge, cada um usa até 4 GB de RAM |
| `--out PASTA` | `resultados` | Onde gravar `resultado.json` e `resultado.xlsx` |

### BRKGA

| Opção | Padrão | Descrição |
|---|---|---|
| `--population N` | 50 | Indivíduos por geração |
| `--generations N` | 40 | Gerações após a população inicial. O histórico tem N+1 linhas (geração 0 a N) |
| `--elite F` | 0,20 | Fração de elite |
| `--mutants F` | 0,15 | Fração de mutantes |
| `--rho F` | 0,70 | Probabilidade de herdar cada gene do pai elite |
| `--stall N` | desligado | Para após N gerações sem melhora (ou sem troca de líder, com fitness ruidoso) |
| `--seed N` | 42 | Semente do BRKGA |
| `--copy-penalty F` | 1,0 | δ: a k-ésima cópia de uma carta recebe Score − δ·(k−1) |

### Simulação e ruído

| Opção | Padrão | Descrição |
|---|---|---|
| `--matches N` | 100 | Séries Bo3 por oponente em cada rodada de avaliação |
| `--validation-matches N` | 5 × `--matches` | Séries novas por oponente na validação final |
| `--resample` / `--no-resample` | automático | Reavalia a população a cada geração, acumulando séries. Automático = ligado no Forge, desligado no substituto |
| `--game1-check N` | — | Joga N Games 1 contra cada oponente, mostra as taxas com IC de 95% e sai |
| `--sim-seed N` | 12345 | Semente do simulador substituto |

### Plano de troca (Games 2/3)

| Opção | Padrão | Descrição |
|---|---|---|
| `--plan {aleatorio,afinidade}` | `aleatorio` | Sorteia o que entra e o que sai, ou usa a tabela de afinidade. Ver [07](07-planos-de-sideboarding.md) |
| `--plan-block N` | 10 | Séries consecutivas que compartilham o mesmo sorteio (só no plano aleatório) |
| `--plan-seed N` | 2024 | Semente dos sorteios de troca |
| `--max-swaps N` | 5 | Máximo de cartas trocadas por série |

## Uso como biblioteca

```python
from tccmagic.brkga import BRKGAConfig
from tccmagic.pipeline import ExperimentConfig, run_experiment
from tccmagic.export import export_json, export_xlsx

config = ExperimentConfig(
    engine="surrogate",
    matches_per_opponent=40,
    plan="aleatorio",
    brkga=BRKGAConfig(population_size=30, generations=10, seed=1),
)
result = run_experiment(config, progress=print)
print(result.validation.gain, result.validation.significant)
export_json(result, "resultados/resultado.json")
export_xlsx(result, "resultados/resultado.xlsx")
```

`ExperimentConfig` aceita os mesmos parâmetros da CLI. A lista completa de campos está em
[12 · Referência de API](12-referencia-de-api.md#pipelinepy).

## O que aparece no terminal

1. **Uma linha por geração:** melhor fitness, média ± desvio da população, Md1/Bo3/ΔWR do melhor,
   número de séries acumuladas pelo melhor (`n=`), jogos simulados e reaproveitados do cache,
   tempo decorrido.
2. **Pesos finais** de cada atributo, com barra proporcional.
3. **Sideboard otimizado:** as 15 entradas em ordem de Score e a lista compacta.
4. **Desempenho por confronto na validação:** Md1, Bo3, pós-side, ΔWR e Bo3 sem side, com as
   cartas que entram e saem. No plano aleatório, os números são cópias médias por série.
5. **Resumo:** fitness da busca (otimista), validação, ganho atribuível ao sideboard com IC de
   95%, tempo total e aproveitamento do cache de jogos.
6. **Efeito das trocas sorteadas** (só no plano aleatório): por oponente e para o metajogo.

> **Windows:** se a saída for redirecionada para um arquivo ou pipe e der `UnicodeEncodeError`,
> rode com `PYTHONIOENCODING=utf-8`. No terminal normal isso não é necessário.

## Quanto tempo leva no Forge

Estimativa do menu para 30 séries por oponente, população 16, 8 gerações e 4 workers (pior caso,
sem cache):

| Plano | Estimativa |
|---|---|
| `afinidade` | ~9,9 h |
| `aleatorio`, `--plan-block 10` | ~13,5 h |
| `aleatorio`, `--plan-block 15` | ~11,7 h |
| `aleatorio`, `--plan-block 30` | ~10,0 h |

No plano aleatório, cada bloco de séries usa um deck diferente, e cada deck distinto custa uma
inicialização da JVM. Blocos maiores são mais rápidos, mas sorteiam menos combinações de troca.
