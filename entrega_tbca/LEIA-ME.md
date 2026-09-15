# TBCA → Supabase — documento de handoff

**Para quem vai importar:** este pacote entrega a Tabela Brasileira de Composição de Alimentos (TBCA, USP/FoRC) já normalizada, pronta para um SaaS de planos alimentares nutricionais. Contém o schema, os dados, os scripts de carga e as decisões de modelagem com o motivo de cada uma.

**Fonte dos dados:** https://www.tbca.net.br — 5.874 alimentos, coleta de setembro/2026.
**Licença:** CC BY-NC-ND 4.0. Citar a fonte é obrigatório, uso comercial é vedado e o conteúdo não pode ser alterado. Os valores nutricionais são reprodução fiel da TBCA; não corrija nem "melhore" nenhum número.

---

## 1. Decisão de modelagem: tabelas separadas, não uma big-table

**Use 5 tabelas: `nutrients`, `foods`, `food_nutrients`, `measures`, `measure_nutrients`. Não use uma tabela única com uma coluna por nutriente.**

O motivo não é preferência de estilo, é o formato dos dados:

1. **A TBCA tem 41 componentes.** Uma tabela larga exigiria 41 colunas de nutrientes mais 41 colunas por medida caseira, e o schema mudaria toda vez que a TBCA publicasse um componente novo. Em formato longo, um nutriente novo é uma linha em `nutrients` e nada mais.
2. **Toda consulta do plano alimentar filtra por nutriente, não por alimento.** "Quanto de ferro tem esta refeição" é `where nutrient_code in (...)` sobre `food_nutrients` com índice em `nutrient_code`. Numa tabela larga é preciso escolher a coluna em tempo de código, o que impede montar dinamicamente a lista de nutrientes que o nutricionista quer ver.
3. **Três estados de valor, não dois.** Boa parte das células é `tr` (traço) ou `NA` (não publicado). Em formato longo isso cabe em uma coluna `value_status` com três valores. Em 41 colunas, ou você perde a distinção, ou cria 41 colunas extras de status.
4. **Fato e dimensão.** `foods` e `nutrients` são dimensões estáveis; `food_nutrients` é o fato. Uma big-table obrigaria a repetir nome, grupo, marca e descrição em 41 linhas por alimento, ou a manter uma segunda tabela de identificação de qualquer forma.
5. **Medida caseira é uma relação, não um atributo.** Cada alimento tem de 0 a 11 medidas, com nomes e gramaturas próprios. É uma tabela filha por definição.

**A exceção deliberada:** `foods.energy_kcal_per_100g` e `foods.energy_kj_per_100g` duplicam o que está em `food_nutrients`. Energia é lida em praticamente toda tela e todo cálculo; evitar o join nesse caso vale a redundância. É a única desnormalização do pacote.

**Índices são obrigatórios:** sem `analyze` depois da carga e sem índice em `nutrient_code`, a primeira consulta do app faz varredura de 241 mil linhas. Os índices já estão em `sql/01_schema.sql`.

---

## 2. Medida caseira: os três campos que você precisa entender

A TBCA publica, para cada alimento, uma tabela cujas colunas são medidas caseiras — e **essas colunas variam de alimento para alimento**. Disso decorrem três armadilhas.

### 2.1 `measure_index` não é um catálogo global

`measure_index` é a posição da coluna na página daquele alimento. **O índice 3 é "Colher sopa cheia" em um alimento e "Pedaço/ Unidade/ Fatia (M)" em outro.** A TBCA não tem um catálogo numerado de medidas caseiras.

- A identidade de uma medida é `(food_code, measure_index)`.
- O significado está em `measure_name`.
- Nunca faça `join` ou `case` por `measure_index`, e nunca mostre o índice na interface.

Não construímos uma tabela de catálogo de medidas porque a mesma medida tem gramatura diferente por alimento (uma colher de sopa de açúcar não pesa o mesmo que uma de farinha): a gramatura é o dado, o nome é o rótulo.

### 2.2 São 26 medidas caseiras distintas

`measure_name` × `measure_unit` resulta em 35 combinações, porque 9 medidas aparecem ora em `g` ora em `mL`. As mais frequentes:

