#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script: scrape_tbca.py
Descrição: Coleta a lista de alimentos da TBCA (Tabela Brasileira de Composição
           de Alimentos) e, para cada alimento, baixa a página de composição com
           os valores de nutrientes por 100 g e por medidas caseiras.
Autor: Lucas Prieto Accorsi
Data: 2025-11-04
Versão: 2.0

Estrutura do site (verificada em 2025-11):
    base-dados/composicao_alimentos.php
        -> tabela HTML com Código | Nome | Nome Científico | Grupo | Marca
        -> links para base-dados/int_composicao_alimentos.php?<token>=<hash>

    base-dados/int_composicao_alimentos.php?<token>=<hash>
        -> <h5> com Código, Grupo, Tipo de Alimento, Nome Científico e Descrição
        -> tabela #tabela1 com Componente | Unidades | Valor por 100g | medidas

O nome do parâmetro da query (?<token>=) é ofuscado e pode mudar; por isso os
links de detalhe são sempre descobertos a partir da página de listagem, nunca
montados à mão.

Saídas (planilha Excel):
    Resumo           - indicadores da execução e inventário de componentes/medidas
    Alimentos        - um alimento por linha (identificação + URL de origem)
    Nutrientes_100g  - um alimento por linha, um componente por coluna (base 100 g)
    Nutrientes       - formato longo: 1 linha por componente por alimento
    Medidas          - formato longo: 1 linha por componente por medida caseira
    Problemas        - páginas/valores que não puderam ser interpretados

Saídas (JSON, pasta dados_tbca/):
    <CÓDIGO>.json    - um arquivo por alimento, com "por_100g", "componentes"
                       (valor + status) e "medidas"; serve também de cache, então
                       uma nova execução não baixa de novo o que já foi coletado
    db.json          - todos os alimentos, para carga direta em aplicações
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup, NavigableString, Tag

# --- CONFIGURAÇÃO ---

LISTING_URL = "https://www.tbca.net.br/base-dados/composicao_alimentos.php"
DETAIL_PAGE = "int_composicao_alimentos.php"

VERSAO_SCRAPER = "2.1"
OUTPUT_FILENAME = "tabela_composicao_alimentos_completa.xlsx"
CACHE_DIR = "cache_tbca"
JSON_DIR = "dados_tbca"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
}

# Intervalo mínimo entre requisições de cada worker (segundos).
MIN_DELAY = 0.3

# Unidades reconhecidas para interpretar medidas caseiras:
# "Colher sopa cheia (45 g)" -> 45 g.
MEASURE_UNITS = {
    "g": "g",
    "grama": "g",
    "gramas": "g",
    "kg": "kg",
    "mg": "mg",
    "ml": "mL",
    "mililitro": "mL",
    "mililitros": "mL",
    "l": "L",
    "litro": "L",
    "litros": "L",
}

# Valores textuais que significam traço/zero em vez de dado ausente.
TRACE_TOKENS = {"tr", "traco", "tracos", "trace", "vestigio", "vestigios"}
MISSING_TOKENS = {"", "na", "n/a", "nd", "-", "--", "---"}

# Rótulos do bloco de identificação (<h5>) da página de composição.
INFO_KEY_LABELS = {
    "Código": "codigo",
    "Grupo": "grupo",
    "Tipo de Alimento": "tipo_alimento",
    "Nome Científico": "nome_cientifico",
    "Descrição": "descricao",
}
INFO_KEYS = list(INFO_KEY_LABELS.values()) + ["descricao_completa", "traducoes"]


@dataclass
class Settings:
    """Parâmetros de coleta."""

    listing_url: str = LISTING_URL
    out: Path = Path(OUTPUT_FILENAME)
    delay: float = 1.0
    workers: int = 2
    listing_delay: float = 0.3
    retries: int = 3
    timeout: float = 30.0
    cache_dir: Path | None = Path(CACHE_DIR)
    json_dir: Path | None = Path(JSON_DIR)
    formatos: str = "ambos"
    limit: int = 0
    force: bool = False
    quiet: bool = False
    issues: list[dict[str, str]] = field(default_factory=list)

    def report(self, codigo: str, url: str, problema: str) -> None:
        """Registra um problema (aba 'Problemas') sem interromper a coleta."""
        self.issues.append({"Código": codigo, "URL": url, "Problema": problema})
        if not self.quiet:
            print(f"      [AVISO] {codigo or url}: {problema}")


# --- NORMALIZAÇÃO DE VALORES ---

_WS_RE = re.compile(r"\s+")
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([,;:.!?)\]])")
_SPACE_AFTER_OPEN_RE = re.compile(r"([(\[])\s+")
_NUMBER_RE = re.compile(r"[^\d,.\-]")


def clean_text(value: Any) -> str:
    """
    Normaliza um texto: remove espaços redundantes, NBSP/BOM e o espaço que sobra
    antes da pontuação quando o HTML quebra a frase em várias tags
    ("polpa, <i>in natura</i>, Brasil" -> "... in natura, Brasil").
    """
    if value is None:
        return ""
    text = str(value)
    for junk in ("\xa0", "\u200b", "\ufeff", "\u2212"):
        text = text.replace(junk, " " if junk == "\xa0" else "")
    text = _WS_RE.sub(" ", text).strip()
    text = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", text)
    text = _SPACE_AFTER_OPEN_RE.sub(r"\1", text)
    return text


def normalize_unit(value: Any) -> str:
    """Normaliza unidade: 'mcg ' / ' mcg' / 'g (*)' -> 'mcg' / 'g'."""
    return clean_text(value).strip("*").strip()


def normalize_component(value: Any) -> str:
    """Normaliza o nome de um componente nutricional."""
    return clean_text(value).rstrip(":").strip()


def parse_value(raw: Any) -> tuple[float | None, str]:
    """
    Converte o valor bruto da tabela em número.

      '-' / 'NA' / vazio  -> (None, 'ausente')
      'tr'                -> (0.0, 'traço')
      '0,00'              -> (0.0, 'valor')
      '*7,32'             -> (7.32, 'valor')   (asterisco marca dado da fonte)
      '6,21 (*)'          -> (6.21, 'valor')

    O status fica explícito para que traço (zero real medido) e ausente
    (dado não publicado) não sejam confundidos na planilha.
    """
    text = clean_text(raw)
    if text == "":
        return None, "ausente"

    lowered = text.lower()
    if lowered in MISSING_TOKENS:
        return None, "ausente"
    if lowered in TRACE_TOKENS:
        return 0.0, "traço"

    cleaned = _NUMBER_RE.sub("", text.replace(" ", ""))
    if cleaned in ("", "-", ".", ","):
        return None, "traço" if "*" in text else "ausente"

    # O site usa vírgula decimal e, às vezes, ponto de milhar (ex.: 1.155,3).
    if "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif cleaned.count(".") > 1:
        cleaned = cleaned.replace(".", "")

    try:
        return float(cleaned), "valor"
    except ValueError:
        return None, "invalido"


