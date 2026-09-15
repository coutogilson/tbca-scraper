#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Testes do parser da TBCA (offline).

    python -m pytest tests -q          (ou)
    python tests/test_parsing.py
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import pandas as pd  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402

import scrape_tbca as s  # noqa: E402

SAMPLES = Path(__file__).resolve().parent / "samples"


# --- valores ---

def test_parse_value_virgula_decimal():
    assert s.parse_value("86,3") == (86.3, "valor")


def test_parse_value_inteiro_e_ponto_de_milhar():
    assert s.parse_value("312") == (312.0, "valor")
    assert s.parse_value("1.155,3") == (1155.3, "valor")


def test_parse_value_traco_vira_zero():
    for bruto in ("tr", "TR", "Tr"):
        assert s.parse_value(bruto) == (0.0, "traço")


def test_parse_value_ausente_nao_vira_zero():
    for bruto in ("NA", "na", "-", "", "   "):
        valor, status = s.parse_value(bruto)
        assert valor is None and status == "ausente", bruto


def test_parse_value_asterisco_da_fonte():
    assert s.parse_value("*7,32") == (7.32, "valor")
    assert s.parse_value("6,21 (*)") == (6.21, "valor")


def test_parse_value_zero_explicito():
    assert s.parse_value("0,00") == (0.0, "valor")


# --- cabeçalhos de medidas caseiras ---

def test_medida_com_gramas():
    assert s.parse_measure_header("Colher sopa cheia (45 g)") == ("Colher sopa cheia", "g", 45.0)


def test_medida_com_mililitros():
    assert s.parse_measure_header("Copo americano duplo (200 mL)") == ("Copo americano duplo", "mL", 200.0)


def test_medida_com_parentese_aninhado():
    assert s.parse_measure_header("Pedaço/ Unidade/ Fatia (M) (370 g)") == \
        ("Pedaço/ Unidade/ Fatia (M)", "g", 370.0)


def test_medida_sem_unidade_reconhecida():
    assert s.parse_measure_header("Porção (1 fatia)") == ("Porção (1 fatia)", "", None)


# --- página de composição ---

def carregar_detalhe() -> dict:
    html = (SAMPLES / "BRC0001C.html").read_text(encoding="utf-8")
    detalhe = s.parse_detail_html(html)
    assert detalhe is not None
    return detalhe


def test_cabecalho_do_alimento():
    info = carregar_detalhe()["info"]
    assert info["codigo"] == "BRC0001C"
    assert info["grupo"] == "C - Frutas e derivados"
    assert info["tipo_alimento"] == "A - Alimento in natura"
    assert info["nome_cientifico"] == "Persea americana Mill"
    assert info["descricao"] == "Abacate, polpa, in natura, Brasil"
    assert "Avocado, pulp, raw, Brazil" in info["traducoes"]
    assert "Aguacate, pulpa, fresco, Brasil" in info["traducoes"]


def test_todas_as_linhas_do_componente():
    detalhe = carregar_detalhe()
    componentes = [linha["componente"] for linha in detalhe["linhas"]]
    assert len(componentes) == 41
    assert componentes[:3] == ["Energia", "Energia", "Umidade"]
    assert "Proteína animal" in componentes


def test_medidas_caseiras_detectadas():
    medidas = carregar_detalhe()["medidas"]
    nomes = [(m["nome"], m["unidade"], m["quantidade"]) for m in medidas]
    assert nomes == [
        ("Colher sopa cheia", "g", 45.0),
        ("Copo americano duplo", "mL", 200.0),
        ("Copo americano pequeno", "mL", 130.0),
        ("Pedaço/ Unidade/ Fatia (M)", "g", 370.0),
        ("Prato fundo", "g", 450.0),
        ("Prato raso", "g", 350.0),
    ]


def test_valores_por_100g():
    linhas = {linha["componente"]: linha for linha in carregar_detalhe()["linhas"]}
    assert linhas["Umidade"]["valor_100g"] == 86.3
    assert linhas["Umidade"]["unidade"] == "g"
    assert linhas["Proteína"]["valor_100g"] == 1.15
    assert linhas["Sódio"]["status_100g"] == "traço"
    assert linhas["Sódio"]["valor_100g"] == 0.0


