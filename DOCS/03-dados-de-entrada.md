# 03 · Dados de entrada

Todos os dados ficam em `tccmagic/data/` e são carregados por `load_database()` em
`tccmagic/cards.py`. As validações rodam no carregamento: um arquivo inválido gera `ValueError` com
a causa, antes de qualquer simulação.

| Arquivo | Conteúdo |
|---|---|
| `maindeck_boros_energy.json` | Maindeck fixo de 60 cartas, com atributos e marcação `flex` |
| `sideboard_pool.json` | Cartas candidatas ao sideboard e o máximo de cópias de cada |
| `sideboard_referencia.json` | Sideboard da lista original (`cards`: carta → cópias, 15 no total, todas do pool). Não entra na busca: é um dos candidatos de `--compare` |
| `opponents.json` | Suíte de oponentes: arquétipo, participação, decklist e parâmetros do substituto |
| `archetypes.json` | Tabela de afinidade arquétipo × atributo (usada só no plano `afinidade`) |

## `maindeck_boros_energy.json`

```json
{
  "name": "Boros Energy",
  "cards": [
    {"name": "Ragavan, Nimble Pilferer", "count": 4, "cmc": 1, "flex": true,
     "attributes": {"pressao": 0.8, "vantagem_cartas": 0.4, "anti_combo": 0.2}},
    {"name": "Arid Mesa", "count": 4, "land": true}
  ]
}
```

| Campo | Obrigatório | Significado |
|---|---|---|
| `name` | sim | Nome da carta, exatamente como o Forge a conhece |
| `count` | sim | Número de cópias |
| `cmc` | não (padrão 0) | Custo de mana convertido. Define o atributo `eficiencia_mana` |
| `flex` | não (padrão `false`) | A carta pode sair no sideboarding |
| `land` | não (padrão `false`) | É terreno. Terrenos têm vetor de atributos nulo |
| `attributes` | não | Atributos 2–9 em [0, 1]. Ausentes valem 0 |

### Lista atual

| Carta | Cópias | Flex |
|---|---|---|
| Ragavan, Nimble Pilferer | 4 | sim |
| Guide of Souls | 4 | não |
| Ocelot Pride | 4 | não |
| Ajani, Nacatl Pariah | 4 | não |
| Voice of Victory | 4 | sim |
| Seasoned Pyromancer | 3 | sim |
| Ranger-Captain of Eos | 2 | sim |
| Solitude | 1 | sim |
| Galvanic Discharge | 4 | sim |
| Prismatic Ending | 1 | sim |
| Goblin Bombardment | 3 | sim |
| Thraben Charm | 2 | sim |
| Blood Moon | 1 | sim |
| Terrenos (10 nomes) | 23 | nunca |

São 37 mágicas (25 cópias flex) e 23 terrenos.

### Validações

- O deck tem exatamente 60 cartas.
- Nenhuma carta que não seja terreno básico passa de 4 cópias.
- **Terreno não pode ser `flex`.** A base de mana mantém sempre a mesma quantidade de terrenos nos
  Games 2/3. Além do bloqueio no carregamento, `Deck.flex_cards()` ignora terrenos.
- Há pelo menos uma carta `flex`.

## `sideboard_pool.json`

```json
{"cards": [
  {"name": "Blood Moon", "cmc": 3, "max_copies": 3, "attributes": {"anti_combo": 0.9}}
]}
```

| Campo | Significado |
|---|---|
| `max_copies` | Máximo de cópias no sideboard (padrão 4) |
| demais | Iguais ao maindeck |

O pool é **expandido em entradas por cópia** (`Database.sideboard_slots()`): "Blood Moon #1",
"#2", "#3". O número de entradas de cada carta é `min(max_copies, 4 − cópias no maindeck)`,
exceto para terrenos básicos. Por exemplo, Blood Moon tem 1 cópia no main e por isso no máximo 3
no side.

### Pool atual (21 entradas para 15 vagas)

