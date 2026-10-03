# 07 · Planos de sideboarding

Módulo: `tccmagic/sideboarding.py`. O modo é escolhido com `--plan` / `ExperimentConfig.plan`.

Um **plano** diz o que entra e o que sai entre o Game 1 e os Games 2/3. É representado por
`SideboardPlan`:

| Campo / propriedade | Conteúdo |
|---|---|
| `archetype` | Arquétipo do oponente |
| `cards_in`, `cards_out` | Cartas que entram e que saem (mesmo número) |
| `deck` | Deck pós-side de 60 cartas |
| `n_swaps` | Número de trocas |
| `signature` | `(nomes que entram ordenados, nomes que saem ordenados)`, a identidade do deck |
| `describe()` | Texto "+2 X, +1 Y" / "−3 Z" |

## Regras comuns aos dois modos

- **Terrenos nunca saem.** Só saem cópias `flex` do maindeck, e `Deck.flex_cards()` exclui
  terrenos. Um terreno marcado como `flex` no JSON é recusado no carregamento.
- O deck pós-side tem sempre 60 cartas.
- No máximo `max_swaps` trocas (padrão 5).

## Plano aleatório (`aleatorio`, padrão)

Nenhuma regra fixa decide a troca. O objetivo é **medir** o efeito de cada carta em vez de
supô-lo.

### Sorteio

Para cada bloco de `plan_block` séries consecutivas, contra cada oponente:

1. **Número de trocas:** `k = 1 + ⌊u · max_swaps⌋`, uniforme em 1..`max_swaps`.
2. **O que entra:** cada cópia do sideboard ("Blood Moon #1", "Blood Moon #2", ...) recebe uma
   prioridade aleatória, e entram as `k` de menor prioridade. Para um sideboard fixo, isso é um
   **sorteio uniforme de k entre as 15 cópias**.
3. **O que sai:** cada cópia flex do maindeck recebe uma prioridade, e saem as `k` de menor
   prioridade. Ficam de fora as cartas com o mesmo nome de uma que está entrando: Blood Moon do side
   nunca substitui Blood Moon do main, porque seria uma troca nula.

Todas as prioridades vêm de `_hash_unit("semente|oponente|bloco|rótulo")`.

### Números aleatórios comuns

A prioridade depende **só do rótulo da cópia**, não do sideboard. Logo, se dois sideboards contêm
as cartas sorteadas para um bloco, os dois recebem **exatamente o mesmo plano** e, portanto, o
mesmo deck. Isso tem dois efeitos:

- o **cache de jogos** reaproveita as partidas entre sideboards parecidos
  ([06](06-simulacao-bo3.md#cache-de-jogos));
- a comparação entre sideboards fica menos ruidosa, porque eles enfrentam as mesmas trocas.

### Por que blocos de séries

Cada deck distinto exige uma chamada separada ao Forge, com cerca de 16 s de inicialização da JVM.
Sortear um plano por série multiplicaria esse custo. Com `plan_block = 10` e 30 séries, cada
sideboard usa 3 decks por oponente e rodada. Blocos menores dão mais combinações de troca para a
análise, mas custam mais tempo.

### O que muda no significado do fitness

Com trocas sorteadas, o fitness mede **quanto o sideboard rende quando as trocas são feitas às
cegas**. Sideboards cheios de cartas úteis em vários confrontos são favorecidos. O resultado mais
útil para decidir as trocas passa a ser a **tabela de efeitos**
([10](10-validacao-e-analise-de-trocas.md#análise-das-trocas-sorteadas)).

## Plano por afinidade (`afinidade`)

Plano determinístico e explicável, baseado na tabela `archetypes.json`.

### Relevância de uma carta contra um arquétipo

```
Rel(c, A) = [Σ_{i=2..9} a_i · v_i(c)] · (1 + a_1 · v_1(c))        a = afinidade[A]
```

Os atributos funcionais (2–9) dizem **se** a carta faz algo contra o arquétipo. A eficiência de
mana (atributo 1) só **amplifica** esse valor. Uma carta barata sem função no confronto tem
relevância zero.

### Trocas

1. O sideboard é ordenado por relevância decrescente, e as cópias flex por relevância crescente.
2. Troca-se par a par (melhor do side ↔ pior do main) enquanto
   `Rel(entra) > Rel(sai) + swap_margin` e o limite de trocas não foi atingido.
3. A ordenação desempata por nome, o que deixa o plano determinístico.

O plano é o mesmo em todas as séries contra o oponente.

### Limitação observada

A tabela é um modelo simplificado do conhecimento do jogador e pode errar. No experimento com o
Forge ([14](14-experimentos-e-limitacoes.md)), o plano contra Domain Zoo tirava Blood Moon (a
relevância dela contra "aggro" é zero, porque o único atributo dela é `anti_combo`) e as 4 Voice of
Victory, e piorou o confronto em 17 pp. Essa foi a motivação para o plano aleatório.

## Comparação

| | `aleatorio` | `afinidade` |
|---|---|---|
| Quem decide as trocas | Sorteio | Tabela arquétipo × atributo |
| Plano entre séries | Muda a cada bloco | Fixo por oponente |
| Depende de conhecimento anotado | Não | Sim (`archetypes.json`) |
| Análise de efeito por carta | Sim | Não (sem variação aleatória, não há como separar os efeitos) |
| Custo no Forge | Maior (um deck por bloco) | Menor (um deck por oponente) |
