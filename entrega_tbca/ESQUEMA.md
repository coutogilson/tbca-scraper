# Esquema de dados — dicionário completo

Cinco tabelas. Ordem de carga obrigatória: `nutrients` → `foods` → `food_nutrients` → `measures` → `measure_nutrients`.

```
nutrients ──┐
            ├──< food_nutrients >── foods ──< measures ──┐
            └──< measure_nutrients >───────────────────┘
```

- `foods` 1—N `food_nutrients` (241.060 linhas)
- `foods` 1—N `measures` (8.213 linhas)
- `measures` 1—N `measure_nutrients` (336.989 linhas)
- `nutrients` 1—N `food_nutrients` e `measure_nutrients` (41 linhas)

Convenção de nulos: coluna de texto sem valor entra como `NULL` na carga; não há string vazia gravada no banco. Nos CSVs isso é um campo vazio, e o `\copy` usa `null ''`.

As contagens deste documento são as do pacote de origem. Com a deduplicação de `sql/03_deduplicar_food_nutrients.sql`, `food_nutrients` entra com 240.787 linhas (em vez de 241.060) e `measure_nutrients` com 336.640 (em vez de 336.989) — ver §4.1 de `ANALISE-DOS-DADOS.md`. `nutrients`, `foods` e `measures` não mudam.

---

## `nutrients` — catálogo de nutrientes (41 linhas)

| Coluna | Tipo | Nulo | Descrição |
| --- | --- | --- | --- |
| `code` | text PK | não | Identificador estável em inglês snake_case: `energy_kcal`, `protein_g`. É o que aparece nas FKs. |
| `display_name` | text | não | Nome para exibir ao nutricionista, como na TBCA: `Energia`, `Carboidrato total`. |
| `unit` | text | não | `g`, `mg`, `mcg`, `kJ` ou `kcal`. A unidade faz parte da identidade: a TBCA publica `Energia` em kJ e em kcal como componentes distintos. |
| `nutrient_group` | text | não | `energia`, `proximais`, `carboidratos`, `proteina`, `lipidios`, `fibra`, `minerais`, `vitaminas`, `adicao`. Agrupa a exibição e permite pedir "todos os minerais" sem listar 12 códigos. |
| `decimal_places` | smallint | não | Casas decimais que a TBCA usa ao arredondar o valor da medida caseira. Use no `round()` e na formatação. |
| `synonyms` | text | sim | Nomes alternativos separados por `;` (`thiamin_mg` → `vitamin_b1`), para busca livre. Vazio nesta versão. |

### Catálogo completo

| code | display_name | unidade | grupo | casas |
| --- | --- | --- | --- | --- |
| energy_kj | Energia | kJ | energia | 0 |
| energy_kcal | Energia | kcal | energia | 0 |
| moisture_g | Umidade | g | proximais | 2 |
| carbohydrate_total_g | Carboidrato total | g | carboidratos | 2 |
| carbohydrate_available_g | Carboidrato disponível | g | carboidratos | 2 |
| protein_g | Proteína | g | proteína | 2 |
| lipid_g | Lipídios | g | lipídios | 2 |
| fiber_g | Fibra alimentar | g | fibra | 2 |
| alcohol_g | Álcool | g | proximais | 2 |
| ash_g | Cinzas | g | proximais | 2 |
| cholesterol_mg | Colesterol | mg | lipídios | 2 |
| fatty_acid_saturated_g | Ácidos graxos saturados | g | lipídios | 3 |
| fatty_acid_monounsaturated_g | Ácidos graxos monoinsaturados | g | lipídios | 3 |
| fatty_acid_polyunsaturated_g | Ácidos graxos poli-insaturados | g | lipídios | 3 |
| fatty_acid_trans_g | Ácidos graxos trans | g | lipídios | 3 |
| calcium_mg | Cálcio | mg | minerais | 3 |
| iron_mg | Ferro | mg | minerais | 3 |
| sodium_mg | Sódio | mg | minerais | 3 |
| magnesium_mg | Magnésio | mg | minerais | 3 |
| phosphorus_mg | Fósforo | mg | minerais | 3 |
| potassium_mg | Potássio | mg | minerais | 3 |
| manganese_mg | Manganês | mg | minerais | 3 |
| zinc_mg | Zinco | mg | minerais | 3 |
| copper_mg | Cobre | mg | minerais | 3 |
| selenium_mcg | Selênio | mcg | minerais | 3 |
| vitamin_a_re_mcg | Vitamina A (RE) | mcg | vitaminas | 3 |
| vitamin_a_rae_mcg | Vitamina A (RAE) | mcg | vitaminas | 3 |
| vitamin_d_mcg | Vitamina D | mcg | vitaminas | 3 |
| vitamin_e_mg | Alfa-tocoferol (Vitamina E) | mg | vitaminas | 3 |
| thiamin_mg | Tiamina | mg | vitaminas | 3 |
| riboflavin_mg | Riboflavina | mg | vitaminas | 3 |
| niacin_mg | Niacina | mg | vitaminas | 3 |
| vitamin_b6_mg | Vitamina B6 | mg | vitaminas | 3 |
| vitamin_b12_mcg | Vitamina B12 | mcg | vitaminas | 3 |
| vitamin_c_mg | Vitamina C | mg | vitaminas | 3 |
| folate_equivalent_mcg | Equivalente de folato | mcg | vitaminas | 3 |
| added_salt_g | Sal de adição | g | adição | 2 |
| added_sugar_g | Açúcar de adição | g | adição | 2 |
| added_fat_g | Gordura de adição | g | adição | 2 |
| vegetable_protein_g | Proteína vegetal | g | proteína | 2 |
| animal_protein_g | Proteína animal | g | proteína | 2 |