| Carta | CMC | Máx. | Atributos |
|---|---|---|---|
| High Noon | 2 | 2 | anti_combo 0,8; remocao 0,3 |
| Sanctifier en-Vec | 3 | 2 | anti_aggro 0,6; anti_cemiterio 0,5; pressao 0,3 |
| Vexing Bauble | 1 | 2 | anti_combo 0,6; interacao_pilha 0,6 |
| Blood Moon | 3 | 3 | anti_combo 0,9 |
| Wear // Tear | 1 | 3 | anti_artefato_encantamento 1,0 |
| The Legend of Roku | 4 | 2 | vantagem_cartas 0,8; pressao 0,6 |
| Obsidian Charmaw | 3 | 2 | anti_combo 0,6; pressao 0,6 |
| Wrath of the Skies | 3 | 2 | anti_aggro 0,6; anti_artefato_encantamento 0,7; remocao 0,4 |
| Rest in Peace | 2 | 3 | anti_cemiterio 1,0; anti_combo 0,3 |

Validações: nomes não podem se repetir, e o pool precisa ter pelo menos 15 entradas legais.

## `opponents.json`

```json
{"opponents": [{
  "name": "Domain Zoo",
  "archetype": "aggro",
  "meta_share": 0.22,
  "surrogate": {
    "base_logit": 0.0,
    "postboard_penalty": 0.10,
    "vulnerability": {"eficiencia_mana": 0.8, "remocao": 0.9, "...": 0.0}
  },
  "decklist": {"Lightning Bolt": 4, "...": 0}
}]}
```

| Campo | Uso |
|---|---|
| `name` | Identificador do oponente nos relatórios |
| `archetype` | Chave da tabela de afinidade. Precisa existir em `archetypes.json` |
| `meta_share` | Peso no fitness. A soma deve ser 1 (verificada nos testes) |
| `decklist` | 60 cartas, gravadas em `.dck` para o Forge |
| `surrogate.base_logit` | Logit da vitória do Boros Energy no Game 1 (só no substituto) |
| `surrogate.postboard_penalty` | Ganho do oponente com o próprio sideboard nos Games 2/3 (só no substituto) |
| `surrogate.vulnerability` | Os 9 atributos: quanto cada um prejudica este oponente (só no substituto) |

### Suíte atual

| Oponente | Arquétipo | Participação | `base_logit` | `postboard_penalty` |
|---|---|---|---|---|
| Domain Zoo | aggro | 22% | 0,0 | 0,10 |
| Esper Blink | midrange | 18% | 0,0 | 0,15 |
| Eldrazi Tron | ramp | 20% | −0,1 | 0,15 |
| Izzet Prowess | aggro | 20% | 0,0 | 0,10 |
| Bogles | auras | 20% | 0,0 | 0,10 |

## `archetypes.json`

```json
{"affinity": {
  "aggro": {"eficiencia_mana": 0.7, "remocao": 1.0, "anti_aggro": 1.0, "anti_combo": 0.0, "...": 0.0}
}}
```

Cada arquétipo tem os 9 atributos (todos obrigatórios). A tabela representa o conhecimento do
jogador sobre o que importa em cada confronto, e não a "verdade" do simulador. Só é usada pelo
plano `afinidade` ([07](07-planos-de-sideboarding.md)). Arquétipos atuais: `aggro`, `control`,
`midrange`, `combo`, `ramp`, `auras`.

## Como trocar os dados

| Objetivo | O que fazer |
|---|---|
| Outro maindeck | Criar um JSON no mesmo formato e passar `maindeck_file` em `ExperimentConfig` |
| Mudar o pool | Editar `sideboard_pool.json` (mínimo de 15 entradas legais) |
| Mudar o metajogo | Editar `opponents.json`. Cada `archetype` precisa existir em `archetypes.json` |
| Anotar uma carta nova | Usar só os nomes de atributo da [seção 04](04-atributos-e-decodificacao.md). Nome errado ou valor fora de [0, 1] gera erro |