| Medida | Unidade | Alimentos |
| --- | --- | --- |
| Pedaço/ Unidade/ Fatia (M) | g | 1750 |
| Colher servir cheia | g | 1268 |
| Porção média | g | 935 |
| Colher sopa cheia | g | 913 |
| Colher sopa rasa | g | 664 |
| Colher servir rasa | g | 390 |
| Copo americano pequeno | mL | 262 |
| Copo americano duplo | mL | 253 |
| Unidade média | g | 214 |
| Concha cheia | g | 211 |

`measure_unit = 'mL'` cobre 373 alimentos (líquidos). **A TBCA não publica densidade:** não converta mL em g por conta própria. Trate volume como volume no plano alimentar e mostre "mL" ao usuário.

### 2.3 Cinquenta linhas têm nome repetido no mesmo alimento

Em 29 alimentos o mesmo `measure_name` aparece duas vezes com gramaturas diferentes — em geral `Colher servir cheia` com 45 g e 60 g (19 preparações de camarão). Essas linhas estão marcadas com `is_duplicate_name = true`. **Na interface, exija que o nutricionista escolha a gramatura explicitamente.** Se o código pegar a primeira linha da lista, o cálculo sai errado sem nenhum sinal visível.

### 2.4 Use `value_measure`, não recalcule

`measure_nutrients` traz `value_measure` (número que a TBCA publicou para aquela medida) **e** `value_per_100g_derived` (recálculo `value_per_100g × measure_grams / 100`). Os dois divergem em 8.899 linhas (2,6%), porque a TBCA arredonda o valor da medida antes de publicar.

**Calcule o plano alimentar a partir de `food_nutrients.value_per_100g × gramas / 100`.** `value_measure` serve para exibir "1 colher de sopa = 34 kcal" e para conferência. `value_per_100g_derived` existe só para auditoria; não é fonte de verdade.

---

## 3. Os três estados de valor

Nunca trate `null` e `0` como a mesma coisa. A TBCA distingue:

| `value_status` | Significado na TBCA | Valor gravado | Como o app deve tratar |
| --- | --- | --- | --- |
| `valor` | número publicado | o número | somar normalmente |
| `traco` | componente relatado como `tr` | `0.0` | somar como zero, mas exibir "traço" ao usuário |
| `ausente` | `NA` ou célula vazia — não publicado | `null` | **nunca somar como zero**: é desconhecido, não é ausência de nutriente |

Distribuição em `food_nutrients`: `valor` 215.110 · `ausente` 20.310 · `traco` 5.640.

Um plano alimentar que soma `ausente` como zero subestima o nutriente e pode esconder uma deficiência real. Ao agregar micronutrientes, propague a informação: "ferro: 8,2 mg (2 alimentos sem dado publicado)".

`value_text` guarda o texto original da TBCA (`tr`, `NA`, `7,32`) para conferência e para exibir o valor bruto.

---

## 4. Conteúdo do pacote

```
entrega_tbca/
├── LEIA-ME.md               este documento
├── ANALISE-DOS-DADOS.md     auditoria da coleta e casos-limite
├── ESQUEMA.md               dicionário de dados tabela por tabela
├── sql/
│   ├── 01_schema.sql        DDL, índices, RLS, views, conferência
│   ├── 02_carga.sql         carga por \copy
│   └── 03_deduplicar_food_nutrients.sql   carga com deduplicação (ver §9)
├── csv/                     dados para importação em massa
│   ├── nutrients.csv               41 linhas
│   ├── foods.csv                5.874 linhas
│   ├── food_nutrients.csv     241.060 linhas
│   ├── measures.csv             8.213 linhas
│   └── measure_nutrients.csv  336.989 linhas
└── json/                    mesmos dados em JSON (seed via supabase-js)
    ├── foods.json, nutrients.json, food_nutrients.json,
    ├── measures.json, measure_nutrients.json
    └── manifest.json        contagens, tamanhos, md5 e alertas da coleta
```

Formato dos arquivos:

- **CSV:** UTF-8 sem BOM, separador vírgula, decimal com ponto, campo vazio = `NULL` (o `\copy` usa `null ''`).
- **JSON:** UTF-8, sem indentação, um array por tabela. Campos numéricos são números ou `null` (nunca `""`) e booleanos são `true`/`false`, para poderem ser inseridos direto pelo supabase-js sem conversão.

O pacote inteiro é regerado por `exportar_entrega.py` na raiz do repositório de coleta, sem rede:

```bash
python exportar_entrega.py
```

