-- =============================================================================
-- TBCA - carga dos CSVs no Supabase / PostgreSQL
--
-- COMO USAR
--   Rode 01_schema.sql primeiro, depois este arquivo.
--   A partir da pasta entrega_tbca/ (a pasta csv/ fica ao lado):
--
--     psql "$DATABASE_URL" -f sql/01_schema.sql
--     psql "$DATABASE_URL" -f sql/02_carga.sql
--
--   DATABASE_URL (Project Settings > Database > Connection string > URI):
--     postgresql://postgres.<ref>:<SENHA>@aws-0-<regiao>.pooler.supabase.com:5432/postgres
--
-- POR QUE \copy E NAO COPY
--   \copy e um comando do psql: o arquivo e lido na maquina do cliente.
--   COPY ... FROM '/caminho' le no servidor e falha no Supabase hospedado.
--
-- ORDEM OBRIGATORIA
--   nutrients -> foods -> food_nutrients -> measures -> measure_nutrients
--   As chaves estrangeiras exigem que a dimensao exista antes do fato.
-- =============================================================================

begin;

-- 1. catalogo de nutrientes (41 linhas)
\copy public.nutrients (code, display_name, unit, nutrient_group, decimal_places, synonyms) from 'csv/nutrients.csv' with (format csv, header true, null '')

-- 2. identificacao dos alimentos (5.874 linhas)
\copy public.foods (code, name, scientific_name, group_code, group_name, type_code, type_name, brand, description_pt, description_en, description_es, energy_kcal_per_100g, energy_kj_per_100g, measure_count, composition_collected, source_url, tbca_version, collected_at) from 'csv/foods.csv' with (format csv, header true, null '')

-- 3. composicao por 100 g (241.060 linhas)
\copy public.food_nutrients (food_code, nutrient_code, value_per_100g, value_status, value_text) from 'csv/food_nutrients.csv' with (format csv, header true, null '')

-- 4. medidas caseiras por alimento (8.213 linhas)
\copy public.measures (food_code, measure_index, measure_name, measure_unit, measure_quantity, measure_grams, is_duplicate_name) from 'csv/measures.csv' with (format csv, header true, null '')

-- 5. valor do nutriente por medida caseira (336.989 linhas)
\copy public.measure_nutrients (food_code, measure_index, nutrient_code, value_measure, value_per_100g_derived, value_status) from 'csv/measure_nutrients.csv' with (format csv, header true, null '')

-- Estatisticas do planejador. Sem o ANALYZE as primeiras consultas do app
-- escolhem plano ruim nas tabelas grandes.
analyze public.nutrients;
analyze public.foods;
analyze public.food_nutrients;
analyze public.measures;
analyze public.measure_nutrients;

commit;

-- =============================================================================
-- Se a carga for interrompida no meio: rode 01_schema.sql de novo (ele apaga as
-- tabelas) e refaca a carga. Nao tente retomar de onde parou: as tabelas de
-- fato tem chave primaria composta e o \copy aborta no primeiro duplicado.
-- =============================================================================

-- =============================================================================
-- CONFERENCIA (as contagens tem que bater)
-- =============================================================================
select 'nutrients' as tabela, count(*) as linhas from public.nutrients
union all select 'foods',             count(*) from public.foods
union all select 'food_nutrients',    count(*) from public.food_nutrients
union all select 'measures',          count(*) from public.measures
union all select 'measure_nutrients', count(*) from public.measure_nutrients
order by 1;
-- nutrients 41 | foods 5874 | food_nutrients 241060
-- measures 8213 | measure_nutrients 336989
