# 04 · Atributos e decodificação

Módulos: `tccmagic/attributes.py` e `tccmagic/decoder.py`.

## Os 9 atributos

Cada carta c é um vetor **v(c) ∈ [0, 1]⁹**. A ordem abaixo é a ordem dos genes no cromossomo e dos
pesos no decodificador (`ATTRIBUTES`).

| i | Nome no código | Significado | Origem |
|---|---|---|---|
| 1 | `eficiencia_mana` | Custo baixo | **Derivado:** `max(0, 1 − CMC/6)` |
| 2 | `remocao` | Remoção pontual de criaturas/permanentes | Anotado |
| 3 | `anti_aggro` | Ganho de vida, sweepers, bloqueadores | Anotado |
| 4 | `anti_combo` | Hate pieces, taxação, Blood Moon | Anotado |
| 5 | `anti_cemiterio` | Exílio de cemitério | Anotado |
| 6 | `anti_artefato_encantamento` | Destruição de artefatos/encantamentos | Anotado |
| 7 | `interacao_pilha` | Counterspells e interação na pilha | Anotado |
| 8 | `vantagem_cartas` | Geração de valor / card advantage | Anotado |
| 9 | `pressao` | Ameaça / clock | Anotado |

Regras de `build_vector(cmc, annotated)`:

- `eficiencia_mana` vale 1 em CMC 0, cai linearmente e chega a 0 em CMC 6
  (`MAX_CMC_FOR_EFFICIENCY = 6`). **Não pode** ser anotada à mão.
- Atributos ausentes valem 0.
- Nome desconhecido ou valor fora de [0, 1] gera `ValueError`, para que erros de digitação não
  passem despercebidos.
- Terrenos têm vetor nulo.

## Decodificação: cromossomo → sideboard

`SideboardDecoder.decode(keys)` faz três passos.

### 1. Chaves → pesos

```
w_i = 20 · k_i − 10        k_i ∈ [0, 1]   →   w_i ∈ [−10, +10]
```

(`keys_to_weights`). Uma chave 0,5 vale peso 0. Pesos negativos **penalizam** o atributo.

### 2. Score de cada entrada do pool

```
Score(c, k) = Σ_i w_i · v_i(c) − δ · (k − 1)
```

- `k` é o índice da cópia (1 para a primeira, 2 para a segunda...);
- `δ` é a penalidade por cópia (`copy_penalty`, padrão 1,0).

Com δ > 0, a segunda cópia de uma carta só entra se ainda superar as alternativas (retornos
decrescentes), o que gera sideboards mais diversificados. Com δ = 0, todas as cópias de uma carta
empatam e entram juntas.

Na implementação, `V` é a matriz (nº de entradas × 9) pré-computada e
`scores = V @ w − penalidades`.

### 3. Top-15

As entradas são ordenadas por Score decrescente e as 15 primeiras formam o sideboard. Empates são
desfeitos de forma determinística: nome da carta, depois índice da cópia.

**Legalidade por construção:** como o pool foi expandido em entradas por cópia, já limitadas pela
regra de 4 cópias, o Top-15 nunca repete entrada e nunca excede o número de cópias permitido.

## Exemplo

Com todos os pesos 0, exceto `anti_cemiterio = +10`, o Top-15 começa por Rest in Peace (v₅ = 1,0)
e Sanctifier en-Vec (v₅ = 0,5). É isso que o teste `test_graveyard_weight_selects_graveyard_hate`
verifica.

## Resultado da decodificação: `DecodedSideboard`

| Campo / método | Conteúdo |
|---|---|
| `weights` | Os 9 pesos |
| `slots` | As 15 entradas, em ordem de Score |
| `scores` | O Score de cada entrada |
| `cards` | As 15 `Card` |
| `key` | Tupla ordenada dos rótulos das entradas: identidade do sideboard, usada como chave de cache |
| `weights_by_attribute()` | `{atributo: peso}` |
| `card_counts()` | `[(carta, cópias)]` na ordem do ranking |

## Espaço de busca

Com o pool atual (21 entradas, 15 vagas), uma amostra de 50 mil cromossomos aleatórios decodificou
para **1.311 sideboards distintos**. Muitos vetores de pesos levam ao mesmo Top-15, e por isso o
cache de sideboards ([09](09-fitness-reamostragem-paralelismo.md)) é eficaz.
