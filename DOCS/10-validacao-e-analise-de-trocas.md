# 10 · Validação e análise das trocas

Depois da busca, o pipeline faz duas coisas: valida o melhor sideboard com séries novas e, no plano
aleatório, estima o efeito de cada carta trocada.

## Validação final

Módulos: `tccmagic/pipeline.py` (`Validation`) e `tccmagic/fitness.py` (`validate`).

### Por que validar

O fitness do melhor indivíduo é **otimista por construção**. Ele é o máximo de muitas estimativas
ruidosas, então quem fica no topo tende a ser quem teve sorte (maldição do vencedor). Por isso
**nenhum número do relatório final sai da busca**.

### Como funciona

1. Joga `validation_matches` séries **novas** por oponente. O padrão é 5 × `matches_per_opponent`.
   Os índices começam em `VALIDATION_MATCH_OFFSET = 1.000.000.000`, longe dos da busca, então o
   substituto gera jogos novos e o plano aleatório sorteia blocos novos.
2. Joga Games 1 novos, compartilhados pelos dois candidatos abaixo.
3. Avalia dois candidatos sobre os mesmos Games 1:
   - o **sideboard escolhido**;
   - a **linha de base sem sideboard**: Games 2/3 com o maindeck, sem nenhuma troca.

### Métricas

| Propriedade | Fórmula |
|---|---|
| `gain` | Bo3 com sideboard − Bo3 sem sideboard |
| `gain_stderr` | `hypot(stderr_sideboard, stderr_baseline)`. É conservador: ignora que os Games 1 são compartilhados |
| `gain_interval()` | `gain ± 1,96 · gain_stderr` |
| `significant` | O IC de 95% exclui zero |

> **Por que comparar com a linha de base, e não usar ΔWinRate?** Mesmo sem sideboard, a taxa de
> séries Bo3 difere da taxa por jogo: o formato Melhor de 3 amplifica taxas diferentes de 50%, e o
> oponente também faz sideboard. O ganho sobre "Bo3 sem sideboard" isola o efeito das 15 cartas.

No plano aleatório, a validação mede o sideboard **com trocas sorteadas**, ou seja, quanto ele
rende quando as trocas são feitas às cegas.

## Análise das trocas sorteadas

Módulo: `tccmagic/analysis.py`. Só roda no plano `aleatorio`. No plano por afinidade, as trocas
não variam aleatoriamente e os efeitos não podem ser separados.

### Dados

Todos os jogos pós-side de `Bo3Simulator.games` (busca e validação, incluindo a linha de base sem
trocas), **cada jogo contado uma única vez**, mesmo que tenha sido reaproveitado por vários
sideboards.

Como as trocas são sorteadas, não há um jogador escolhendo as cartas "certas" para cada confronto.
A associação entre trocar uma carta e vencer pode então ser lida como **efeito causal**.

### Modelo (por oponente)

Probabilidade linear, ajustada por mínimos quadrados:

```
P(vitória) = α + Σ_c β_c · (cópias de c que entraram) − Σ_f γ_f · (cópias de f que saíram)
```

**Identificação.** Toda troca põe uma carta e tira outra, então somar a mesma constante a todos os
β e γ não muda nenhuma previsão. Só diferenças entre cartas são identificáveis. A normalização
adotada é que **a média dos γ, ponderada pelas cópias flex do maindeck, seja zero**. Na prática, o
modelo é ajustado com a primeira carta que sai como referência (γ = 0) e depois reparametrizado.
As covariâncias são transformadas pela mesma matriz linear.

### Interpretação

| Papel | Valor reportado | Leitura |
|---|---|---|
| `entra` | β_c | Ganho, em probabilidade de vitória por jogo, de colocar **uma cópia** de c no lugar de uma carta flex qualquer do maindeck |
| `sai` | −γ_f | Ganho de tirar f em vez de uma flex qualquer. **Positivo** = f é das que menos fazem falta contra aquele oponente |
| — | α (`no_swap_winrate`) | Taxa estimada sem nenhuma troca |

**Exemplo:** "Wear // Tear entra +12 pp ± 6 contra Bogles" significa que cada cópia de Wear // Tear
que entra no lugar de uma carta flex média aumenta a chance de vencer cada jogo pós-side em cerca
de 12 pontos percentuais. O intervalo de 95% vai de +6 a +18 pp.

### Erros padrão

- **HC1** (robustos à heterocedasticidade, inevitável com resposta binária):
  `cov = (XᵀX)⁻¹ · Xᵀ diag(e²) X · (XᵀX)⁻¹ · n/(n−p)`.
- Se a matriz for degenerada (poucos dados ou uma carta sem variação), os coeficientes saem por
  mínimos quadrados de norma mínima e os erros viram `NaN`.
- Os jogos são tratados como independentes. G2 e G3 da mesma série compartilham o plano, então os
  intervalos são **um pouco otimistas**.

### Efeito no metajogo

`metagame_effects()` combina o efeito de **colocar** cada carta contra todos os oponentes:

```
efeito = Σ_opp (share/Σshare) · β_c,opp        erro = sqrt(Σ (share/Σshare)² · se²)
```

Só entram cartas estimadas contra **todos** os oponentes. É a resposta direta para "qual carta
mais vale a pena ter no sideboard para este metajogo".

### Estruturas

- `SwapEffect`: `opponent`, `card`, `role` (`entra`/`sai`), `games` (jogos em que ao menos uma
  cópia entrou/saiu), `winrate` (taxa bruta nesses jogos), `effect`, `stderr`, `ci95`,
  `significant`.
- `OpponentSwapAnalysis`: `opponent`, `archetype`, `meta_share`, `games`, `winrate` (pós-side
  bruta), `no_swap_winrate` (α), `effects`. `role("entra")` e `role("sai")` devolvem os efeitos
  ordenados do maior para o menor.

### Precisão esperada

A precisão depende do número de **jogos distintos**. No teste com o substituto, cada carta teve de
100 a 900 jogos por oponente, e os intervalos ficaram em torno de ±5 a ±10 pp. Com o Forge, efeitos
de poucos pontos percentuais só aparecem com bastante jogo acumulado. Mais gerações ou mais séries
por rodada aumentam a amostra.

O teste `test_swap_analysis_recovers_the_effect_of_a_card` usa um motor em que só Wear // Tear
importa (+15 pp por cópia) e confirma que a regressão recupera esse efeito, com os demais perto de
zero.
