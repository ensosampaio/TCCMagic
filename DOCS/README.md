# Documentação do TCCMagic

O TCCMagic otimiza o **sideboard de 15 cartas** de um maindeck fixo de Magic: The Gathering
(formato Modern, deck Boros Energy). O otimizador é um **BRKGA com codificação por atributos
(BRKGA-A)**. Cada sideboard é avaliado em séries **Melhor de 3** simuladas contra uma suíte de
oponentes do metajogo, pelo MTG Forge ou por um simulador substituto.

## Índice

| # | Documento | Conteúdo |
|---|---|---|
| 01 | [Visão geral](01-visao-geral.md) | Objetivo, fluxo do pipeline, mapa dos módulos, glossário |
| 02 | [Instalação e execução](02-instalacao-e-execucao.md) | Dependências, menu interativo, todas as opções de linha de comando |
| 03 | [Dados de entrada](03-dados-de-entrada.md) | Formato dos JSON (maindeck, pool, oponentes, afinidades) e validações |
| 04 | [Atributos e decodificação](04-atributos-e-decodificacao.md) | Os 9 atributos, o vetor v(c), chaves → pesos → Top-15 |
| 05 | [BRKGA](05-brkga.md) | Ciclo evolutivo, elite, mutantes, cruzamento, fitness ruidoso, parada |
| 06 | [Simulação Bo3](06-simulacao-bo3.md) | Estrutura das séries, cache de jogos, lotes por deck, métricas |
| 07 | [Planos de sideboarding](07-planos-de-sideboarding.md) | Plano aleatório (padrão) e plano por afinidade; terrenos nunca saem |
| 08 | [Motores de partida](08-motores.md) | Simulador substituto e integração com o MTG Forge |
| 09 | [Fitness, reamostragem e paralelismo](09-fitness-reamostragem-paralelismo.md) | Cálculo do fitness, caches, reamostragem, workers |
| 10 | [Validação e análise das trocas](10-validacao-e-analise-de-trocas.md) | Validação final com linha de base e regressão do efeito de cada carta |
| 11 | [Saídas: JSON e XLSX](11-saidas-json-xlsx.md) | Esquema completo dos arquivos exportados |
| 12 | [Referência de API](12-referencia-de-api.md) | Classes e funções públicas, por módulo |
| 13 | [Testes](13-testes.md) | O que cada teste automatizado garante |
| 14 | [Experimentos e limitações](14-experimentos-e-limitacoes.md) | Resultado do experimento com o Forge, limitações conhecidas, próximos passos |

## Leitura sugerida

- **Para rodar um experimento:** 02 → 11.
- **Para entender o método (texto do TCC):** 01 → 04 → 05 → 06 → 07 → 10.
- **Para alterar o código:** 01 → 12 → 13.
- **Para trocar deck, pool ou oponentes:** 03.

## Convenções

- Taxas de vitória são proporções em [0, 1]. "pp" significa pontos percentuais.
- "Série" é uma partida Melhor de 3. "Jogo" é cada game dentro dela (G1, G2, G3).
- "Pós-side" refere-se aos Games 2 e 3, jogados depois da troca de cartas.
- Os nomes de código (classes, campos, opções) aparecem em `monoespaçado`, exatamente como no código.