O script recria `csv/` e `json/`; `sql/` e os três `.md` são mantidos à mão e não são apagados. Se a TBCA publicar uma revisão, o ciclo é recoletar → regerar o pacote → rodar `01_schema.sql` e `03_deduplicar_food_nutrients.sql` de novo.

---

## 5. Como importar

### Opção A — psql (recomendado, uma vez por ambiente)

A partir da pasta `entrega_tbca/`:

```bash
psql "$DATABASE_URL" -f sql/01_schema.sql
psql "$DATABASE_URL" -f sql/03_deduplicar_food_nutrients.sql
```

`DATABASE_URL` está em Project Settings → Database → Connection string → URI.

**Use `03_deduplicar_food_nutrients.sql`, não `02_carga.sql`.** Os dois fazem a mesma carga, mas o pacote contém chave repetida em duas tabelas, por causa dos 8 alimentos cuja página na TBCA publica duas tabelas de composição (ver §9):

| Tabela | No pacote | Após deduplicação |
| --- | --- | --- |
| `food_nutrients` | 241.060 | 240.787 |
| `measure_nutrients` | 336.989 | 336.640 |

O `03` carrega essas duas tabelas em tabela de estágio e mantém a primeira ocorrência de cada chave. O `02` é a carga direta e aborta na primeira duplicata — deixamos o arquivo no pacote como referência do caminho sem estágio, não como caminho recomendado.

Os dois scripts usam `\copy`, que lê o arquivo na sua máquina. **Não troque por `COPY ... FROM '/caminho'`:** no Supabase hospedado esse caminho não existe no servidor e a carga falha. Tudo roda em uma transação, então uma falha no meio não deixa estado parcial.

### Opção B — supabase-js com o seed JSON

Adequado quando a importação é feita por script dentro do próprio projeto:

```ts
import { createClient } from '@supabase/supabase-js'
import nutrients from './entrega_tbca/json/nutrients.json'
import foods from './entrega_tbca/json/foods.json'
import foodNutrients from './entrega_tbca/json/food_nutrients.json'
import measures from './entrega_tbca/json/measures.json'
import measureNutrients from './entrega_tbca/json/measure_nutrients.json'

const db = createClient(process.env.SUPABASE_URL!, process.env.SUPABASE_SERVICE_ROLE_KEY!)

async function inserir(tabela: string, linhas: Record<string, unknown>[]) {
  const lote = 1000
  for (let i = 0; i < linhas.length; i += lote) {
    const { error } = await db.from(tabela).upsert(linhas.slice(i, i + lote))
    if (error) throw new Error(`${tabela} lote ${i}: ${error.message}`)
  }
}

// a ordem importa: as chaves estrangeiras exigem a dimensão antes do fato
await inserir('nutrients', nutrients)
await inserir('foods', foods)
await inserir('food_nutrients', foodNutrients)
await inserir('measures', measures)
await inserir('measure_nutrients', measureNutrients)
```

Use a `service_role` key: as tabelas têm RLS com leitura pública e nenhuma policy de escrita.

Cuidados:

- Lotes de 500 a 1000 linhas. `measure_nutrients` tem 336.989 linhas; enviar tudo de uma vez estoura o limite de payload da API.
- `collected_at` vem como `"2026-09-14T00:01:29"`, sem fuso. Trate como UTC.
- O `upsert` exige que a tabela já exista: rode `sql/01_schema.sql` antes.

### Opção C — Dashboard

O Data Editor importa CSV pela interface, mas não é prático para 336.989 linhas. Use só para `nutrients.csv` e `foods.csv` e faça o resto pela opção A.

---

## 6. Verificação depois da carga

As contagens têm que bater exatamente:

| Tabela | Com deduplicação (§5) |
| --- | --- |
| `nutrients` | 41 |
| `foods` | 5.874 |
| `food_nutrients` | **240.787** |
| `measures` | 8.213 |
| `measure_nutrients` | **336.640** |

As consultas de conferência estão no fim de `01_schema.sql` (contagens, distribuição de status, alimentos sem energia, alimentos sem medida caseira). O `json/manifest.json` traz o md5 de cada arquivo e a lista completa dos 51 alertas da coleta, caso seja preciso investigar uma divergência.

---

## 7. Cinco consultas para validar a integração