**Atenção:** `vitamin_a_re_mcg` e `vitamin_a_rae_mcg` são dois componentes distintos publicados pela TBCA. Não são sinônimos e não devem ser somados. O mesmo vale para os `added_*`: `added_sugar_g` é o açúcar adicionado, não o açúcar total do alimento.

---

## `foods` — identificação do alimento (5.874 linhas)

| Coluna | Tipo | Nulo | Descrição |
| --- | --- | --- | --- |
| `code` | text PK | não | Código TBCA: `BRC` + 4 dígitos + letra do grupo. Ex.: `BRC0001C`. Chave natural — use nas FKs do seu domínio. |
| `name` | text | não | Nome do alimento em português, como na TBCA. Inclui a forma de preparo quando aplicável: `Abobrinha, italiana, c/ casca, refogada (c/ óleo, cebola e alho)`. |
| `scientific_name` | text | sim | Nome científico. Preenchido em 1.652 alimentos (os de origem botânica ou animal identificável). |
| `group_code` | text | sim | Letra do grupo TBCA: `A` a `U` (17 grupos). |
| `group_name` | text | sim | `Cereais e derivados`, `Frutas e derivados`, `Carnes e derivados`... |
| `type_code` | text | sim | `A` in natura, `B` processado (ingrediente), `C` processado pronto para consumo, `D` preparação, `F` preparo simples, `L` preparação vegana/vegetariana/sem lactose. |
| `type_name` | text | sim | Descrição do tipo, sem a marca. |
| `brand` | text | sim | Marca. Preenchido em 331 alimentos industrializados. |
| `description_pt` | text | sim | Descrição TBCA em português (parte antes das traduções). |
| `description_en` | text | sim | Descrição em inglês. Preenchida em 5.849 alimentos. |
| `description_es` | text | sim | Descrição em espanhol. |
| `energy_kcal_per_100g` | numeric(10,2) | sim | **Desnormalizado de `food_nutrients`** para evitar join em toda consulta. `NULL` em 5 alimentos. |
| `energy_kj_per_100g` | numeric(10,2) | sim | Idem, em kJ. |
| `measure_count` | smallint | não | Quantidade de medidas caseiras válidas do alimento. `0` em 317 alimentos — use gramas no plano para eles. |
| `composition_collected` | boolean | não | `false` = alimento aparece na listagem da TBCA mas não publica tabela de composição. Nesta coleta todos são `true`. |
| `source_url` | text | sim | URL da página de origem na TBCA, com o token de acesso original. Rastreabilidade. |
| `tbca_version` | text | sim | Versão do coletor (`2.1`), não da TBCA. |
| `collected_at` | timestamptz | sim | Data e hora da coleta (`2026-09-14T00:01:29`, tratar como UTC). |

**Campos derivados da coleta:** `type_name` e `brand` foram separados do campo original `tipo_alimento`, que vinha no formato `B - Alimento processado (ingrediente) Marca: Sadia`. Se precisar do texto original, ele está no `db.json` do repositório de coleta.

**O nome não é único.** Existem alimentos com o mesmo nome em grupos diferentes (preparações com e sem sal, por exemplo). Sempre use `code` como identidade.

---

## `food_nutrients` — composição por 100 g (241.060 linhas)

Base de todos os cálculos. Uma linha por alimento × nutriente.

| Coluna | Tipo | Nulo | Descrição |
| --- | --- | --- | --- |
| `food_code` | text FK | não | → `foods.code` |
| `nutrient_code` | text FK | não | → `nutrients.code` |
| `value_per_100g` | numeric(14,6) | sim | Valor por 100 g da **parte comestível**. `NULL` quando `value_status = 'ausente'`. |
| `value_status` | text | não | `valor` \| `traco` \| `ausente`. Ver `LEIA-ME.md` §3. |
| `value_text` | text | sim | Texto original da TBCA: `tr`, `NA`, `7,32`. Para exibir o valor bruto ao nutricionista e para auditoria. |
| PK | | | `(food_code, nutrient_code)` |

