# Coletor de Dados da TBCA

**scrape_tbca.py** é um script em Python que realiza a extração automatizada dos dados da [Tabela Brasileira de Composição de Alimentos (TBCA)](https://www.tbca.net.br), consolidando as informações em uma planilha Excel e em arquivos JSON. Utilizado para a criação de banco de dados na Graduação em Sistemas de Informação PUC-Minas, alimentando aplicação desenvolvida para cálculo de valores nutricionais das refeições.

---

## Visão Geral

O script percorre a listagem de alimentos da TBCA, abre a **página de composição de cada alimento** e coleta:

- identificação: código, nome, nome científico, grupo, tipo de alimento, marca e descrição (com as traduções em inglês e espanhol);
- **valores de nutrientes por 100 g** da parte comestível (energia, macronutrientes, minerais e vitaminas);
- **valores por medida caseira** (colher de sopa, copo americano, prato raso, unidade etc.), com a quantidade em gramas ou mililitros de cada medida.

Saídas:

| Arquivo | Conteúdo |
| --- | --- |
| `tabela_composicao_alimentos_completa.xlsx` | planilha com 6 abas: `Resumo`, `Alimentos`, `Nutrientes_100g`, `Nutrientes`, `Medidas`, `Problemas` |
| `dados_tbca/<CÓDIGO>.json` | um arquivo por alimento, com `por_100g`, `componentes` (valor + status) e `medidas` |
| `dados_tbca/db.json` | todos os alimentos em um único JSON, para carga direta na aplicação |

A coleta usa `requests` e `BeautifulSoup` para o scraping, e `pandas` para tratamento e exportação dos dados.

---

## Funcionalidades

- Coleta automática de todos os alimentos da listagem e de suas páginas de composição
- Leitura da tabela de nutrientes com as colunas de medidas caseiras, que variam de alimento para alimento
- Conversão dos valores do site (`86,3`, `tr`, `NA`, `*7,32`) para número, preservando a distinção entre **traço** (`tr` = 0,0 relatado) e **ausente** (`NA` = dado não publicado)
- Exportação em Excel **e** em JSON (um arquivo por alimento + `db.json`)
- Cache local: o HTML de cada página e o JSON de cada alimento são reaproveitados em execuções seguintes, então uma execução interrompida continua de onde parou

---

## Requisitos

- Python 3.9 ou superior
- Bibliotecas: `pandas`, `requests`, `beautifulsoup4`, `openpyxl` (para o Excel)

Instale todas as dependências executando:

```bash
pip install -r requirements.txt
```

Se o repositório ainda não tiver o `requirements.txt`:

```bash
pip install pandas requests beautifulsoup4 openpyxl
```

---

## Uso

Coleta completa (grava a planilha e o JSON):

```bash
python scrape_tbca.py
```

Teste rápido com os 5 primeiros alimentos:

```bash
python scrape_tbca.py --limit 5
```

Somente JSON, sem planilha:

```bash
python scrape_tbca.py --format json
```

Para conferir como um único alimento é interpretado (não grava nada):

```bash
python scrape_tbca.py --inspect "https://www.tbca.net.br/base-dados/int_composicao_alimentos.php?n0REd3kv7e86D%2BViXWYUnQ%3D%3D=QagWPGGLCefQ%2BGqdjKbs2w%3D%3D"
python scrape_tbca.py --inspect cache_tbca/BRC0001C.html
```

Reprocessar páginas já salvas em disco, sem internet:

```bash
python scrape_tbca.py --from-html-dir cache_tbca --out testes.xlsx
```

### Opções principais

| Opção | Padrão | Descrição |
| --- | --- | --- |
| `--url` | listagem da TBCA | URL da listagem de alimentos |
| `--out` | `tabela_composicao_alimentos_completa.xlsx` | arquivo Excel de saída |
| `--json-dir` | `dados_tbca` | pasta dos arquivos JSON |
| `--format` | `ambos` | `ambos`, `excel` ou `json` |
| `--limit` | `0` (todos) | processa somente os N primeiros alimentos |
| `--delay` | `1.0` | intervalo entre requisições de cada worker, em segundos |
| `--workers` | `2` | requisições simultâneas |
| `--retries` | `3` | tentativas por página, com backoff exponencial |
| `--no-cache` / `--no-json` | — | desliga o cache local de HTML / a saída JSON |
| `--force` | — | ignora cache de HTML e de JSON e baixa tudo novamente |

A coleta completa da TBCA passa de 5.800 alimentos: com os padrões (`--workers 2 --delay 1.0`) leva cerca de 45 a 50 minutos. Para retomar depois de uma interrupção, basta rodar de novo: o que já foi coletado é lido do JSON e não é baixado outra vez.

---

## Estrutura dos dados

Planilha:

- `Resumo`: indicadores da execução e inventário de componentes/medidas encontrados
- `Alimentos`: um alimento por linha (identificação, descrição, URL e se a composição foi coletada)
- `Nutrientes_100g`: um alimento por linha e um componente por coluna, já com a unidade no nome da coluna (`Energia (kcal)`, `Proteína (g)`)
- `Nutrientes`: formato longo (1 linha por componente por alimento), com o texto original e o `Status`
- `Medidas`: 1 linha por componente por medida caseira, com `Medida`, `Unidade da medida`, `Quantidade da medida` e `Valor`
- `Problemas`: páginas ou valores que não puderam ser interpretados

Coluna `Status`, presente nas abas longas e no JSON:

| Status | Significado |
| --- | --- |
| `valor` | número publicado pela TBCA |
| `traço` | valor `tr`: a TBCA relata o componente como traço, gravado como `0.0` |
| `ausente` | valor `NA` ou vazio: dado não publicado, gravado como vazio/`null` |

Exemplo de JSON individual:

```json
{
  "codigo": "BRC0001C",
  "nome": "Abacate, polpa, in natura, Brasil",
  "nome_cientifico": "Persea americana Mill",
  "grupo": "Frutas e derivados",
  "grupo_completo": "C - Frutas e derivados",
  "tipo_alimento": "A - Alimento in natura",
  "por_100g": { "Energia (kcal)": 76.0, "Umidade (g)": 86.3, "Proteína (g)": 1.15 },
  "componentes": [
    {
      "componente": "Sódio", "unidade": "mg", "valor_100g": 0.0,
      "status": "traço", "texto_original": "tr",
      "medidas": [
        { "indice": 3, "valor": 0.0, "status": "traço" },
        { "indice": 4, "valor": null, "status": "ausente" }
      ]
    }
  ],
  "medidas": [
    { "indice": 3, "nome": "Colher sopa cheia", "unidade": "g", "quantidade": 45.0 }
  ]
}
```

---

## Testes

Os testes rodam offline, contra páginas de exemplo salvas em `tests/samples`:

```bash
python tests/test_parsing.py
# ou
python -m pytest tests -q
```

Eles cobrem a conversão de valores (`tr`, `NA`, vírgula decimal, asterisco da fonte), a leitura dos cabeçalhos de medidas caseiras, o casamento entre a listagem e os links de composição, a geração da planilha e do JSON, e o reaproveitamento do JSON como cache.

---

## Nota sobre a fonte

Os dados são de propriedade da TBCA (USP/FoRC). A reprodução total ou parcial do material exige a citação da fonte, e não é permitida a comercialização nem a alteração do conteúdo (Creative Commons BY-NC-ND 4.0). O script mantém um intervalo entre requisições para não sobrecarregar o servidor; evite reduzir `--delay` ou aumentar `--workers` de forma agressiva.
