# Análise dos dados — auditoria da coleta

Auditoria feita sobre os 5.874 arquivos JSON individuais da coleta TBCA (setembro/2026), que deram origem a este pacote. Serve para o outro projeto saber **o que existe, o que é confiável e o que precisa de tratamento** antes de entrar num plano alimentar.

O `json/manifest.json` traz a lista completa e legível por máquina dos 51 alertas registrados na exportação.

---

## 1. Inventário

| Item | Quantidade |
| --- | --- |
| Alimentos | 5.874 |
| Grupos TBCA | 17 (`A` Cereais … `U` Nozes e sementes) |
| Nutrientes | 41 (2 de energia, 39 de composição) |
| Valores por 100 g | 241.060 |
| Medidas caseiras | 8.213 |
| Valores por medida caseira | 336.989 |
| Alimentos com marca | 331 |
| Alimentos com nome científico | 1.652 |
| Alimentos com alguma medida em `mL` | 373 |
| Alimentos sem nenhuma medida caseira | 317 |
| Alimentos sem energia por 100 g | 5 |
| Total do pacote (CSV + JSON) | 108 MB |

Status dos valores:

| | `valor` | `traco` | `ausente` |
| --- | --- | --- | --- |
| por 100 g | 215.110 | 5.640 | 20.310 |
| por medida caseira | 299.358 | 10.238 | 27.393 |

**Leitura:** 8,4% dos valores por 100 g são `ausente`. Não é defeito da coleta — é a TBCA não publicando o dado. Mas significa que um cálculo de micronutrientes que ignora o status vai errar em quase um de cada doze valores.

---

## 2. O achado que mais importa: o índice da medida não é um catálogo

A tabela da TBCA tem uma coluna por medida caseira, e **as colunas mudam de alimento para alimento**. A coleta preservou a posição da coluna (`indice`, agora `measure_index`), que é consistente *dentro* de um alimento, mas não entre alimentos:

| `measure_index` | Nomes que aparecem nessa posição |
| --- | --- |
| 3 | `Pedaço/ Unidade/ Fatia (M)` (1.664) · `Colher servir cheia` (1.244) · `Porção média` (917) · `Colher sopa cheia` (601) · `Copo americano duplo` (250) |
| 4 | `Colher servir rasa` (344) · `Copo americano pequeno` (248) · `Colher sopa rasa` (218) · `Colher sopa cheia` (122) |

O índice vai de 3 a 13 e não é contínuo dentro de um alimento: um alimento pode ter as posições 3, 5 e 8.

**Consequências práticas:**

- `measure_index` só é único junto de `food_code` — a PK de `measures` é `(food_code, measure_index)`.
- **Não** crie uma tabela de catálogo `measure_types` com `id = measure_index`. Seria um modelo errado e produziria cálculos silenciosamente incorretos.
- **Não** filtre nem agrupe por `measure_index`. Use `measure_name`.
- Se quiser um catálogo de medidas para a interface ("escolha uma colher de sopa"), construa-o com `select distinct measure_name, measure_unit from measures` — 35 combinações.

---

## 3. Medidas caseiras: 26 nomes, 35 combinações com unidade

Nove medidas aparecem ora em `g` ora em `mL` (373 alimentos líquidos usam `mL`). As principais, por número de alimentos:

| Medida | Unidade | Alimentos |
| --- | --- | --- |
| Pedaço/ Unidade/ Fatia (M) | g | 1.750 |
| Colher servir cheia | g | 1.268 |
| Porção média | g | 935 |
| Colher sopa cheia | g | 913 |
| Colher sopa rasa | g | 664 |
| Colher servir rasa | g | 390 |
| Copo americano pequeno | mL | 262 |
| Copo americano duplo | mL | 253 |
| Unidade média | g | 214 |
| Concha cheia | g | 211 |
| Escumadeira cheia / rasa | g | 179 cada |
| Colher sobremesa rasa | g | 146 |
| Colher sobremesa cheia | g | 118 |
| Xícara chá | mL | 94 |
| Colher chá rasa / cheia | g | 89 / 74 |
| Xícara chá | g | 68 |
| Prato fundo / Prato raso | g | 44 / 25 |
| Fatia média | g | 23 |
| Dose / Taça | mL | 17 |
| Pedaço médio | g | 15 |
| Cálice | mL | 5 |

**Ponto de atenção para o nutricionista:** `Copo americano duplo` tem 200 mL para uma bebida e 200 g para um alimento pastoso, em alimentos diferentes. A unidade vem da origem e não deve ser convertida — a TBCA não publica densidade.

### 3.1 Cinquenta linhas com nome repetido no mesmo alimento

Em 29 alimentos o mesmo nome aparece duas vezes com gramaturas diferentes. Concentração: preparações de camarão (grupo E) com `Colher servir cheia` 45 g e 60 g.

| Alimento | Medida | Gramaturas |
| --- | --- | --- |
| BRC0221C Chimia de uva | Colher sobremesa rasa | 11 g e 26 g |
| BRC0243C Suco de graviola | Copo americano pequeno | 240 mL e 165 mL |
| BRC0287E–BRC0337E (camarão, ~21 alimentos) | Colher servir cheia | 45 g e 60 g |
| BRC0793A | Colher sopa rasa | duas gramaturas |
| BRC0937A | Escumadeira cheia | duas gramaturas |

Marcadas com `is_duplicate_name = true`. Se a interface pegar a primeira, o plano alimentar do paciente fica errado sem nenhum sinal visível.

### 3.2 Dezoito medidas descartadas na exportação

São cabeçalhos de coluna malformados na própria TBCA, sem unidade e sem gramatura:

`Colher sopa cheia (9)` · `Colher sopa rasa (6)` · `Escumadeira rasa (90)` · `Pedaço/ Unidade/ Fatia (M) (10 unidade)` · `(20 unidade)` · `(30 unidade)` · `(50 unidade)` · `(60 unidade)` · `(110 unidade)` · `(280 unidade)` · `Porção média (100)` · `(110)` · `Prato fundo (100)` · `Prato raso (80)` · `Prato raso (200 -)`

Aparecem em 18 alimentos. Foram removidas de `measures.csv` porque não têm gramatura: sem isso não há como converter em nutriente. As demais medidas desses alimentos continuam no pacote.

---

## 4. Anomalias de composição

### 4.1 Oito alimentos com o conjunto de componentes duplicado

`BRC0004A` (82 componentes), `BRC1196B` (82), `BRC0237T`, `BRC0953F`, `BRC0955F`, `BRC0956F`, `BRC0957F` (79 cada) e `BRC1145B` (1 componente repetido).

A página desses alimentos na TBCA publica **duas tabelas de composição** — duas bases analíticas ou duas referências bibliográficas — e a coleta gravou as duas. As chaves repetidas somam **273 linhas em `food_nutrients`** (241.060 → 240.787) e **349 em `measure_nutrients`** (336.989 → 336.640). Como as duas tabelas têm PK composta, a carga direta aborta na primeira duplicata e nada é importado.

**O que o outro projeto deve fazer:** usar `sql/03_deduplicar_food_nutrients.sql`, que carrega as duas tabelas em tabela de estágio e mantém a primeira ocorrência de cada chave. Os 8 alimentos ficam com o conjunto completo de nutrientes. A alternativa é excluir os 8 códigos do catálogo.

Qual das duas tabelas analíticas é a correta é decisão de domínio, não correção de software: se a segunda for a que interessa, isso se resolve recoletando a origem. A view `food_componentes_duplicados` lista os códigos.

### 4.2 Um alimento com apenas 3 nutrientes

`BRC0262C` — "Snacks, banana chips, com gordura" — tem só `Gordura de adição`, `Proteína vegetal` e `Proteína animal`, todos sem valor. A página da TBCA publica apenas os nutrientes de adição. Um plano alimentar que use esse alimento calcula zero para tudo. Exclua-o ou marque como `composition_collected = false` no seu domínio.

### 4.3 Cinco alimentos sem energia

`BRC0262C`, `BRC1090A`, `BRC1091A`, `BRC1121A`, `BRC1122A` — bebidas à base de arroz, as quatro últimas variações de vitamina. `energy_kcal_per_100g` é `NULL` e `energy_kcal` está `ausente` em `food_nutrients`.

**Implicação:** a tela de plano alimentar precisa tratar energia nula. Somar `null` como zero produz um total calórico menor do que a realidade — é o erro mais grave possível num app de nutrição.

---

## 5. Integridade referencial verificada

O pacote foi conferido carregando os cinco CSVs em um banco com o schema de `01_schema.sql`, pelo caminho de deduplicação de `03_deduplicar_food_nutrients.sql`:

| Verificação | Resultado |
| --- | --- |
| `food_nutrients.food_code` sem alimento correspondente | 0 |
| `measures.food_code` sem alimento correspondente | 0 |
| `measure_nutrients` sem medida correspondente | 0 |
| `nutrient_code` fora do catálogo de 41 | 0 |
| Componente sem mapeamento para o catálogo | 0 |
| `value_per_100g` nulo com status diferente de `ausente` | 0 |
| `value_status = 'ausente'` com valor preenchido | 0 |
| Medidas com unidade fora de `g`/`mL` | 0 |
| Medidas com gramatura nula ou ≤ 0 | 0 |
| Chaves estrangeiras violadas (`pragma foreign_key_check`) | 0 |
| Contagens finais | 41 · 5.874 · 240.787 · 8.213 · 336.640 |

A exportação falha ruidosamente se um componente novo aparecer sem mapeamento: nenhum valor foi silenciosamente descartado.

---

## 6. `value_measure` versus valor recalculado

`measure_nutrients` traz as duas versões. Elas divergem em 8.899 linhas (2,6%), com desvio quase sempre de uma unidade na última casa:

| Nutriente | Linhas divergentes |
| --- | --- |
| energy_kcal | 3.372 |
| energy_kj | 1.398 |
| potassium_mg | 642 |
| sodium_mg | 544 |
| phosphorus_mg | 516 |
| vitamin_a_re_mcg | 320 |

Exemplo: `BRC0001C`, `Copo americano duplo` (200 mL) — energia kcal publicada 151, recalculada 152. O desvio decorre do arredondamento da TBCA, que arredonda o valor da medida antes de publicar.

**Regra:** calcule a partir de `food_nutrients.value_per_100g × gramas / 100`. Use `value_measure` para exibir o número que a TBCA publica. `value_per_100g_derived` é conferência, não fonte de verdade.

---

## 7. Reprodutibilidade

Os JSONs individuais e o `db.json` ficam em `dados_tbca/` no repositório de coleta, com o HTML de cada página em `cache_tbca/`. `exportar_entrega.py` regenera este pacote inteiro a partir deles, sem rede:

```bash
python exportar_entrega.py
```

O script recria apenas `csv/` e `json/`; `sql/` e os três documentos `.md` são mantidos à mão e não são apagados.

Se a TBCA publicar uma revisão, a sequência é: recoletar → regenerar o pacote → rodar `01_schema.sql` e `02_carga.sql` de novo. Nenhum ajuste manual nos dados sobrevive a esse ciclo, e é assim que deve ser — a licença CC BY-NC-ND não permite alterar o conteúdo.

O `json/manifest.json` registra data de geração, contagens, tamanho, md5 e alertas de cada arquivo, para comparar duas gerações e ver exatamente o que mudou.