**Base:** 100 g de parte comestível. Se o plano alimentar precisa distinguir cru de cozido, isso está no `name`, não em coluna separada.

**Cobertura:** 5.862 alimentos têm os 41 nutrientes; 4 têm 39 (sem energia); 1 tem 3; 7 têm o conjunto duplicado — ver `ANALISE-DOS-DADOS.md` §4. Depois da deduplicação descrita em `sql/03_deduplicar_food_nutrients.sql`, o total da tabela é 240.787 linhas e 5.868 alimentos ficam com os 41 nutrientes.

---

## `measures` — medidas caseiras por alimento (8.213 linhas)

Quantos gramas (ou mL) corresponde uma medida caseira **daquele alimento específico**.

| Coluna | Tipo | Nulo | Descrição |
| --- | --- | --- | --- |
| `food_code` | text FK | não | → `foods.code` |
| `measure_index` | smallint | não | Posição da medida na tabela da TBCA, de 3 a 13 e não contínua. **Só tem significado junto com `food_code`** — não é catálogo global. |
| `measure_name` | text | não | `Colher sopa cheia`, `Copo americano pequeno`, `Pedaço/ Unidade/ Fatia (M)`. 26 nomes distintos no total. |
| `measure_unit` | text | não | `g` ou `mL`. |
| `measure_quantity` | numeric(10,2) | não | Quantidade da medida na unidade acima. Sempre > 0. |
| `measure_grams` | numeric(10,2) | não | Gramatura da medida. Redundante com `measure_quantity` de propósito: leitores não precisam saber se a origem veio em mL. |
| `is_duplicate_name` | boolean | não | `true` quando o mesmo `measure_name` aparece mais de uma vez no alimento com gramaturas diferentes. 50 linhas. Exija escolha do usuário. |
| PK | | | `(food_code, measure_index)` |

`measure_index` começa em 3 na TBCA, porque as duas primeiras colunas da tabela são o nome e a unidade do componente. **Não presuma sequência contínua nem começo em 1.**

---

## `measure_nutrients` — valor por medida caseira (336.989 linhas)

Valor do nutriente para **uma medida caseira inteira**, não por grama.

| Coluna | Tipo | Nulo | Descrição |
| --- | --- | --- | --- |
| `food_code` | text FK | não | → `measures` |
| `measure_index` | smallint FK | não | → `measures` |
| `nutrient_code` | text FK | não | → `nutrients.code` |
| `value_measure` | numeric(14,6) | sim | Valor publicado pela TBCA para a medida inteira, com o arredondamento da TBCA. Compare com `value_per_100g_derived` antes de confiar: divergem em 2,6% das linhas. |
| `value_per_100g_derived` | numeric(14,6) | sim | `food_nutrients.value_per_100g × measures.measure_grams / 100`. Conferência e preenchimento de lacuna, não fonte de verdade. |
| `value_status` | text | não | Mesmo domínio de `food_nutrients`. |
| PK | | | `(food_code, measure_index, nutrient_code)` |

Exemplo real (`BRC0001C`, abacate, `Colher sopa cheia` = 45 g):

| nutriente | por 100 g | valor da medida |
| --- | --- | --- |
| energy_kcal | 76 | 34 |
| protein_g | 1,15 | 0,52 |
| lipid_g | 6,21 | 2,79 |
| fiber_g | 4,03 | 1,81 |

---

## Views de apoio

**`food_full`** — alimento com os nutrientes agregados em dois JSONB: `nutrients_per_100g` (só status `valor` e `traco`) e `nutrients_ausentes`. Use para telas de detalhe e busca. Para cálculo em lote, consulte `food_nutrients` direto: a view faz `group by` sobre 241 mil linhas.

**`food_componentes_duplicados`** — os 8 alimentos cuja coleta trouxe componente repetido. Revise antes de usar em plano alimentar (ver `ANALISE-DOS-DADOS.md` §4.1).

---

## Convenções dos arquivos

**CSV**

- UTF-8 sem BOM, separador `,`, aspas `"` apenas quando necessário.
- Decimal com ponto; `NULL` como campo vazio (o `\copy` usa `null ''`).
- `boolean` como `true`/`false` minúsculo.
- Nomes de coluna iguais aos das tabelas: o CSV pode ser importado sem transformação.
- Não há coluna `id` em nenhuma tabela: as PKs são naturais (`foods.code`) ou compostas.

**JSON**

- UTF-8, sem indentação, um array por tabela.
- Campos numéricos são número ou `null`, nunca `""`; booleanos são `true`/`false`. O JSON pode ser inserido direto pelo supabase-js sem conversão.
- `manifest.json` (objeto, não array) traz data de geração, contagens, tamanho, md5 e os 51 alertas da coleta.