def top_level_parentheses(text: str) -> list[tuple[int, int]]:
    """Devolve os pares (início, fim) dos parênteses mais externos de um texto."""
    spans: list[tuple[int, int]] = []
    depth = 0
    start = -1
    for index, char in enumerate(text):
        if char == "(":
            if depth == 0:
                start = index
            depth += 1
        elif char == ")" and depth > 0:
            depth -= 1
            if depth == 0:
                spans.append((start, index))
    return spans


def parse_measure_header(header: str) -> tuple[str, str, float | None]:
    """
    Interpreta o cabeçalho de uma coluna de medida caseira.

      'Colher sopa cheia (45 g)'           -> ('Colher sopa cheia', 'g', 45.0)
      'Copo americano duplo (200 mL)'      -> ('Copo americano duplo', 'mL', 200.0)
      'Pedaço/ Unidade/ Fatia (M) (370 g)' -> ('Pedaço/ Unidade/ Fatia (M)', 'g', 370.0)
      'Copo americano pequeno (130 mL)'    -> ('Copo americano pequeno', 'mL', 130.0)

    Sem unidade reconhecida, o texto integral é preservado como nome da medida.
    """
    text = clean_text(header)
    if not text:
        return "", "", None

    for start, end in reversed(top_level_parentheses(text)):
        inner = clean_text(text[start + 1 : end])
        match = re.fullmatch(r"([\d.,]+)\s*([A-Za-zç]+)", inner)
        if match and match.group(2).strip().lower() in MEASURE_UNITS:
            amount, status = parse_value(match.group(1))
            unit_key = match.group(2).strip().lower()
            name = clean_text(text[:start] + " " + text[end + 1 :]) or text
            return name, MEASURE_UNITS[unit_key], (amount if status == "valor" else None)

    return text, "", None


# --- REQUISIÇÕES ---

def build_session() -> requests.Session:
    """Cria uma sessão HTTP com cabeçalhos de navegador."""
    session = requests.Session()
    session.headers.update(HEADERS)
    return session


def fetch_html(session: requests.Session, url: str, settings: Settings) -> str | None:
    """Baixa uma página com retentativas e backoff exponencial."""
    last_error = ""
    for attempt in range(1, settings.retries + 1):
        try:
            response = session.get(url, timeout=settings.timeout)
            if response.status_code == 404:
                last_error = "HTTP 404 (página inexistente)"
                break
            response.raise_for_status()
            if not response.encoding or response.encoding.lower() == "iso-8859-1":
                response.encoding = response.apparent_encoding or "utf-8"
            return response.text
        except requests.exceptions.RequestException as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < settings.retries:
                time.sleep(min(2 ** attempt, 15) + random.uniform(0.0, 0.5))
    settings.report("", url, f"falha ao baixar ({last_error})")
    return None


def cache_file(settings: Settings, codigo: str) -> Path | None:
    if settings.cache_dir is None:
        return None
    return Path(settings.cache_dir) / f"{codigo or 'sem-codigo'}.html"


# --- DESCOBERTA DOS ALIMENTOS (PÁGINA DE LISTAGEM) ---

def read_listing_table(soup: BeautifulSoup) -> tuple[list[str], list[list[str]]]:
    """Extrai cabeçalho e linhas da tabela de listagem de alimentos."""
    table = soup.find("table", id=re.compile(r"tabela", re.I)) or soup.find("table")
    if table is None:
        return [], []

    header_cells = [clean_text(th.get_text(" ", strip=True)) for th in table.find_all("th")]
    if not header_cells:
        first_row = table.find("tr")
        if first_row is not None:
            header_cells = [clean_text(td.get_text(" ", strip=True)) for td in first_row.find_all("td")]

    rows: list[list[str]] = []
    body = table.find("tbody") or table
    for tr in body.find_all("tr"):
        cells = [clean_text(td.get_text(" ", strip=True)) for td in tr.find_all("td")]
        if cells and any(cells):
            rows.append(cells)
    return header_cells, rows


def extract_detail_links(soup: BeautifulSoup, page_url: str) -> list[dict[str, str]]:
    """
    Coleta os links das páginas de composição e o código do alimento.

    O parâmetro da query é ofuscado (ex.: n0REd3kv7e86D+ViXWYUnQ==), então a
    detecção é feita pelo arquivo de destino, não pelo nome do parâmetro.
    """
    found: list[dict[str, str]] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if DETAIL_PAGE not in href:
            continue
        url = urljoin(page_url, href)
        if url in seen:
            continue
        seen.add(url)
        codigo = clean_text(anchor.get_text(" ", strip=True))
        if not re.fullmatch(r"[A-Za-z]{2,4}\d{3,5}[A-Za-z]?", codigo):
            codigo = ""
        found.append({"codigo": codigo, "url": url})
    return found


def discover_foods(soup: BeautifulSoup, page_url: str, settings: Settings) -> list[dict[str, Any]]:
    """Casa cada linha da listagem com o link da página de composição."""
    header_cells, rows = read_listing_table(soup)
    links = extract_detail_links(soup, page_url)
    if not rows:
        return [
            {"codigo": link["codigo"], "nome": "", "nome_cientifico": "", "grupo": "", "marca": "",
             "url": link["url"]}
            for link in links
        ]

    labels = [h or f"coluna_{i + 1}" for i, h in enumerate(header_cells)] or \
        [f"coluna_{i + 1}" for i in range(len(rows[0]))]

    foods: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, cells in enumerate(rows):
        if len(cells) < 2:
            continue
        data = dict(zip(labels, cells))
        codigo = clean_text(data.get("Código", ""))
        url = ""
        for link in links:
            if link["codigo"] and link["codigo"] == codigo:
                url = link["url"]
                break
        chave = codigo or url or f"linha_{index}"
        if chave in seen:
            continue
        seen.add(chave)
        foods.append(
            {
                "codigo": codigo,
                "nome": clean_text(data.get("Nome", "")),
                "nome_cientifico": clean_text(data.get("Nome Científico", "")),
                "grupo": clean_text(data.get("Grupo", "")),
                "marca": clean_text(data.get("Marca", "")),
                "url": url,
            }
        )

    # Fallback: se o casamento por código falhar, usa a ordem das linhas.
    if any(not food["url"] for food in foods):
        ordenados = [link["url"] for link in links]
        for index, food in enumerate(foods):
            if not food["url"] and index < len(ordenados):
                food["url"] = ordenados[index]
    return foods