```sql
-- 1. busca de alimento para montar refeição
select code, name, energy_kcal_per_100g
from foods
where name ilike '%abacate%'
order by name
limit 20;

-- 2. macro de 100 g de um alimento
select n.display_name, n.unit, fn.value_per_100g, fn.value_status
from food_nutrients fn
join nutrients n on n.code = fn.nutrient_code
where fn.food_code = 'BRC0001C'
  and fn.nutrient_code in ('energy_kcal','protein_g','carbohydrate_total_g','lipid_g','fiber_g')
order by n.display_name;

-- 3. medidas caseiras disponíveis para o alimento
select measure_index, measure_name, measure_unit, measure_quantity, is_duplicate_name
from measures
where food_code = 'BRC0001C'
order by measure_index;

-- 4. o que o usuário vê ao escolher "1 colher de sopa cheia"
select n.display_name, mn.value_measure, n.unit
from measure_nutrients mn
join nutrients n on n.code = mn.nutrient_code
join measures m on m.food_code = mn.food_code and m.measure_index = mn.measure_index
where mn.food_code = 'BRC0001C'
  and m.measure_name = 'Colher sopa cheia'
  and mn.nutrient_code in ('energy_kcal','protein_g','carbohydrate_total_g','lipid_g')
order by n.display_name;

-- 5. cálculo de um item de refeição (80 g de abacate)
select n.display_name,
       round(fn.value_per_100g * 80 / 100.0, 2) as valor_na_porcao,
       n.unit
from food_nutrients fn
join nutrients n on n.code = fn.nutrient_code
where fn.food_code = 'BRC0001C'
  and fn.value_status <> 'ausente'
  and fn.nutrient_code in ('energy_kcal','protein_g','carbohydrate_total_g','lipid_g','fiber_g');
```

---

## 8. Regras que o outro projeto deve seguir

1. **Não altere valores nutricionais.** A licença CC BY-NC-ND proíbe. Se a TBCA corrigir um dado, a correção vem de uma nova coleta e de uma nova importação, não de um `update` manual.
2. **Sempre exiba a fonte.** Toda tela que mostra valor nutricional da TBCA precisa citar "TBCA/USP" e, se houver exportação de plano, incluir a referência.
3. **`ausente` não é zero.** Propague o estado para o usuário; não silencie.
4. **`mL` não é `g`.** Não converta sem densidade.
5. **Medida repetida exige escolha do usuário.** Use `is_duplicate_name`.
6. **A carga é idempotente.** `01_schema.sql` apaga e recria as tabelas; o seed JSON usa `upsert` por chave primária.
7. **`foods.code` é a chave natural.** Use-a como FK nas tabelas de plano alimentar do SaaS, em vez de criar um `id` próprio — assim a rastreabilidade até a TBCA se mantém.

---

## 9. Ressalvas conhecidas do dado de origem

Detalhamento completo em `ANALISE-DOS-DADOS.md`. O que precisa de decisão de produto:

- **8 alimentos têm componente repetido na coleta** (`BRC0004A`, `BRC0237T`, `BRC0953F`, `BRC0955F`, `BRC0956F`, `BRC0957F`, `BRC1145B`, `BRC1196B`): a página da TBCA traz duas tabelas de composição e as duas foram gravadas. Isso gera 273 linhas além do esperado em `food_nutrients` e 349 em `measure_nutrients`; como as PKs são compostas, a carga direta aborta. Use `sql/03_deduplicar_food_nutrients.sql` (mantém a primeira tabela de composição de cada alimento) ou exclua os 8 códigos do catálogo. A view `food_componentes_duplicados` lista quem são. Qual das duas tabelas analíticas usar é decisão de domínio — se a segunda for a correta, isso se resolve recoletando a origem, não por heurística no código.
- **1 alimento tem só 3 nutrientes** (`BRC0262C`, Snacks de banana chips): a página publica apenas os nutrientes de adição.
- **5 alimentos não têm energia por 100 g**: `BRC0262C`, `BRC1090A`, `BRC1091A`, `BRC1121A`, `BRC1122A` (bebidas à base de arroz). Energia `ausente` é `null`: o cálculo da refeição precisa tratar, porque somar `null` como zero produz total calórico menor que a realidade.
- **18 medidas caseiras foram descartadas** na exportação: são cabeçalhos de coluna malformados (`Prato raso (200 -)`, `Colher sopa cheia (9)`), sem unidade e sem gramatura. Não perdem informação nutricional — as demais medidas desses alimentos continuam disponíveis.
- **317 alimentos não têm nenhuma medida caseira** válida: use gramas no plano alimentar para eles.
