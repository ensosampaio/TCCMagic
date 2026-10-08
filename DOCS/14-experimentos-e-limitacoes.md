# 14 · Experimentos e limitações

## Experimento 1: Forge, plano por afinidade (outubro de 2026)

Arquivo: `resultados/resultado.json` (gravado em 2026-10-02).

> Este experimento é **anterior** ao plano aleatório e ao cache de jogos. Ele usou o plano por
> afinidade e o cache por sideboard. As conclusões abaixo motivaram essas duas mudanças.

### Configuração

| Parâmetro | Valor |
|---|---|
| Motor | Forge 2.0.15 |
| Séries por oponente por rodada | 30 |
| Séries de validação por oponente | 150 |
| População / gerações | 16 / 8 (histórico com as gerações 0 a 8) |
| Reamostragem | ligada |
| Workers | 4 |
| Tempo total | 8,5 h (~57 min por geração) |
| Sideboards distintos simulados | 111 |

### Sideboard final

2 The Legend of Roku, 2 Sanctifier en-Vec, 2 Obsidian Charmaw, 3 Blood Moon, 2 Wrath of the Skies,
2 Wear // Tear, 1 Vexing Bauble, 1 Rest in Peace.

### Resultado principal: não houve ganho

| | Busca | Validação |
|---|---|---|
| WinRate Md1 | 54,1% | 52,5% |
| WinRate Bo3 com o sideboard | 57,2% | 51,9% |
| Bo3 sem sideboard | — | 53,2% |
| **Ganho sobre a linha de base** | — | **−1,3 pp** (IC 95%: −5,9 a +3,4; não significativo) |

O fitness da busca (57,2%) não se sustentou fora da amostra.

### Convergência: o fitness ficou dentro do ruído

- Melhor fitness por geração entre 0,552 e 0,574, sem tendência. O melhor da geração 0 (0,571) era
  praticamente o final (0,574).
- Em todas as gerações o líder tinha `best_n_matches = 30`: era sempre um sideboard avaliado uma
  única vez. Os elites reavaliados regrediam à média (maldição do vencedor).
- A distância entre o melhor e a média ficou entre 1,1 e 1,6 desvios-padrão da população. Para o
  máximo de 16 sorteios de puro ruído, o esperado é cerca de 1,77σ. Os dados são compatíveis com
  nenhum indivíduo ser realmente melhor que outro.
- A queda de 5,3 pp entre busca e validação também é consistente com esse viés de seleção.

### Por confronto (validação, mesmos Games 1)

| Oponente | Bo3 com side | Bo3 sem side | Δ | Contribuição no total |
|---|---|---|---|---|
| Domain Zoo | 48,7% | 66,0% | **−17,3 pp** | −3,8 pp |
| Eldrazi Tron | 47,3% | 36,7% | **+10,7 pp** | +2,1 pp |
| Bogles | 24,7% | 22,0% | +2,7 pp | +0,5 pp |
| Esper Blink | 66,0% | 66,7% | −0,7 pp | −0,1 pp |
| Izzet Prowess | 74,7% | 74,7% | 0 | 0 |

- **Zoo:** perda real. Nos jogos pós-side caiu de 59,1% para 42,9% (cerca de 3,5σ).
- **Tron:** ganho plausível. Nos jogos pós-side subiu de 41,0% para 51,1% (cerca de 2,1σ). O plano
  foi +2 Blood Moon, +2 Charmaw e +1 Bauble.
- **Bogles** é o pior confronto (22–32%), e nada no pool resolve.

### Causa: o plano por afinidade

Contra Zoo, a tabela de afinidade produziu
`+2 Wrath of the Skies, +2 Sanctifier en-Vec, +1 Roku / −1 Blood Moon, −4 Voice of Victory`:

- **Blood Moon saiu**, embora seja forte contra a base de mana de Domain Zoo. O único atributo
  dela é `anti_combo`, que vale 0 para "aggro".