def find_next_pages(soup: BeautifulSoup, page_url: str) -> list[str]:
    """
    Procura links de paginação da listagem (Próxima/numerada), se existirem.

    Mantida por compatibilidade: o caminho usado pela coleta é pagination_info(),
    que entende a paginação em dois níveis do site.
    """
    pages: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        if DETAIL_PAGE in href:
            continue
        text = clean_text(anchor.get_text(" ", strip=True)).lower()
        classes = " ".join(anchor.get("class") or []).lower()
        if "next" in classes or "paginate" in classes or text in {"próxima", "proxima", "next", "»"}:
            url = urljoin(page_url, href)
            if url != page_url and url not in pages:
                pages.append(url)
    return pages


# "Exibindo página 37 de 59" (o site serve o texto com a entidade &aacute;)
_PAGINA_INFO_RE = re.compile(r"Exibindo\s*p(?:&aacute;|á|a|&#225;)gina\s*(\d+)\s*de\s*(\d+)", re.I)
_PAGINA_LINK_RE = re.compile(r"pagina=(\d+)")


def parse_pagination_info(html: str) -> dict[str, Any]:
    """
    Lê a paginação da listagem da TBCA.

    O site pagina em dois níveis: '?pagina=N&atuald=B', em que B é o bloco de
    páginas (a página 10 leva a 'pagina=11&atuald=2', e assim por diante). Por
    isso não basta seguir os links visíveis: é preciso saber o total de páginas
    ('Exibindo página 37 de 59') e como o bloco avança.

    Retorna {'atual', 'total', 'bloco', 'ultima_pagina_do_bloco'}.
    """
    info = _PAGINA_INFO_RE.search(html or "")
    atual = int(info.group(1)) if info else 1
    total = int(info.group(2)) if info else 1

    soup = BeautifulSoup(html or "", "html.parser")
    corpo = soup.find(id="block_2") or soup
    paginas_linkadas: set[int] = set()
    blocos: list[int] = []
    for anchor in corpo.find_all("a", href=True):
        href = anchor["href"]
        if "composicao_alimentos.php" not in href:
            continue
        numero = _PAGINA_LINK_RE.search(href)
        if not numero:
            continue
        paginas_linkadas.add(int(numero.group(1)))
        bloco = re.search(r"atuald=(\d+)", href)
        if bloco:
            blocos.append(int(bloco.group(1)))

    bloco_atual = max(set(blocos), key=blocos.count) if blocos else 1
    # Tamanho do bloco: quantas páginas o mesmo valor de 'atuald' agrupa
    # (hoje 10, com '?pagina=1..10&atuald=1').
    tamanho_bloco = len(paginas_linkadas) or 10
    ultima_do_bloco = min(((bloco_atual - 1) * tamanho_bloco + tamanho_bloco), total)
    if total > 1 and ultima_do_bloco < atual:
        ultima_do_bloco = total

    return {
        "atual": atual,
        "total": total,
        "bloco": bloco_atual,
        "tamanho_bloco": tamanho_bloco,
        "ultima_pagina_do_bloco": ultima_do_bloco,
    }


def listing_page_url(listing_url: str, pagina: int, bloco: int) -> str:
    """Monta a URL de uma página da listagem, preservando o bloco correto."""
    separador = "&" if "?" in listing_url else "?"
    return f"{listing_url}{separador}pagina={pagina}&atuald={bloco}"


# --- PARSER DA PÁGINA DE COMPOSIÇÃO ---

def find_composition_table(soup: BeautifulSoup) -> Tag | None:
    """Localiza a tabela de composição (a que traz Componente / Unidade / 100 g)."""
    for candidate in soup.find_all("table"):
        texto = clean_text(candidate.get_text(" ", strip=True))
        if "Componente" in texto and "Unidade" in texto and re.search(r"100\s*g", texto, re.I):
            return candidate
    return soup.find("table", id=re.compile(r"tabela", re.I)) or soup.find("table")


def split_blocks_by_br(tag: Tag) -> list[str]:
    """Divide um elemento em blocos de texto separados por <br>."""
    blocks: list[str] = []
    current: list[str] = []

    def flush() -> None:
        text = clean_text(" ".join(current))
        if text:
            blocks.append(text)
        current.clear()

    for child in tag.children:
        if isinstance(child, Tag) and child.name == "br":
            flush()
        elif isinstance(child, NavigableString):
            current.append(str(child))
        elif isinstance(child, Tag):
            current.append(child.get_text(" ", strip=True))
    flush()
    return blocks


def _labels_regex() -> re.Pattern[str]:
    """Regex que reconhece os rótulos do bloco de identificação ('Código:', 'Grupo:', ...)."""
    rotulos = "|".join(re.escape(rotulo) for rotulo in INFO_KEY_LABELS)
    return re.compile(rf"(?<!\w)({rotulos}):", re.I)


def split_info_fields(tag: Tag) -> list[tuple[str, str]]:
    """
    Devolve [(chave, valor)] do bloco de identificação, na ordem do documento.

    O HTML do site é irregular: às vezes cada rótulo vem separado por <br>, às
    vezes o bloco inteiro chega como um único nó de texto ("Código: BRC0001C
    Grupo: C - Frutas e derivados Tipo de Alimento: ..."). Por isso os dois casos
    são tratados: primeiro quebra por <br>, depois procura os rótulos dentro de
    cada bloco. Linhas sem rótulo (as traduções "<< ... >>") são anexadas ao
    campo anterior.
    """
    regex = _labels_regex()
    campos: list[tuple[str, str]] = []
    for bloco in split_blocks_by_br(tag):
        marcações = list(regex.finditer(bloco))
        if not marcações:
            if campos:
                chave, valor = campos[-1]
                campos[-1] = (chave, clean_text(f"{valor} {bloco}"))
            continue
        for posição, marcação in enumerate(marcações):
            chave = INFO_KEY_LABELS.get(clean_text(marcação.group(1)).title())
            if chave is None:  # tolera diferenças de caixa/acentuação no rótulo
                chave = next((v for rotulo, v in INFO_KEY_LABELS.items()
                              if rotulo.lower() == marcação.group(1).lower()), None)
            if chave is None:
                continue
            fim = marcações[posição + 1].start() if posição + 1 < len(marcações) else len(bloco)
            valor = clean_text(bloco[marcação.end():fim])
            campos.append((chave, valor))
    return campos


def parse_food_info(soup: BeautifulSoup) -> dict[str, str]:
    """
    Lê o bloco de identificação do alimento (<h5> da página de composição).

    Chaves do retorno: codigo, grupo, tipo_alimento, nome_cientifico, descricao
    (1ª linha), descricao_completa e traducoes (trechos em inglês/espanhol,
    publicados entre << >> logo abaixo da descrição).
    """
    info: dict[str, str] = {key: "" for key in INFO_KEYS}

    blocos = [tag for tag in soup.find_all(["h5", "h4", "h3", "div", "p"])
              if "Código:" in tag.get_text(" ", strip=True)]
    if not blocos:
        return info

    # Prefere o <h5> (cabeçalho real da página); se não existir, o último bloco
    # encontrado, que é o mais específico (o <main> também contém "Código:").
    h5 = next((tag for tag in blocos if tag.name in {"h5", "h4", "h3"}), None)
    header = h5 or blocos[-1]

    for chave, valor in split_info_fields(header):
        if not valor:
            continue
        info[chave] = clean_text(f"{info[chave]} {valor}")

    completa = info["descricao"]
    info["descricao_completa"] = completa
    info["traducoes"] = " | ".join(
        clean_text(item) for item in re.findall(r"<<\s*(.+?)\s*>>", completa) if clean_text(item)
    )
    info["descricao"] = clean_text(completa.split("<<")[0])
    return info