def test_valores_das_medidas_caseiras():
    detalhe = carregar_detalhe()
    indices = {str(m["indice"]): m["nome"] for m in detalhe["medidas"]}
    por_nome = {indices[k]: v for k, v in list(detalhe["linhas"][2]["valores_medidas"].items())}
    assert por_nome["Colher sopa cheia"] == 38.8
    assert por_nome["Prato raso"] == 302.0
    sódio = next(linha for linha in detalhe["linhas"] if linha["componente"] == "Sódio")
    # "NA" no copo duplo não pode virar zero.
    assert sódio["valores_medidas"]["4"] is None
    assert sódio["status_medidas"]["4"] == "ausente"


# --- listagem ---

def test_listagem_casa_codigo_com_link():
    html = (SAMPLES / "listing_composicao.html").read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")
    foods = s.discover_foods(soup, s.LISTING_URL, s.Settings(quiet=True))
    assert [f["codigo"] for f in foods] == ["BRC0001C", "BRC0195C", "BRC0005K"]
    assert foods[0]["nome"] == "Abacate, polpa, in natura, Brasil"
    assert foods[0]["nome_cientifico"] == "Persea americana Mill"
    assert foods[1]["nome_cientifico"] == ""
    assert foods[2]["marca"] == "União"
    assert all(f["url"].startswith("https://www.tbca.net.br/base-dados/int_composicao_alimentos.php?") for f in foods)
    assert foods[0]["url"].endswith("n0REd3kv7e86D%2BViXWYUnQ%3D%3D=QagWPGGLCefQ%2BGqdjKbs2w%3D%3D")


def test_links_preservam_escape_da_query():
    html = (SAMPLES / "listing_composicao.html").read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")
    links = s.extract_detail_links(soup, s.LISTING_URL)
    assert len(links) == 3
    # urljoin não pode corromper os %2B / %3D do parâmetro ofuscado.
    assert all("%2B" in link["url"] or "%3D" in link["url"] for link in links)
    assert not any(" " in link["url"] for link in links)


# --- paginação da listagem ---

def ler_listagem() -> tuple[str, BeautifulSoup]:
    html = (SAMPLES / "listing_composicao.html").read_text(encoding="utf-8")
    return html, BeautifulSoup(html, "html.parser")


def test_paginacao_le_pagina_atual_e_fim_do_bloco():
    html, _ = ler_listagem()
    info = s.parse_pagination_info(html)
    assert info["atual"] == 1
    assert info["total"] == 59  # "Exibindo página 1 de 59" = fim do bloco atual
    assert info["bloco"] == 1
    assert info["tamanho_bloco"] == 10  # páginas 1..10 no bloco atuald=1


def test_paginacao_segue_o_link_proxima():
    html, soup = ler_listagem()
    proxima = s.find_next_page_url(soup, s.LISTING_URL, 1)
    assert proxima is not None
    assert proxima.endswith("?pagina=2&atuald=1")

    # Na última página do bloco (10) o "Próxima" já aponta para o bloco seguinte.
    html10 = html.replace("p&aacute;gina 1 de 59", "p&aacute;gina 10 de 59") \
                 .replace("href='composicao_alimentos.php?pagina=2&atuald=1' class='nav-link'>pr&oacute;xima",
                          "href='composicao_alimentos.php?pagina=11&atuald=2' class='nav-link'>pr&oacute;xima")
    proxima10 = s.find_next_page_url(BeautifulSoup(html10, "html.parser"), s.LISTING_URL, 10)
    assert proxima10 is not None and proxima10.endswith("?pagina=11&atuald=2")


def test_paginacao_para_quando_nao_ha_proxima():
    soup = BeautifulSoup("<div id='block_2'><a href='#' class='nav-link disabled'>59</a></div>", "html.parser")
    assert s.find_next_page_url(soup, s.LISTING_URL, 59) is None

    # Sem link "próxima", usa o menor número de página maior que o atual.
    soup_numeros = BeautifulSoup(
        "<div id='block_2'><a href='composicao_alimentos.php?pagina=1&atuald=1'>1</a>"
        "<a href='composicao_alimentos.php?pagina=3&atuald=1'>3</a></div>", "html.parser")
    assert s.find_next_page_url(soup_numeros, s.LISTING_URL, 2).endswith("?pagina=3&atuald=1")


def test_paginacao_na_ultima_pagina_nao_avanca():
    html, _ = ler_listagem()
    html = html.replace("p&aacute;gina 1 de 59", "p&aacute;gina 59 de 59")
    info = s.parse_pagination_info(html)
    assert (info["atual"], info["total"]) == (59, 59)