- **As 4 Voice of Victory saíram**, embora sejam úteis contra as respostas instantâneas de Zoo
  (Bolt, Stubborn Denial, Spell Snare).
- **Wrath of the Skies** num deck de criaturas baratas provavelmente faz a IA do Forge destruir o
  próprio campo.
- Zoo e Prowess recebem o mesmo plano (os dois são "aggro"), e a tabela não consegue
  diferenciá-los.

Além disso, Rest in Peace e High Noon quase não têm uso contra essa suíte (não há decks de
cemitério nem de combo). O fitness é indiferente a elas, e o BRKGA preenche esses slots por deriva
aleatória.

### Ineficiência encontrada (corrigida)

O resultado contra um oponente depende só do deck pós-side, mas o cache era por sideboard. Numa
amostra de 50 mil cromossomos havia 1.311 sideboards distintos, mas só **216 planos pós-side
distintos** somando os oponentes (Esper Blink: só 10). Isso motivou o
[cache de jogos](06-simulacao-bo3.md#cache-de-jogos).

### Mudanças feitas depois

| Problema | Mudança |
|---|---|
| Regra de troca fixa e errada em alguns confrontos | Plano **aleatório** como padrão, com análise do efeito de cada carta ([07](07-planos-de-sideboarding.md), [10](10-validacao-e-analise-de-trocas.md)) |
| Jogos repetidos para decks iguais | Cache de jogos por (oponente, deck, série) e lotes por deck ([06](06-simulacao-bo3.md)) |
| Terrenos poderiam sair se marcados como flex | Terrenos nunca saem ([07](07-planos-de-sideboarding.md#regras-comuns-aos-dois-modos)) |

## Limitações conhecidas

### Do método

- **Ruído:** com 30 séries por oponente, o fitness de uma rodada tem erro de cerca de ±4 pp.
  Diferenças menores entre sideboards só aparecem com muitas rodadas acumuladas.
- **Atributos anotados à mão:** os 9 atributos simplificam o que uma carta faz. Efeitos como
  "ataca bases de mana gananciosas" (Blood Moon contra Zoo) não têm atributo próprio.
- **Fitness do plano aleatório:** mede o sideboard com trocas às cegas, e não com as trocas que um
  jogador faria. A decisão de troca deve vir da tabela de efeitos.
- **Modelo da análise:** linear e aditivo. Não captura interações entre cartas, como duas cartas
  que só funcionam juntas. Os ICs tratam G2 e G3 da mesma série como independentes.

### Do Forge

- Não é possível escolher quem começa.
- A IA não faz sideboard e não pilota bem todos os arquétipos.
- Cerca de 16 s de inicialização da JVM por chamada, o que torna caros os planos que variam muito.
- Empates contam como derrota.

### Do metajogo

- Cinco oponentes, com participações fixas. O resultado vale para essa suíte.
- O oponente não faz sideboard real. No substituto, isso é modelado só como `postboard_penalty`.

## Próximos passos sugeridos

1. **Rodar o plano aleatório no Forge** e ler a tabela de efeitos por oponente, em especial Blood
   Moon e Voice of Victory contra Zoo, e Wear // Tear e Wrath contra Bogles.
2. **Plano aprendido:** usar a tabela de efeitos como plano de troca (entram as cartas de maior β
   e saem as de maior −γ) e validar contra a linha de base e contra o plano por afinidade.
3. **Validar o sideboard de referência** da lista original, para responder se o otimizador supera
   o sideboard humano. Implementado: `python main.py --compare`
   ([10](10-validacao-e-analise-de-trocas.md#comparação-de-sideboards)); falta rodar no Forge.
4. **Gastar simulações onde importa:** técnicas de *racing* ou OCBA, para concentrar séries nos
   candidatos próximos do topo.
5. **Ampliar o metajogo** com decks de cemitério e combo, para que cartas como Rest in Peace e
   High Noon tenham onde mostrar valor.