def parse_composition_table(
    table: Tag, codigo: str, url: str, settings: Settings
) -> tuple[list[str], list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Converte a tabela de composição em estruturas utilizáveis.

    Retorna (colunas_de_medida, linhas, medidas):
      linhas  - [{'componente', 'unidade', 'valor_100g', 'valores_medidas', ...}]
      medidas - [{'indice', 'nome', 'unidade', 'quantidade'}] na ordem do HTML
    """
    thead = table.find("thead")
    headers = [clean_text(th.get_text(" ", strip=True))
               for th in (thead.find_all("th") if thead else table.find_all("th"))]
    if not headers:
        first_row = table.find("tr")
        headers = [clean_text(cell.get_text(" ", strip=True))
                   for cell in (first_row.find_all(["th", "td"]) if first_row else [])]
    if not headers:
        settings.report(codigo, url, "tabela de composição sem cabeçalho legível")
        return [], [], []

    idx_componente = next((i for i, h in enumerate(headers) if re.search(r"componente", h, re.I)), 0)
    idx_unidade = next((i for i, h in enumerate(headers) if re.search(r"unidade", h, re.I)), idx_componente + 1)
    idx_100g = next((i for i, h in enumerate(headers) if re.search(r"100\s*g", h, re.I)), idx_unidade + 1)

    medidas: list[dict[str, Any]] = []
    for i, header in enumerate(headers):
        if i in (idx_componente, idx_unidade, idx_100g):
            continue
        nome, unidade, quantidade = parse_measure_header(header)
        medidas.append({"indice": i, "nome": nome, "unidade": unidade, "quantidade": quantidade})

    body = table.find("tbody") or table
    linhas: list[dict[str, Any]] = []
    for tr in body.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if len(cells) <= max(idx_componente, idx_unidade, idx_100g):
            continue
        textos = [clean_text(cell.get_text(" ", strip=True)) for cell in cells]
        componente = normalize_component(textos[idx_componente])
        if not componente:
            continue
        unidade = normalize_unit(textos[idx_unidade])

        valor_100g, status_100g = parse_value(textos[idx_100g])
        if status_100g == "invalido":
            settings.report(codigo, url,
                            f"valor por 100 g não interpretado em '{componente}': {textos[idx_100g]!r}")

        valores_medidas: dict[str, float | None] = {}
        status_medidas: dict[str, str] = {}
        for medida in medidas:
            indice = medida["indice"]
            if indice >= len(textos):
                valor, status = None, "ausente"
            else:
                valor, status = parse_value(textos[indice])
                if status == "invalido":
                    settings.report(
                        codigo, url,
                        f"valor de medida não interpretado em '{componente}' "
                        f"({medida['nome']}): {textos[indice]!r}",
                    )
            valores_medidas[str(indice)] = valor
            status_medidas[str(indice)] = status

        linhas.append(
            {
                "componente": componente,
                "unidade": unidade,
                "valor_100g": valor_100g,
                "status_100g": status_100g,
                "texto_100g": textos[idx_100g],
                "valores_medidas": valores_medidas,
                "status_medidas": status_medidas,
            }
        )

    return [m["nome"] for m in medidas], linhas, medidas


def parse_detail_html(html: str) -> dict[str, Any] | None:
    """Interpreta uma página de composição já em memória (sem registrar problemas)."""
    if not html or not html.strip():
        return None
    soup = BeautifulSoup(html, "html.parser")
    table = find_composition_table(soup)
    if table is None:
        return None
    info = parse_food_info(soup)
    _, linhas, medidas = parse_composition_table(table, info.get("codigo", ""), "", Settings(quiet=True))
    return {"info": info, "linhas": linhas, "medidas": medidas}


def parse_detail_page(html: str, url: str, codigo: str, settings: Settings) -> dict[str, Any] | None:
    """Interpreta a página de composição de um alimento."""
    soup = BeautifulSoup(html, "html.parser")
    table = find_composition_table(soup)
    if table is None:
        settings.report(codigo, url, "tabela de composição não encontrada")
        return None

    info = parse_food_info(soup)
    if not info["codigo"]:
        settings.report(codigo, url, "código do alimento ausente no cabeçalho da página")
        info["codigo"] = codigo

    _, linhas, medidas = parse_composition_table(table, info["codigo"], url, settings)
    if not linhas:
        settings.report(codigo, url, "tabela de composição sem linhas de nutrientes")
        return None

    return {"info": info, "linhas": linhas, "medidas": medidas, "url": url}


# --- COLETA ---

def collect_foods(session: requests.Session, settings: Settings) -> list[dict[str, Any]]:
    """
    Baixa todas as páginas da listagem e devolve os alimentos com a URL da
    página de composição de cada um.

    A listagem é paginada em blocos de 10 páginas ('?pagina=N&atuald=B'), com 100
    alimentos por página. Em vez de seguir os links visíveis (que só cobrem o
    bloco atual), o total de páginas é lido do próprio HTML ("Exibindo página 1
    de 59") e as páginas são percorridas até o fim.
    """
    print(f"[1/3] Lendo a listagem: {settings.listing_url}")
    html = fetch_html(session, settings.listing_url, settings)
    if html is None:
        raise SystemExit("ERRO: não foi possível acessar a listagem da TBCA.")

    soup = BeautifulSoup(html, "html.parser")
    foods = discover_foods(soup, settings.listing_url, settings)
    if not foods:
        raise SystemExit("ERRO: nenhum alimento encontrado na listagem (o layout do site pode ter mudado).")

    info = parse_pagination_info(html)
    total_paginas = max(info["total"], 1)
    print(f"      página 1/{total_paginas}: {len(foods)} alimentos.")

    vistos = {food["codigo"] or food["url"] for food in foods}
    pagina = 1
    while pagina < total_paginas:
        pagina += 1
        bloco = (pagina - 1) // max(info["tamanho_bloco"], 1) + 1
        page_url = listing_page_url(settings.listing_url, pagina, bloco)
        time.sleep(settings.listing_delay)

        page_html = fetch_html(session, page_url, settings)
        if page_html is None:
            continue

        page_info = parse_pagination_info(page_html)
        if page_info["atual"] != pagina:
            # O bloco não avançou como esperado: recalcula usando o que a página
            # devolveu, em vez de insistir na mesma URL.
            settings.report("", page_url,
                            f"paginação inesperada: pedi a página {pagina}, o site respondeu "
                            f"{page_info['atual']} de {page_info['total']}")
            if page_info["atual"] < pagina:
                break

        soup_pagina = BeautifulSoup(page_html, "html.parser")
        encontrados = discover_foods(soup_pagina, page_url, settings)
        if not encontrados:
            encontrados = [
                {"codigo": link["codigo"], "nome": "", "nome_cientifico": "", "grupo": "",
                 "marca": "", "url": link["url"]}
                for link in extract_detail_links(soup_pagina, page_url)
            ]
        novos = []
        for food in encontrados:
            chave = food["codigo"] or food["url"]
            if chave in vistos:
                continue
            vistos.add(chave)
            novos.append(food)

        if novos:
            foods.extend(novos)
        if pagina % 10 == 0 or pagina == total_paginas:
            print(f"      página {pagina}/{total_paginas}: {len(foods)} alimentos acumulados.")
        if not encontrados:
            print(f"      página {pagina} sem alimentos: encerrando a paginação.")
            break

    sem_link = sum(1 for food in foods if not food["url"])
    print(f"      {len(foods)} alimentos encontrados ({len(foods) - sem_link} com link de composição).")
    return foods


def collect_details(
    session: requests.Session, foods: Sequence[dict[str, Any]], settings: Settings
) -> dict[str, dict[str, Any]]:
    """Baixa e interpreta a página de composição de cada alimento."""
    total = len(foods)
    print(f"[2/3] Baixando composição de {total} alimentos "
          f"(workers={settings.workers}, delay={settings.delay}s, cache={settings.cache_dir})")

    detalhes: dict[str, dict[str, Any]] = {}
    reutilizados = 0
    erros = 0
    concluidos = 0

    def work(food: dict[str, Any]) -> tuple[str, dict[str, Any] | None, bool]:
        codigo = food["codigo"]
        url = food["url"]
        if not url:
            return codigo, None, False

        # 1) JSON já gerado em execuções anteriores: não precisa baixar de novo.
        json_existente = ler_json(settings, codigo)
        if json_existente is not None and not settings.force:
            return codigo, detalhe_de_json(json_existente), True

        # 2) HTML em cache local.
        destino = cache_file(settings, codigo)
        if destino is not None and destino.exists() and not settings.force:
            html: str | None = destino.read_text(encoding="utf-8")
        else:
            # Cada worker usa a própria sessão: requests.Session não é thread-safe.
            with build_session() as local_session:
                html = fetch_html(local_session, url, settings)
            if html is not None and destino is not None:
                destino.parent.mkdir(parents=True, exist_ok=True)
                destino.write_text(html, encoding="utf-8")
            time.sleep(max(settings.delay, MIN_DELAY))

        if html is None:
            return codigo, None, False
        return codigo, parse_detail_page(html, url, codigo, settings), False

    with ThreadPoolExecutor(max_workers=max(1, settings.workers)) as pool:
        futures = {pool.submit(work, food): food for food in foods}
        for future in as_completed(futures):
            food = futures[future]
            try:
                codigo, detalhe, reutilizado = future.result()
            except Exception as exc:  # pragma: no cover - proteção de robustez
                settings.report(food.get("codigo", ""), food.get("url", ""), f"erro inesperado: {exc}")
                erros += 1
                continue
            if detalhe is None:
                erros += 1
                if not food["url"]:
                    settings.report(food.get("codigo", ""), "", "linha da listagem sem link de composição")
            else:
                detalhes[codigo] = detalhe
                reutilizados += int(reutilizado)
                # Grava o JSON assim que cada alimento fica pronto: uma execução
                # interrompida não perde o que já foi coletado.
                escrever_json_alimento(settings, food, detalhe)
            concluidos += 1
            if concluidos % 100 == 0 or concluidos == total:
                print(f"      {concluidos}/{total} processados "
                      f"({len(detalhes)} ok, {reutilizados} do JSON existente, {erros} com problema)")

    return detalhes


# --- EXPORTAÇÃO EM JSON ---

def build_json_record(food: dict[str, Any], detalhe: dict[str, Any]) -> dict[str, Any]:
    """
    Monta o registro JSON de um alimento.

    Formato pensado para ser consumido direto por uma aplicação (e para servir de
    cache entre execuções):

        {
          "codigo": "BRC0001C",
          "nome": "Abacate, polpa, in natura, Brasil",
          "por_100g": {"Energia (kcal)": 76.0, "Umidade (g)": 86.3, ...},
          "componentes": [{"componente", "unidade", "valor_100g", "status",
                           "medidas": [{"indice", "valor", "status"}]}, ...],
          "medidas": [{"indice", "nome", "unidade", "quantidade"}],
          "fontes": "https://www.tbca.net.br/...",
          "fonte_html": "cache_tbca/BRC0001C.html"
        }

    Valores ausentes (NA) entram como null; traço ('tr') entra como 0.0 com
    status 'traço', para não se confundir com dado não publicado.
    """
    info = detalhe.get("info", {})
    componentes: list[dict[str, Any]] = []
    por_100g: dict[str, float | None] = {}

    for linha in detalhe["linhas"]:
        chave = f"{linha['componente']} ({linha['unidade']})" if linha["unidade"] else linha["componente"]
        if chave in por_100g:
            chave = f"{chave} [{len(componentes)}]"
        por_100g[chave] = linha["valor_100g"]

        componentes.append(
            {
                "componente": linha["componente"],
                "unidade": linha["unidade"],
                "valor_100g": linha["valor_100g"],
                "status": linha["status_100g"],
                "texto_original": linha["texto_100g"],
                "medidas": [
                    {
                        "indice": int(indice),
                        "valor": linha["valores_medidas"].get(indice),
                        "status": linha["status_medidas"].get(indice, "ausente"),
                    }
                    for indice in sorted(linha["valores_medidas"], key=int)
                ],
            }
        )

    return {
        "codigo": info.get("codigo") or food.get("codigo", ""),
        "nome": food.get("nome") or info.get("descricao", ""),
        "nome_cientifico": food.get("nome_cientifico") or info.get("nome_cientifico", ""),
        "grupo": food.get("grupo") or info.get("grupo", ""),
        "grupo_completo": info.get("grupo", ""),
        "tipo_alimento": info.get("tipo_alimento", ""),
        "marca": food.get("marca", ""),
        "descricao_tbca": info.get("descricao_completa", ""),
        "descricao_traducoes": info.get("traducoes", ""),
        "url": food.get("url", ""),
        "cache_html": "",
        "por_100g": por_100g,
        "componentes": componentes,
        "medidas": [
            {"indice": m["indice"], "nome": m["nome"], "unidade": m["unidade"], "quantidade": m["quantidade"]}
            for m in detalhe["medidas"]
        ],
        "coletado_em": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "versao_scraper": VERSAO_SCRAPER,
    }


def json_alimento_path(settings: Settings, codigo: str) -> Path | None:
    if settings.json_dir is None:
        return None
    return Path(settings.json_dir) / f"{codigo or 'sem-codigo'}.json"


def escrever_json_alimento(settings: Settings, food: dict[str, Any], detalhe: dict[str, Any]) -> None:
    """Grava (ou regrava) o JSON individual de um alimento."""
    destino = json_alimento_path(settings, detalhe.get("info", {}).get("codigo") or food.get("codigo", ""))
    if destino is None:
        return
    destino.parent.mkdir(parents=True, exist_ok=True)
    registro = build_json_record(food, detalhe)
    registro["cache_html"] = str(cache_file(settings, registro["codigo"])) if settings.cache_dir else None
    destino.write_text(json.dumps(registro, ensure_ascii=False, indent=2), encoding="utf-8")


def escrever_json_completo(frames: dict[str, pd.DataFrame], settings: Settings) -> None:
    """
    Grava o arquivo JSON único com todos os alimentos ("db.json").

    Os componentes ficam listados uma única vez em "componentes"; cada alimento
    traz o mapa "por_100g" com o nome e a unidade do componente, para o arquivo
    poder ser lido direto por uma aplicação.
    """
    if settings.json_dir is None:
        return

    alimentos = frames["Alimentos"].to_dict("records")
    long = frames["Nutrientes"].to_dict("records")
    medidas = frames["Medidas"].to_dict("records")

    componentes = sorted({str(linha["Componente"]) for linha in long if linha.get("Componente")})
    nomes_medidas: list[dict[str, Any]] = []
    vistos: set[tuple[Any, Any, Any]] = set()
    for linha in medidas:
        chave = (linha.get("Medida"), linha.get("Unidade da medida"), linha.get("Quantidade da medida"))
        if chave in vistos:
            continue
        vistos.add(chave)
        nomes_medidas.append({"nome": chave[0], "unidade": chave[1], "quantidade": chave[2]})

    por_codigo: dict[str, dict[str, Any]] = {}
    for linha in long:
        codigo = str(linha["Código"])
        unidade = linha.get("Unidade") or ""
        nome = linha["Componente"]
        chave = f"{nome} ({unidade})" if unidade else str(nome)
        destino = por_codigo.setdefault(codigo, {})
        if chave in destino:
            chave = f"{chave} [duplicado {len(destino)}]"
        valor = linha.get("Valor por 100g")
        destino[chave] = None if valor is None or pd.isna(valor) else float(valor)

    medidas_por_codigo: dict[str, list[dict[str, Any]]] = {}
    for linha in medidas:
        codigo = str(linha["Código"])
        valor = linha.get("Valor")
        medidas_por_codigo.setdefault(codigo, []).append(
            {
                "medida": linha.get("Medida"),
                "unidade": linha.get("Unidade da medida"),
                "quantidade": linha.get("Quantidade da medida"),
                "componente": linha.get("Componente"),
                "valor": None if valor is None or pd.isna(valor) else float(valor),
            }
        )

    registros = [
        {
            "codigo": str(linha.get("Código", "")),
            "nome": linha.get("Nome", ""),
            "nome_cientifico": linha.get("Nome Científico", ""),
            "grupo": linha.get("Grupo", ""),
            "marca": linha.get("Marca", ""),
            "tipo_alimento": linha.get("Tipo de Alimento", ""),
            "descricao_tbca": linha.get("Descrição (TBCA)", ""),
            "descricao_traducoes": linha.get("Descrição EN/ES", ""),
            "url": linha.get("URL", ""),
            "composicao_coletada": bool(linha.get("Composição coletada")),
            "por_100g": por_codigo.get(str(linha.get("Código", "")), {k: None for k in componentes}),
            "medidas": medidas_por_codigo.get(str(linha.get("Código", "")), []),
        }
        for linha in alimentos
    ]

    destino = Path(settings.json_dir) / "db.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(
        json.dumps(
            {
                "gerado_em": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "fonte": settings.listing_url,
                "versao_scraper": VERSAO_SCRAPER,
                "base": "valores por 100 g da parte comestível",
                "observacao": ("null = dado não publicado (NA); 0.0 pode ser valor zero ou traço. "
                               "O JSON individual de cada alimento traz o campo 'status' para distinguir os casos."),
                "componentes": componentes,
                "medidas_caseiras": nomes_medidas,
                "alimentos": registros,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"      JSON completo: {destino} ({len(registros)} alimentos)")


def ler_json(settings: Settings, codigo: str) -> dict[str, Any] | None:
    """Lê o JSON individual de um alimento, se existir e for legível."""
    destino = json_alimento_path(settings, codigo)
    if destino is None or not destino.exists():
        return None
    try:
        return json.loads(destino.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def detalhe_de_json(registro: dict[str, Any]) -> dict[str, Any]:
    """Reconstrói a estrutura interna (info/linhas/medidas) a partir do JSON."""
    medidas = registro.get("medidas", [])
    linhas: list[dict[str, Any]] = []
    for componente in registro.get("componentes", []):
        valores = {str(m["indice"]): m.get("valor") for m in componente.get("medidas", [])}
        status = {str(m["indice"]): m.get("status", "ausente") for m in componente.get("medidas", [])}
        linhas.append(
            {
                "componente": componente.get("componente", ""),
                "unidade": componente.get("unidade", ""),
                "valor_100g": componente.get("valor_100g"),
                "status_100g": componente.get("status", "ausente"),
                "texto_100g": componente.get("texto_original", ""),
                "valores_medidas": valores,
                "status_medidas": status,
            }
        )
    return {
        "info": {
            "codigo": registro.get("codigo", ""),
            "grupo": registro.get("grupo_completo") or registro.get("grupo", ""),
            "tipo_alimento": registro.get("tipo_alimento", ""),
            "nome_cientifico": registro.get("nome_cientifico", ""),
            "descricao": registro.get("descricao_tbca", ""),
            "descricao_completa": registro.get("descricao_tbca", ""),
            "traducoes": registro.get("descricao_traducoes", ""),
        },
        "linhas": linhas,
        "medidas": medidas,
        "url": registro.get("url", ""),
    }


# --- MONTAGEM DAS TABELAS ---

def build_frames(
    foods: Sequence[dict[str, Any]], detalhes: dict[str, dict[str, Any]]
) -> dict[str, pd.DataFrame]:
    """Monta os DataFrames finais a partir da listagem e das páginas de composição."""
    alimentos: list[dict[str, Any]] = []
    linhas_long: list[dict[str, Any]] = []
    linhas_medida: list[dict[str, Any]] = []

    for food in foods:
        codigo = food["codigo"]
        detalhe = detalhes.get(codigo)
        info = detalhe["info"] if detalhe else {}
        nome = food["nome"] or info.get("descricao", "")

        alimentos.append(
            {
                "Código": codigo,
                "Nome": nome,
                "Nome Científico": food["nome_cientifico"] or info.get("nome_cientifico", ""),
                "Grupo": food["grupo"] or info.get("grupo", ""),
                "Marca": food["marca"],
                "Tipo de Alimento": info.get("tipo_alimento", ""),
                "Descrição (TBCA)": info.get("descricao_completa", ""),
                "Descrição EN/ES": info.get("traducoes", ""),
                "URL": food["url"],
                "Composição coletada": bool(detalhe),
            }
        )
        if not detalhe:
            continue

        medidas_por_indice = {str(m["indice"]): m for m in detalhe["medidas"]}
        for linha in detalhe["linhas"]:
            linhas_long.append(
                {
                    "Código": codigo,
                    "Nome": nome,
                    "Componente": linha["componente"],
                    "Unidade": linha["unidade"],
                    "Valor por 100g": linha["valor_100g"],
                    "Valor por 100g (texto original)": linha["texto_100g"],
                    "Status": linha["status_100g"],
                }
            )
            for indice, medida in medidas_por_indice.items():
                valor = linha["valores_medidas"].get(indice)
                status = linha["status_medidas"].get(indice, "ausente")
                if valor is None and status != "traço":
                    continue  # não publica linha vazia para medida não informada
                linhas_medida.append(
                    {
                        "Código": codigo,
                        "Nome": nome,
                        "Medida": medida["nome"],
                        "Unidade da medida": medida["unidade"],
                        "Quantidade da medida": medida["quantidade"],
                        "Componente": linha["componente"],
                        "Unidade": linha["unidade"],
                        "Valor": valor,
                        "Status": status,
                    }
                )

    df_alimentos = pd.DataFrame(alimentos)
    df_long = pd.DataFrame(linhas_long)
    df_medidas = pd.DataFrame(linhas_medida)
    return {
        "Alimentos": df_alimentos,
        "Nutrientes_100g": pivot_100g(df_long, df_alimentos),
        "Nutrientes": df_long,
        "Medidas": df_medidas,
    }


def pivot_100g(df_long: pd.DataFrame, df_alimentos: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por alimento, um componente por coluna (valores por 100 g)."""
    identificacao_cols = ["Código", "Nome", "Grupo", "Nome Científico", "Tipo de Alimento"]
    if df_long.empty:
        return df_alimentos[identificacao_cols].copy()

    valores = df_long.pivot_table(
        index="Código",
        columns=["Componente", "Unidade"],
        values="Valor por 100g",
        aggfunc="first",
    )
    valores.columns = [
        f"{componente} ({unidade})" if unidade else str(componente)
        for componente, unidade in valores.columns
    ]
    valores = valores.reset_index()
    return df_alimentos[identificacao_cols].merge(valores, on="Código", how="left")


def summarise(frames: dict[str, pd.DataFrame], settings: Settings) -> pd.DataFrame:
    """Indicadores da execução, gravados na primeira aba da planilha."""
    alimentos = frames["Alimentos"]
    coletados = int(alimentos["Composição coletada"].sum()) if "Composição coletada" in alimentos else 0
    componentes = sorted(frames["Nutrientes"]["Componente"].dropna().unique().tolist()) \
        if not frames["Nutrientes"].empty else []
    medidas = sorted(frames["Medidas"]["Medida"].dropna().unique().tolist()) \
        if not frames["Medidas"].empty else []
    return pd.DataFrame(
        [
            {"Indicador": "Executado em", "Valor": time.strftime("%Y-%m-%d %H:%M")},
            {"Indicador": "URL da listagem", "Valor": settings.listing_url},
            {"Indicador": "Alimentos listados", "Valor": len(alimentos)},
            {"Indicador": "Alimentos com composição coletada", "Valor": coletados},
            {"Indicador": "Alimentos sem composição", "Valor": len(alimentos) - coletados},
            {"Indicador": "Componentes distintos", "Valor": len(componentes)},
            {"Indicador": "Componentes", "Valor": "; ".join(componentes)},
            {"Indicador": "Medidas caseiras distintas", "Valor": len(medidas)},
            {"Indicador": "Medidas caseiras", "Valor": "; ".join(medidas)},
            {"Indicador": "Problemas registrados", "Valor": len(settings.issues)},
            {"Indicador": "Cache local (HTML)", "Valor": str(settings.cache_dir) if settings.cache_dir else "desativado"},
            {"Indicador": "Pasta JSON", "Valor": str(settings.json_dir) if settings.json_dir else "desativado"},
            {"Indicador": "Formatos gerados", "Valor": settings.formatos},
            {"Indicador": "Observação de valores", "Valor":
                "Status 'traço' = 0 relatado pela TBCA (tr); 'ausente' = dado não publicado (NA); "
                "'valor' = número informado."},
        ]
    )


def export(frames: dict[str, pd.DataFrame], settings: Settings) -> None:
    """Grava a planilha de saída."""
    settings.out.parent.mkdir(parents=True, exist_ok=True)
    print(f"[3/3] Gravando '{settings.out}'")

    problemas = pd.DataFrame(settings.issues) if settings.issues else \
        pd.DataFrame(columns=["Código", "URL", "Problema"])
    resumo = summarise(frames, settings)

    with pd.ExcelWriter(settings.out, engine="openpyxl") as writer:
        resumo.to_excel(writer, sheet_name="Resumo", index=False)
        frames["Alimentos"].to_excel(writer, sheet_name="Alimentos", index=False)
        frames["Nutrientes_100g"].to_excel(writer, sheet_name="Nutrientes_100g", index=False)
        frames["Nutrientes"].to_excel(writer, sheet_name="Nutrientes", index=False)
        frames["Medidas"].to_excel(writer, sheet_name="Medidas", index=False)
        problemas.to_excel(writer, sheet_name="Problemas", index=False)

    print(f"[OK] {len(frames['Alimentos'])} alimentos | "
          f"{len(frames['Nutrientes'])} linhas de nutrientes | "
          f"{len(frames['Medidas'])} linhas de medidas caseiras | "
          f"{len(settings.issues)} problemas")


# --- FLUXOS DE EXECUÇÃO ---

def escrever_json_por_alimento(foods: Sequence[dict[str, Any]],
                               detalhes: dict[str, dict[str, Any]],
                               settings: Settings) -> None:
    """Grava o JSON individual de cada alimento coletado."""
    if settings.json_dir is None:
        return
    gravados = 0
    destino = Path(settings.json_dir)
    destino.mkdir(parents=True, exist_ok=True)
    for food in foods:
        detalhe = detalhes.get(food["codigo"])
        if detalhe is None:
            continue
        escrever_json_alimento(settings, food, detalhe)
        gravados += 1
    if gravados:
        print(f"      JSON individual: {gravados} arquivos em {destino}")


def persistir(frames: dict[str, pd.DataFrame], settings: Settings,
              foods: Sequence[dict[str, Any]] | None = None,
              detalhes: dict[str, dict[str, Any]] | None = None) -> None:
    """
    Grava as saídas pedidas.

    --format ambos (padrão) : planilha + JSON (individual e db.json)
    --format excel          : apenas a planilha
    --format json           : JSON individual de cada alimento + db.json
    """
    if settings.formatos in ("ambos", "excel"):
        export(frames, settings)
    if settings.formatos in ("ambos", "json"):
        if foods is not None and detalhes is not None:
            escrever_json_por_alimento(foods, detalhes, settings)
        print(f"[3/3] Gravando JSON em '{settings.json_dir}'")
        escrever_json_completo(frames, settings)


def settings_from_args(args: argparse.Namespace) -> Settings:
    return Settings(
        listing_url=args.url,
        out=Path(args.out),
        delay=max(float(args.delay), 0.0),
        workers=max(int(args.workers), 1),
        listing_delay=max(float(args.listing_delay), 0.0),
        retries=max(int(args.retries), 1),
        timeout=float(args.timeout),
        cache_dir=None if args.no_cache else Path(args.cache_dir),
        json_dir=None if args.no_json else Path(args.json_dir),
        formatos=args.format,
        limit=int(args.limit or 0),
        force=bool(args.force),
    )


def run_scraper(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)

    if args.from_html_dir:
        return run_from_directory(Path(args.from_html_dir), settings)

    with build_session() as session:
        foods = collect_foods(session, settings)
        if settings.limit:
            foods = foods[: settings.limit]
            print(f"      limitado a {len(foods)} alimentos (--limit)")
        detalhes = collect_details(session, foods, settings)

    if not detalhes:
        print("ATENÇÃO: nenhuma página de composição foi interpretada com sucesso.")

    persistir(build_frames(foods, detalhes), settings, foods, detalhes)
    return 0


def run_from_directory(directory: Path, settings: Settings) -> int:
    """
    Reprocessa páginas de composição já salvas em disco (modo offline).

    Considera apenas os arquivos cujo nome é o código do alimento (mesmo padrão do
    cache), para não tentar interpretar HTMLs que não sejam páginas de composição.
    """
    arquivos = sorted(
        arquivo for arquivo in directory.glob("*.html")
        if re.fullmatch(r"[A-Za-z]{2,4}\d{3,5}[A-Za-z]?", arquivo.stem)
    )
    if not arquivos:
        raise SystemExit(
            f"ERRO: nenhuma página de composição (arquivo <CÓDIGO>.html) encontrada em {directory}"
        )
    print(f"[1/3] Reprocessando {len(arquivos)} arquivos de {directory}")

    foods: list[dict[str, Any]] = []
    detalhes: dict[str, dict[str, Any]] = {}
    for arquivo in arquivos:
        detalhe = parse_detail_page(arquivo.read_text(encoding="utf-8"), f"file://{arquivo}",
                                    arquivo.stem, settings)
        if detalhe is None:
            continue
        info = detalhe["info"]
        codigo = info.get("codigo") or arquivo.stem
        detalhes[codigo] = detalhe
        foods.append(
            {
                "codigo": codigo,
                "nome": info.get("descricao", ""),
                "nome_cientifico": info.get("nome_cientifico", ""),
                "grupo": info.get("grupo", ""),
                "marca": "",
                "url": f"file://{arquivo}",
            }
        )

    print(f"[2/3] {len(detalhes)} páginas interpretadas")
    persistir(build_frames(foods, detalhes), settings, foods, detalhes)
    return 0


def inspect_single(source: str) -> int:
    """Mostra (sem gravar nada) o que o parser extrai de uma URL ou arquivo local."""
    if re.match(r"^https?://", source, re.I):
        with build_session() as session:
            html = fetch_html(session, source, Settings(cache_dir=None))
        if html is None:
            return 1
    else:
        html = Path(source).read_text(encoding="utf-8")

    detalhe = parse_detail_html(html)
    if detalhe is None:
        print("ERRO: tabela de composição não encontrada no HTML informado.")
        return 1

    print(json.dumps(
        {
            "info": detalhe["info"],
            "medidas": [{k: v for k, v in m.items() if k != "indice"} for m in detalhe["medidas"]],
            "linhas": [
                {
                    "componente": linha["componente"],
                    "unidade": linha["unidade"],
                    "valor_100g": linha["valor_100g"],
                    "status": linha["status_100g"],
                    "medidas": linha["valores_medidas"],
                }
                for linha in detalhe["linhas"]
            ],
        },
        ensure_ascii=False,
        indent=2,
    ))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Baixa a composição nutricional dos alimentos da TBCA "
                    "(por 100 g e por medidas caseiras).",
    )
    parser.add_argument("--url", default=LISTING_URL, help="URL da listagem de alimentos")
    parser.add_argument("--out", default=OUTPUT_FILENAME, help="arquivo .xlsx de saída")
    parser.add_argument("--delay", type=float, default=1.0,
                        help="intervalo entre requisições de cada worker (s)")
    parser.add_argument("--workers", type=int, default=2, help="requisições simultâneas")
    parser.add_argument("--listing-delay", type=float, default=0.3,
                        help="intervalo entre páginas da listagem (s)")
    parser.add_argument("--retries", type=int, default=3, help="tentativas por página")
    parser.add_argument("--timeout", type=float, default=30.0, help="timeout por requisição (s)")
    parser.add_argument("--limit", type=int, default=0, help="processar somente os N primeiros alimentos")
    parser.add_argument("--cache-dir", default=CACHE_DIR, help="diretório de cache do HTML")
    parser.add_argument("--no-cache", action="store_true", help="não usar nem gravar cache local")
    parser.add_argument("--json-dir", default=JSON_DIR,
                        help="pasta dos arquivos JSON (um por alimento + db.json)")
    parser.add_argument("--no-json", action="store_true", help="não gerar JSON")
    parser.add_argument("--format", choices=["ambos", "excel", "json"], default="ambos",
                        help="formatos de saída (padrão: ambos)")
    parser.add_argument("--force", action="store_true",
                        help="ignorar cache de HTML/JSON e baixar novamente")
    parser.add_argument("--from-html-dir", help="reprocessar páginas salvas em disco (offline)")
    parser.add_argument("--inspect", help="mostrar o que o parser extrai de uma URL ou arquivo, sem gravar nada")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    # No console do Windows (cp1252) os acentos dos avisos quebrariam a execução.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")

    args = build_parser().parse_args(argv)
    if args.inspect:
        return inspect_single(args.inspect)
    return run_scraper(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrompido pelo usuário.")
        sys.exit(130)
