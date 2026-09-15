-- =============================================================================
-- TBCA - Tabela Brasileira de Composicao de Alimentos
-- Schema de importacao para Supabase / PostgreSQL 15+
--
-- Fonte dos dados: https://www.tbca.net.br  (USP/FoRC)
-- Licenca dos dados: CC BY-NC-ND 4.0
--   - citacao da fonte obrigatoria;
--   - vedada a comercializacao;
--   - vedada a alteracao do conteudo (valores nao podem ser editados).
--
-- Convencao de nulos: coluna de texto sem valor entra como NULL na carga
-- (o \copy usa "null ''"). Nao ha string vazia gravada no banco.
-- =============================================================================

-- Extensoes uteis (opcionais). pg_trgm acelera busca por nome com ILIKE.
create extension if not exists pg_trgm;

-- -----------------------------------------------------------------------------
-- Limpeza (idempotente). Remova este bloco se quiser preservar dados existentes.
-- -----------------------------------------------------------------------------
drop table if exists public.measure_nutrients cascade;
drop table if exists public.measures cascade;
drop table if exists public.food_nutrients cascade;
drop table if exists public.nutrients cascade;
drop table if exists public.foods cascade;

-- =============================================================================
-- 1. nutrients - catalogo de nutrientes (dimensao). 41 linhas.
--    Importe ANTES de food_nutrients e measure_nutrients.
-- =============================================================================
create table public.nutrients (
  code            text primary key,
  display_name    text not null,
  unit            text not null check (unit in ('g', 'mg', 'mcg', 'kJ', 'kcal')),
  nutrient_group  text not null check (nutrient_group in
                    ('energia', 'proximais', 'carboidratos', 'proteina',
                     'lipidios', 'fibra', 'minerais', 'vitaminas', 'adicao')),
  decimal_places  smallint not null default 2,
  synonyms        text
);

comment on table  public.nutrients is
  'Catalogo dos 41 componentes da TBCA. code e o identificador estavel usado em food_nutrients e measure_nutrients.';
comment on column public.nutrients.decimal_places is
  'Casas decimais usadas pela TBCA ao arredondar o valor por medida caseira.';
comment on column public.nutrients.synonyms is
  'Nomes alternativos separados por ponto e virgula, para busca livre.';

-- =============================================================================
-- 2. foods - identificacao do alimento. 5.874 linhas.
-- =============================================================================
create table public.foods (
  code                 text primary key,          -- codigo TBCA, ex.: BRC0001C
  name                 text not null,
  scientific_name      text,                      -- so 1.652 alimentos tem
  group_code           text,                      -- A..U (categoria TBCA)
  group_name           text,                      -- 'Frutas e derivados'
  type_code            text,                      -- A, B, C, D, F, L
  type_name            text,                      -- 'Alimento in natura', 'Preparacao'...
  brand                text,                      -- so 331 alimentos tem
  description_pt       text,
  description_en       text,
  description_es       text,
  energy_kcal_per_100g numeric(10,2),             -- desnormalizado: uso constante
  energy_kj_per_100g   numeric(10,2),
  measure_count        smallint not null default 0,
  composition_collected boolean not null default true,
  source_url           text,
  tbca_version         text,
  collected_at         timestamptz
);

comment on table  public.foods is
  'Um alimento (ou preparacao) da TBCA. Prefixo do code indica a categoria: BRC + 4 digitos + letra do grupo.';
comment on column public.foods.energy_kcal_per_100g is
  'Copia de food_nutrients para o nutriente energy_kcal. Mantida aqui porque o calculo de plano alimentar le a energia em toda consulta. NULL em 5 alimentos.';
comment on column public.foods.measure_count is
  'Quantidade de medidas caseiras com unidade (g ou mL) e gramatura validas. 0 em 317 alimentos.';
comment on column public.foods.composition_collected is
  'false = alimento listado na TBCA mas sem tabela de composicao publicada. Nesta coleta todos sao true.';

create index foods_group_code_idx  on public.foods (group_code);
create index foods_type_code_idx   on public.foods (type_code);
create index foods_name_trgm_idx   on public.foods using gin (name gin_trgm_ops);
create index foods_name_lower_idx  on public.foods (lower(name));

-- =============================================================================
-- 3. food_nutrients - valor por 100 g da parte comestivel. 241.060 linhas.
--    Uma linha por alimento x nutriente (formato longo).
-- =============================================================================
create table public.food_nutrients (
  food_code      text not null references public.foods (code) on delete cascade,
  nutrient_code  text not null references public.nutrients (code) on delete restrict,
  value_per_100g numeric(14,6),                   -- null quando value_status = 'ausente'
  value_status   text not null check (value_status in ('valor', 'traco', 'ausente')),
  value_text     text,                            -- texto original: 'tr', 'NA', '7,32'
  primary key (food_code, nutrient_code)
);