def test_listagem_sem_paginacao_nao_quebra():
    info = s.parse_pagination_info("<html><body><table><tr><td>BRC0001C</td></tr></table></body></html>")
    assert info["atual"] == 1 and info["total"] == 1 and info["tamanho_bloco"] == 10
    soup = BeautifulSoup("<html><body><table></table></body></html>", "html.parser")
    assert s.find_next_page_url(soup, s.LISTING_URL, 1) is None


# --- planilha final ---

def test_planilha_gerada_a_partir_do_html_offline(tmp_path):
    out = tmp_path / "saida.xlsx"
    codigo = s.main([
        "--from-html-dir", str(SAMPLES),
        "--out", str(out),
        "--no-cache",
        "--json-dir", str(tmp_path / "json"),
    ])
    assert codigo == 0
    assert out.exists()

    abas = pd.read_excel(out, sheet_name=None)
    assert set(abas) >= {"Resumo", "Alimentos", "Nutrientes_100g", "Nutrientes", "Medidas", "Problemas"}

    alimentos = abas["Alimentos"]
    assert len(alimentos) == 1
    assert alimentos.loc[0, "Código"] == "BRC0001C"
    assert bool(alimentos.loc[0, "Composição coletada"]) is True

    wide = abas["Nutrientes_100g"]
    assert "Umidade (g)" in wide.columns
    assert "Energia (kcal)" in wide.columns
    assert float(wide.loc[0, "Energia (kcal)"]) == 76.0

    long = abas["Nutrientes"]
    assert len(long) == 41
    assert set(long["Status"]) <= {"valor", "traço", "ausente"}

    medidas = abas["Medidas"]
    assert set(medidas["Medida"]) == {
        "Colher sopa cheia", "Copo americano duplo", "Copo americano pequeno",
        "Pedaço/ Unidade/ Fatia (M)", "Prato fundo", "Prato raso",
    }
    umidade = medidas[(medidas["Medida"] == "Colher sopa cheia") & (medidas["Componente"] == "Umidade")]
    assert float(umidade.iloc[0]["Valor"]) == 38.8
    assert float(umidade.iloc[0]["Quantidade da medida"]) == 45.0
    # Medidas com NA não entram na aba.
    assert not ((medidas["Componente"] == "Sódio") & (medidas["Medida"] == "Copo americano duplo")).any()


# --- JSON ---

