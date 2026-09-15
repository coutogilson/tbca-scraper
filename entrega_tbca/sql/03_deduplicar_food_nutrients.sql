-- =============================================================================
-- TBCA - importacao com deduplicacao
--
-- USE ESTE ARQUIVO em vez de 02_carga.sql. Duas tabelas tem chave repetida no
-- pacote, por causa de 8 alimentos cuja pagina na TBCA publica duas tabelas de
-- composicao (a coleta gravou as duas):
--
--   BRC0004A  BRC0237T  BRC0953F  BRC0955F  BRC0956F  BRC0957F  BRC1145B  BRC1196B
--
--   food_nutrients:    273 linhas a mais  (241.060 -> 240.787)
--   measure_nutrients: 349 linhas a mais  (336.989 -> 336.640)
--
-- A carga direta aborta na primeira chave duplicada. Aqui as duas tabelas
-- passam por uma tabela de estagio e a copia mantem a PRIMEIRA ocorrencia de
-- cada chave, ou seja, a primeira tabela de composicao da pagina.
--
-- Qual das duas tabelas analiticas e a correta e decisao de dominio, nao de
-- software: se a segunda for a que interessa, isso se resolve recoletando a
-- origem. Nao decida isso por heuristica no codigo.
--
-- COMO USAR, a partir da pasta entrega_tbca/:
--   psql "$DATABASE_URL" -f sql/01_schema.sql
--   psql "$DATABASE_URL" -f sql/03_deduplicar_food_nutrients.sql
-- =============================================================================

begin;

-- As tres tabelas sem duplicidade entram direto.
\copy public.nutrients (code, display_name, unit, nutrient_group, decimal_places, synonyms) from 'csv/nutrients.csv' with (format csv, header true, null '')

\copy public.foods (code, name, scientific_name, group_code, group_name, type_code, type_name, brand, description_pt, description_en, description_es, energy_kcal_per_100g, energy_kj_per_100g, measure_count, composition_collected, source_url, tbca_version, collected_at) from 'csv/foods.csv' with (format csv, header true, null '')

\copy public.measures (food_code, measure_index, measure_name, measure_unit, measure_quantity, measure_grams, is_duplicate_name) from 'csv/measures.csv' with (format csv, header true, null '')

-- food_nutrients: estagio sem chave -> tabela final com distinct on
create temporary table stg_food_nutrients (
  food_code      text,
  nutrient_code  text,
  value_per_100g numeric(14,6),
  value_status   text,
  value_text     text,
  ordem          bigserial
) on commit drop;

\copy stg_food_nutrients (food_code, nutrient_code, value_per_100g, value_status, value_text) from 'csv/food_nutrients.csv' with (format csv, header true, null '')

insert into public.food_nutrients (food_code, nutrient_code, value_per_100g, value_status, value_text)
select distinct on (food_code, nutrient_code)
       food_code, nutrient_code, value_per_100g, value_status, value_text
from stg_food_nutrients
order by food_code, nutrient_code, ordem;

-- measure_nutrients: mesma coisa, chave de tres colunas
create temporary table stg_measure_nutrients (
  food_code              text,
  measure_index          smallint,
  nutrient_code          text,
  value_measure          numeric(14,6),
  value_per_100g_derived numeric(14,6),
  value_status           text,
  ordem                  bigserial
) on commit drop;

\copy stg_measure_nutrients (food_code, measure_index, nutrient_code, value_measure, value_per_100g_derived, value_status) from 'csv/measure_nutrients.csv' with (format csv, header true, null '')

insert into public.measure_nutrients (food_code, measure_index, nutrient_code, value_measure, value_per_100g_derived, value_status)
select distinct on (food_code, measure_index, nutrient_code)
       food_code, measure_index, nutrient_code, value_measure, value_per_100g_derived, value_status
from stg_measure_nutrients
order by food_code, measure_index, nutrient_code, ordem;

-- conferencia da deduplicacao
select 'food_nutrients' as tabela, count(*) as linhas from public.food_nutrients
union all select 'measure_nutrients', count(*) from public.measure_nutrients;
-- esperado: food_nutrients 240787 | measure_nutrients 336640

analyze public.nutrients;
analyze public.foods;
analyze public.food_nutrients;
analyze public.measures;
analyze public.measure_nutrients;

commit;

-- =============================================================================
-- CONFERENCIA FINAL
-- =============================================================================
select 'nutrients' as tabela, count(*) as linhas from public.nutrients
union all select 'foods',             count(*) from public.foods
union all select 'food_nutrients',    count(*) from public.food_nutrients
union all select 'measures',          count(*) from public.measures
union all select 'measure_nutrients', count(*) from public.measure_nutrients
order by 1;
-- nutrients 41 | foods 5874 | food_nutrients 240787
-- measures 8213 | measure_nutrients 336640

-- os 8 alimentos afetados ficam com o conjunto completo depois da deduplicacao
select count(*) as alimentos_com_41_nutrientes
from (
  select food_code from public.food_nutrients group by food_code having count(*) = 41
) t;
-- esperado 5868 (5862 intactos + 6 dos 8 deduplicados)