comment on table  public.food_nutrients is
  'Composicao por 100 g da parte comestivel. E a fonte de verdade para calculo: valor da refeicao = value_per_100g * gramas / 100.';
comment on column public.food_nutrients.value_status is
  'valor = numero publicado; traco = TBCA relata "tr" (gravado como 0.0); ausente = "NA"/vazio, dado nao publicado (value_per_100g = null).';
comment on column public.food_nutrients.value_text is
  'Texto como aparece na TBCA. Util para auditoria e para exibir o valor bruto ao nutricionista.';

create index food_nutrients_nutrient_idx on public.food_nutrients (nutrient_code);
create index food_nutrients_status_idx   on public.food_nutrients (value_status);

-- =============================================================================
-- 4. measures - medidas caseiras registradas por alimento. 8.213 linhas.
--    ATENCAO: measure_index NAO e um catalogo global de medidas caseiras.
--    Ele e apenas a posicao da coluna na pagina do alimento, ou seja,
--    o indice 3 pode ser 'Colher sopa cheia' em um alimento e
--    'Pedaco/ Unidade/ Fatia (M)' em outro. A identidade da medida e
--    (food_code, measure_index); o significado esta em measure_name.
-- =============================================================================
create table public.measures (
  food_code         text not null references public.foods (code) on delete cascade,
  measure_index     smallint not null,
  measure_name      text not null,
  measure_unit      text not null check (measure_unit in ('g', 'mL')),
  measure_quantity  numeric(10,2) not null check (measure_quantity > 0),
  measure_grams     numeric(10,2) not null check (measure_grams > 0),
  is_duplicate_name boolean not null default false,
  primary key (food_code, measure_index)
);

comment on table  public.measures is
  'Medida caseira padronizada pela TBCA para um alimento especifico: quantos gramas (ou mL) corresponde uma colher, copo, fatia etc.';
comment on column public.measures.measure_index is
  'Posicao da medida na tabela da TBCA para aquele alimento. So tem significado junto de food_code. Vai de 3 a 13 e nao e continuo.';
comment on column public.measures.measure_unit is
  'g = massa; mL = volume. Nao ha densidade na TBCA: mL nao pode ser convertido em gramas sem uma tabela de densidade.';
comment on column public.measures.measure_grams is
  'Redundante com measure_quantity de proposito: e sempre a gramatura da medida caseira.';
comment on column public.measures.is_duplicate_name is
  'true = o mesmo measure_name aparece mais de uma vez no alimento com gramaturas diferentes (ex.: colher servir 45 g e 60 g). Exija escolha explicita do usuario. 50 linhas.';

create index measures_name_idx on public.measures (measure_name);
create index measures_food_idx on public.measures (food_code);

-- =============================================================================
-- 5. measure_nutrients - valor do nutriente PARA A MEDIDA CASEIRA. 336.989 linhas.
-- =============================================================================
create table public.measure_nutrients (
  food_code              text not null,
  measure_index          smallint not null,
  nutrient_code          text not null references public.nutrients (code) on delete restrict,
  value_measure          numeric(14,6),           -- numero publicado pela TBCA
  value_per_100g_derived numeric(14,6),           -- recalculado de food_nutrients x measure_grams
  value_status           text not null check (value_status in ('valor', 'traco', 'ausente')),
  primary key (food_code, measure_index, nutrient_code),
  foreign key (food_code, measure_index)
    references public.measures (food_code, measure_index) on delete cascade
);

comment on table  public.measure_nutrients is
  'Valor do nutriente para UMA medida caseira inteira (nao por grama). Ex.: 1 colher sopa cheia de abacate = 34 kcal.';
comment on column public.measure_nutrients.value_measure is
  'Valor publicado pela TBCA para a medida, com o arredondamento da propria TBCA. Compare com value_per_100g_derived antes de confiar: ha divergencia em 2,6% das linhas.';
comment on column public.measure_nutrients.value_per_100g_derived is
  'Recalculo de food_nutrients.value_per_100g * measures.measure_grams / 100. Serve para conferencia e para preencher lacunas, nao como fonte de verdade.';
comment on column public.measure_nutrients.value_status is
  'Mesmo dominio de food_nutrients.value_status.';

create index measure_nutrients_nutrient_idx on public.measure_nutrients (nutrient_code);
create index measure_nutrients_food_idx     on public.measure_nutrients (food_code);