def test_json_por_alimento_e_db(tmp_path):
    pasta = tmp_path / "formato_json"
    # o runner do __main__ reaproveita a pasta entre testes: começa limpo
    if pasta.exists():
        shutil.rmtree(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    out = pasta / "saida.xlsx"
    pasta_json = pasta / "json"
    assert s.main([
        "--from-html-dir", str(SAMPLES),
        "--out", str(out),
        "--no-cache",
        "--json-dir", str(pasta_json),
        "--format", "json",
    ]) == 0

    individual = json.loads((pasta_json / "BRC0001C.json").read_text(encoding="utf-8"))
    assert individual["codigo"] == "BRC0001C"
    assert individual["nome"] == "Abacate, polpa, in natura, Brasil"
    assert individual["por_100g"]["Umidade (g)"] == 86.3
    assert individual["por_100g"]["Energia (kcal)"] == 76.0
    assert individual["por_100g"]["Sódio (mg)"] == 0.0  # traço vem como 0
    sodio = next(c for c in individual["componentes"] if c["componente"] == "Sódio")
    assert sodio["status"] == "traço"
    assert any(m["valor"] is None and m["status"] == "ausente" for m in sodio["medidas"])
    assert [m["nome"] for m in individual["medidas"]][0] == "Colher sopa cheia"
    assert individual["medidas"][0]["quantidade"] == 45.0
    # O JSON não pode ter criado a planilha quando --format json.
    assert not out.exists()

    db = json.loads((pasta_json / "db.json").read_text(encoding="utf-8"))
    assert len(db["alimentos"]) == 1
    assert "Umidade (g)" in db["alimentos"][0]["por_100g"]
    assert any(m["nome"] == "Prato raso" for m in db["medidas_caseiras"])
    medida = next(m for m in db["alimentos"][0]["medidas"]
                  if m["medida"] == "Colher sopa cheia" and m["componente"] == "Umidade")
    assert medida["valor"] == 38.8


def test_json_serve_de_cache_na_proxima_execucao(tmp_path):
    pasta_json = tmp_path / "json"
    caminho_json = pasta_json / "BRC0001C.json"
    pasta_json.mkdir(parents=True, exist_ok=True)
    caminho_json.write_text(json.dumps({
        "codigo": "BRC0001C",
        "nome": "Alimento do cache",
        "grupo": "C - Frutas e derivados",
        "nome_cientifico": "Persea americana Mill",
        "descricao_tbca": "Alimento do cache",
        "por_100g": {},
        "componentes": [{
            "componente": "Energia", "unidade": "kcal", "valor_100g": 76.0,
            "status": "valor", "texto_original": "76",
            "medidas": [{"indice": 3, "valor": 34.0, "status": "valor"}],
        }],
        "medidas": [{"indice": 3, "nome": "Colher sopa cheia", "unidade": "g", "quantidade": 45.0}],
        "url": "https://exemplo/BRC0001C",
    }, ensure_ascii=False), encoding="utf-8")

    settings = s.Settings(cache_dir=None, json_dir=pasta_json, quiet=True)
    registro = s.ler_json(settings, "BRC0001C")
    assert registro is not None
    detalhe = s.detalhe_de_json(registro)
    assert detalhe["info"]["descricao"] == "Alimento do cache"
    assert detalhe["linhas"][0]["valor_100g"] == 76.0
    assert detalhe["linhas"][0]["valores_medidas"]["3"] == 34.0
    assert detalhe["medidas"][0]["nome"] == "Colher sopa cheia"


def test_json_do_site_ao_vivo_continua_legivel(tmp_path):
    pasta_json = tmp_path / "json"
    settings = s.Settings(cache_dir=None, json_dir=pasta_json, quiet=True)
    detalhe = s.parse_detail_html((SAMPLES / "BRC0001C.html").read_text(encoding="utf-8"))
    registro = s.build_json_record({"codigo": "BRC0001C", "nome": "Abacate",
                                    "nome_cientifico": "", "grupo": "", "marca": "",
                                    "url": "https://exemplo"}, detalhe)
    pasta_json.mkdir(parents=True, exist_ok=True)
    (pasta_json / "BRC0001C.json").write_text(json.dumps(registro, ensure_ascii=False), encoding="utf-8")

    de_volta = s.detalhe_de_json(s.ler_json(settings, "BRC0001C"))
    assert [linha["componente"] for linha in de_volta["linhas"]] == \
        [linha["componente"] for linha in detalhe["linhas"]]
    assert de_volta["linhas"][2]["valor_100g"] == detalhe["linhas"][2]["valor_100g"]


def test_json_fora_da_listagem_vai_para_orfaos(tmp_path):
    pasta = tmp_path / "orfaos"
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "BRC0001C.json").write_text("{}", encoding="utf-8")
    (pasta / "ZZZ9999Z.json").write_text("{}", encoding="utf-8")   # fora da listagem
    (pasta / "db.json").write_text("{}", encoding="utf-8")

    settings = s.Settings(cache_dir=None, json_dir=pasta, quiet=True)
    foods = [{"codigo": "BRC0001C", "url": "u", "nome": "", "nome_cientifico": "",
              "grupo": "", "marca": ""}]
    s.tratar_json_orfaos(foods, settings)

    assert (pasta / "BRC0001C.json").exists()
    assert (pasta / "db.json").exists()
    assert not (pasta / "ZZZ9999Z.json").exists()
    assert (pasta / "orfaos" / "ZZZ9999Z.json").exists()


if __name__ == "__main__":
    import traceback

    pasta_temporaria = RAIZ / ".tmp_tests"
    pasta_temporaria.mkdir(exist_ok=True)

    testes = [valor for nome, valor in sorted(globals().items()) if nome.startswith("test_") and callable(valor)]
    falhas = 0
    for teste in testes:
        try:
            if "tmp_path" in teste.__code__.co_varnames[: teste.__code__.co_argcount]:
                teste(pasta_temporaria)
            else:
                teste()
            print(f"  ok   {teste.__name__}")
        except Exception:
            falhas += 1
            print(f"  FALHA {teste.__name__}")
            traceback.print_exc()
    print(f"\n{len(testes) - falhas}/{len(testes)} testes passaram.")
    sys.exit(1 if falhas else 0)