-- =============================================================================
-- 6. Row Level Security
--    Dados de referencia: leitura publica, escrita apenas via service_role
--    (migrations / SQL editor). Nao ha dado de usuario nestas tabelas.
-- =============================================================================
alter table public.nutrients         enable row level security;
alter table public.foods             enable row level security;
alter table public.food_nutrients    enable row level security;
alter table public.measures          enable row level security;
alter table public.measure_nutrients enable row level security;

drop policy if exists nutrients_read on public.nutrients;
create policy nutrients_read on public.nutrients
  for select to anon, authenticated using (true);

drop policy if exists foods_read on public.foods;
create policy foods_read on public.foods
  for select to anon, authenticated using (true);

drop policy if exists food_nutrients_read on public.food_nutrients;
create policy food_nutrients_read on public.food_nutrients
  for select to anon, authenticated using (true);

drop policy if exists measures_read on public.measures;
create policy measures_read on public.measures
  for select to anon, authenticated using (true);

drop policy if exists measure_nutrients_read on public.measure_nutrients;
create policy measure_nutrients_read on public.measure_nutrients
  for select to anon, authenticated using (true);

-- Nenhuma policy de insert/update/delete: sem elas, os roles anon e
-- authenticated nao escrevem. A carga roda com a service_role key ou pelo
-- SQL editor.

-- =============================================================================
-- 7. View de apoio: alimento pronto para o montador de plano alimentar
-- =============================================================================
create or replace view public.food_full as
select
  f.code,
  f.name,
  f.scientific_name,
  f.group_code,
  f.group_name,
  f.type_code,
  f.type_name,
  f.brand,
  f.energy_kcal_per_100g,
  f.energy_kj_per_100g,
  f.measure_count,
  f.source_url,
  coalesce(
    jsonb_object_agg(fn.nutrient_code, fn.value_per_100g)
      filter (where fn.value_status <> 'ausente'),
    '{}'::jsonb
  ) as nutrients_per_100g,
  coalesce(
    jsonb_object_agg(fn.nutrient_code, fn.value_status)
      filter (where fn.value_status = 'ausente'),
    '{}'::jsonb
  ) as nutrients_ausentes
from public.foods f
left join public.food_nutrients fn on fn.food_code = f.code
group by f.code;

comment on view public.food_full is
  'Alimento com os nutrientes por 100 g agregados em JSON. Comodo para o app; para calculo em lote use food_nutrients direto.';

-- =============================================================================
-- 8. Os oito alimentos com componente duplicado na coleta
--
-- A pagina desses alimentos na TBCA publica duas tabelas de composicao e a
-- coleta gravou as duas. Como a PK de food_nutrients e composta, a segunda
-- ocorrencia faz a carga direta abortar (ha 273 linhas a mais que o esperado).
--
-- Duas saidas, ambas legitimas:
--   (a) importar por tabela de estagio e manter a primeira ocorrencia de cada
--       nutriente  ->  sql/03_deduplicar_food_nutrients.sql;
--   (b) excluir estes 8 codigos do catalogo.
-- Ver ANALISE-DOS-DADOS.md secao 4.1.
-- =============================================================================
create or replace view public.food_componentes_duplicados as
select code, name
from public.foods
where code in ('BRC0004A', 'BRC0237T', 'BRC0953F', 'BRC0955F',
               'BRC0956F', 'BRC0957F', 'BRC1145B', 'BRC1196B');

comment on view public.food_componentes_duplicados is
  'Os 8 alimentos cuja coleta trouxe componente repetido. Revise antes de usar em plano alimentar.';

-- =============================================================================
-- 9. Conferencia pos-carga (rode depois de 02_carga.sql)
--
-- Os valores esperados estao nos comentarios. Se qualquer contagem divergir,
-- a carga foi parcial e deve ser repetida (02_carga.sql e idempotente).
-- =============================================================================

-- contagens por tabela
select 'nutrients' as tabela, count(*) as linhas from public.nutrients
union all select 'foods',             count(*) from public.foods
union all select 'food_nutrients',    count(*) from public.food_nutrients
union all select 'measures',          count(*) from public.measures
union all select 'measure_nutrients', count(*) from public.measure_nutrients
order by 1;
-- esperado: food_nutrients 241060 | foods 5874 | measure_nutrients 336989
--           measures 8213 | nutrients 41

-- distribuicao de status em food_nutrients
select value_status, count(*) as linhas
from public.food_nutrients
group by 1
order by 2 desc;
-- esperado: valor 215110 | ausente 20310 | traco 5640

-- nenhum alimento pode ficar sem energia nem sem medida caseira valida
select count(*) as sem_energia
from public.foods where energy_kcal_per_100g is null;
-- esperado: 5

select count(*) as sem_medida
from public.foods where measure_count = 0;
-- esperado: 317
