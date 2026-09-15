"""Exporta os JSONs da TBCA para o pacote de importacao (CSV + JSON + inventario).

Gera, em entrega_tbca/:
  csv/foods.csv, nutrients.csv, food_nutrients.csv, measures.csv, measure_nutrients.csv
  json/foods.json, nutrients.json, food_nutrients.json, measures.json, measure_nutrients.json
  json/manifest.json
"""
from __future__ import annotations

import csv
import glob
import hashlib
import json
import os
import re
import shutil
from collections import Counter, OrderedDict

RAIZ = os.path.dirname(os.path.abspath(__file__))
ENTRADA = os.path.join(RAIZ, "dados_tbca")
SAIDA = os.path.join(RAIZ, "entrega_tbca")

# code, nome, unidade, grupo, casas decimais, sinonimos
NUTRIENTES = [
    ("energy_kj", "Energia", "kJ", "energia", 0, []),
    ("energy_kcal", "Energia", "kcal", "energia", 0, []),
    ("moisture_g", "Umidade", "g", "proximais", 2, []),
    ("carbohydrate_total_g", "Carboidrato total", "g", "carboidratos", 2, []),
    ("carbohydrate_available_g", "Carboidrato disponivel", "g", "carboidratos", 2, []),
    ("protein_g", "Proteina", "g", "proteina", 2, []),
    ("lipid_g", "Lipidios", "g", "lipidios", 2, []),
    ("fiber_g", "Fibra alimentar", "g", "fibra", 2, []),
    ("alcohol_g", "Alcool", "g", "proximais", 2, []),
    ("ash_g", "Cinzas", "g", "proximais", 2, []),
    ("cholesterol_mg", "Colesterol", "mg", "lipidios", 2, []),
    ("fatty_acid_saturated_g", "Acidos graxos saturados", "g", "lipidios", 3, []),
    ("fatty_acid_monounsaturated_g", "Acidos graxos monoinsaturados", "g", "lipidios", 3, []),
    ("fatty_acid_polyunsaturated_g", "Acidos graxos poliinsaturados", "g", "lipidios", 3, []),
    ("fatty_acid_trans_g", "Acidos graxos trans", "g", "lipidios", 3, []),
    ("calcium_mg", "Calcio", "mg", "minerais", 3, []),
    ("iron_mg", "Ferro", "mg", "minerais", 3, []),
    ("sodium_mg", "Sodio", "mg", "minerais", 3, []),
    ("magnesium_mg", "Magnesio", "mg", "minerais", 3, []),
    ("phosphorus_mg", "Fosforo", "mg", "minerais", 3, []),
    ("potassium_mg", "Potassio", "mg", "minerais", 3, []),
    ("manganese_mg", "Manganes", "mg", "minerais", 3, []),
    ("zinc_mg", "Zinco", "mg", "minerais", 3, []),
    ("copper_mg", "Cobre", "mg", "minerais", 3, []),
    ("selenium_mcg", "Selenio", "mcg", "minerais", 3, []),
    ("vitamin_a_re_mcg", "Vitamina A (RE)", "mcg", "vitaminas", 3, ["retinol_equivalent"]),
    ("vitamin_a_rae_mcg", "Vitamina A (RAE)", "mcg", "vitaminas", 3, ["retinol_activity_equivalent"]),
    ("vitamin_d_mcg", "Vitamina D", "mcg", "vitaminas", 3, []),
    ("vitamin_e_mg", "Alfa-tocoferol (Vitamina E)", "mg", "vitaminas", 3, []),
    ("thiamin_mg", "Tiamina", "mg", "vitaminas", 3, ["vitamin_b1"]),
    ("riboflavin_mg", "Riboflavina", "mg", "vitaminas", 3, ["vitamin_b2"]),
    ("niacin_mg", "Niacina", "mg", "vitaminas", 3, ["vitamin_b3"]),
    ("vitamin_b6_mg", "Vitamina B6", "mg", "vitaminas", 3, ["pyridoxine"]),
    ("vitamin_b12_mcg", "Vitamina B12", "mcg", "vitaminas", 3, ["cobalamin"]),
    ("vitamin_c_mg", "Vitamina C", "mg", "vitaminas", 3, ["ascorbic_acid"]),
    ("folate_equivalent_mcg", "Equivalente de folato", "mcg", "vitaminas", 3, ["dietary_folate_equivalent"]),
    ("added_salt_g", "Sal de adicao", "g", "adicao", 2, []),
    ("added_sugar_g", "Acucar de adicao", "g", "adicao", 2, []),
    ("added_fat_g", "Gordura de adicao", "g", "adicao", 2, []),
    ("vegetable_protein_g", "Proteina vegetal", "g", "proteina", 2, []),
    ("animal_protein_g", "Proteina animal", "g", "proteina", 2, []),
]

# chave do componente -> (code, unidade)
MAPA = {}
for code, nome, unidade, _g, _d, _s in NUTRIENTES:
    MAPA[(nome, unidade)] = code
MAPA[("Proteina", "g")] = "protein_g"

# precisao de casas decimais para o valor derivado (por medida)
CASAS = {code: d for code, _n, _u, _g, d, _s in NUTRIENTES}


def normalizar(texto: str) -> str:
    """Remove acentos e reduz a forma comparavel (apenas para casar nomes)."""
    tabela = str.maketrans(
        "áàâãäéèêëíìîïóòôõöúùûüçÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇ",
        "aaaaaeeeeiiiiooooouuuucAAAAAEEEEIIIIOOOOOUUUUC",
    )
    return texto.translate(tabela).lower()


# indice de nomes normalizados -> code (para casar componentes reais dos arquivos)
MAPA_NORM = {}
for (nome, unidade), code in MAPA.items():
    MAPA_NORM[(normalizar(nome), unidade.lower())] = code


def carregar_alimentos():
    arquivos = sorted(glob.glob(os.path.join(ENTRADA, "BRC*.json")))
    for caminho in arquivos:
        with open(caminho, encoding="utf-8") as fh:
            yield caminho, json.load(fh)


def gerar():
    # Limpa apenas o que este script gera. LEIA-ME.md, ESQUEMA.md,
    # ANALISE-DOS-DADOS.md e sql/ sao mantidos a mao e nao podem ser apagados.
    for sub in ("csv", "json"):
        caminho = os.path.join(SAIDA, sub)
        if os.path.isdir(caminho):
            shutil.rmtree(caminho)
        os.makedirs(caminho, exist_ok=True)

    alimentos = []          # linhas de foods
    fn_rows = []            # food_nutrients
    md_rows = []            # measures
    mn_rows = []            # measure_nutrients
    alertas = []            # dados que merecem atencao
    sem_composicao = []     # alimentos listados na TBCA sem composicao coletada
    codigos_vistos = set()
    componentes_desconhecidos = Counter()
    status_100 = Counter()
    status_med = Counter()
    duplicados = []

    for caminho, j in carregar_alimentos():
        codigo = j["codigo"]
        if codigo in codigos_vistos:
            alertas.append(f"codigo duplicado: {codigo}")
        codigos_vistos.add(codigo)

        componentes = j.get("componentes") or []
        med_raw = j.get("medidas") or []
        nome = j.get("nome", "")

        # --- foods ---
        if not componentes:
            sem_composicao.append(codigo)
            alertas.append(f"{codigo}: sem composicao coletada ({nome[:50]})")

        chaves = Counter()
        for c in componentes:
            chaves[(normalizar(c["componente"]), (c["unidade"] or "").lower())] += 1

        if not componentes:
            energia_kcal = energia_kj = None
        else:
            energia_kcal = energia_kj = None
            for c in componentes:
                if normalizar(c["componente"]) == "energia":
                    if c["unidade"] == "kcal":
                        energia_kcal = c["valor_100g"]
                    elif c["unidade"] == "kJ":
                        energia_kj = c["valor_100g"]

        completo = bool(componentes) and all(v == 1 for v in chaves.values())
        if componentes and not completo:
            dup = [k for k, v in chaves.items() if v > 1]
            duplicados.append(codigo)
            alertas.append(
                f"{codigo}: componente repetido no mesmo alimento ({len(dup)} chaves)")

        # grupo: 'C - Frutas e derivados' -> codigo do grupo + nome
        grupo_completo = j.get("grupo_completo", "") or ""
        m = re.match(r"^\s*([A-Z])\s*-\s*(.+)$", grupo_completo)
        grupo_codigo = m.group(1) if m else ""
        grupo_nome = m.group(2).strip() if m else (j.get("grupo", "") or "")

        tipo = j.get("tipo_alimento", "") or ""
        t = re.match(r"^\s*([A-Z])\s*-\s*(.+?)(?:\s+Marca:\s*(.+))?$", tipo)
        tipo_codigo = t.group(1) if t else ""
        tipo_nome = t.group(2).strip() if t else tipo
        marca_tipo = (t.group(3) or "").strip() if t else ""

        # medidas caseiras distintas (nome, unidade, quantidade)
        distinct = []
        vistos = set()
        for mm in med_raw:
            chave = (mm["nome"], mm["unidade"], mm["quantidade"])
            if chave in vistos:
                continue
            vistos.add(chave)
            distinct.append(mm)

        usadas = 0
        for mm in distinct:
            qtd = mm["quantidade"]
            if mm["unidade"] not in ("g", "mL") or qtd is None or qtd <= 0:
                alertas.append(
                    f"{codigo}: medida '{mm['nome']}' com unidade/quantidade invalida "
                    f"({mm['unidade']!r}, {qtd!r})")
                continue
            usadas += 1
            md_rows.append(OrderedDict([
                ("food_code", codigo),
                ("measure_index", mm["indice"]),
                ("measure_name", mm["nome"]),
                ("measure_unit", mm["unidade"]),
                ("measure_quantity", fmt(qtd)),
                ("measure_grams", fmt(qtd)),
                ("is_duplicate_name", "true" if False else ""),
            ]))

        contagem_nome = Counter(mm["nome"] for mm in distinct)

        alimentos.append(OrderedDict([
            ("code", codigo),
            ("name", nome),
            ("scientific_name", j.get("nome_cientifico", "") or ""),
            ("group_code", grupo_codigo),
            ("group_name", grupo_nome),
            ("type_code", tipo_codigo),
            ("type_name", tipo_nome),
            ("brand", (j.get("marca", "") or marca_tipo or "").strip()),
            ("description_pt", primeira_descricao(j.get("descricao_tbca", ""))),
            ("description_en", traducao(j.get("descricao_traducoes", ""), 0)),
            ("description_es", traducao(j.get("descricao_traducoes", ""), 1)),
            ("energy_kcal_per_100g", fmt(energia_kcal)),
            ("energy_kj_per_100g", fmt(energia_kj)),
            ("measure_count", usadas),
            ("composition_collected", "true" if componentes else "false"),
            ("source_url", j.get("url", "") or ""),
            ("tbca_version", j.get("versao_scraper", "") or ""),
            ("collected_at", j.get("coletado_em", "") or ""),
        ]))

        # por alimento, para saber quais nomes sao ambiguos
        nomes_ambiguos = {n for n, c in contagem_nome.items() if c > 1}
        if nomes_ambiguos:
            alertas.append(
                f"{codigo}: medida caseira repetida com gramaturas diferentes "
                f"({', '.join(sorted(nomes_ambiguos))})")

        # --- food_nutrients + measure_nutrients ---
        indices_validos = {mm["indice"]: mm for mm in distinct
                           if mm["unidade"] in ("g", "mL") and mm["quantidade"] and mm["quantidade"] > 0}
        for c in componentes:
            nome_c = c["componente"]
            unidade = c["unidade"] or ""
            key = (normalizar(nome_c), unidade.lower())
            code = MAPA_NORM.get(key)
            if code is None:
                componentes_desconhecidos[(nome_c, unidade)] += 1
                continue
            status_100[c["status"]] += 1
            fn_rows.append(OrderedDict([
                ("food_code", codigo),
                ("nutrient_code", code),
                ("value_per_100g", fmt(c["valor_100g"])),
                ("value_status", c["status"]),
                ("value_text", c.get("texto_original", "") or ""),
            ]))
            casas = CASAS[code]
            for v in c["medidas"]:
                mm = indices_validos.get(v["indice"])
                if mm is None:
                    continue
                qtd = mm["quantidade"]
                base = c["valor_100g"]
                if base is None or v["status"] == "ausente":
                    derivado = None
                else:
                    derivado = round(base * qtd / 100.0, casas)
                status_med[v["status"]] += 1
                texto_medida = fmt(derivado)
                mn_rows.append(OrderedDict([
                    ("food_code", codigo),
                    ("measure_index", v["indice"]),
                    ("nutrient_code", code),
                    ("value_measure", fmt_medida(v["valor"], v["status"], casas)),
                    ("value_per_100g_derived", texto_medida),
                    ("value_status", v["status"]),
                ]))

    md_rows.sort(key=lambda r: (r["food_code"], r["measure_index"]))
    fn_rows.sort(key=lambda r: (r["food_code"], r["nutrient_code"]))
    mn_rows.sort(key=lambda r: (r["food_code"], r["measure_index"], r["nutrient_code"]))

    # marca medidas cujo nome se repete no mesmo alimento
    repetidas = Counter((r["food_code"], r["measure_name"]) for r in md_rows)
    for r in md_rows:
        if repetidas[(r["food_code"], r["measure_name"])] > 1:
            r["is_duplicate_name"] = "true"

    if componentes_desconhecidos:
        alertas.append(f"componentes sem mapeamento: {dict(componentes_desconhecidos)}")

    nutrients_rows = [OrderedDict([
        ("code", code),
        ("display_name", nome),
        ("unit", unidade),
        ("nutrient_group", grupo),
        ("decimal_places", casas),
        ("synonyms", ";".join(sin)),
    ]) for code, nome, unidade, grupo, casas, sin in NUTRIENTES]

    escrever_csv("foods.csv", alimentos)
    escrever_csv("nutrients.csv", nutrients_rows)
    escrever_csv("food_nutrients.csv", fn_rows)
    escrever_csv("measures.csv", md_rows)
    escrever_csv("measure_nutrients.csv", mn_rows)

    escrever_json("foods.json", numerizar(alimentos, "foods"))
    escrever_json("nutrients.json", nutrients_rows)
    escrever_json("food_nutrients.json", numerizar(fn_rows, "food_nutrients"))
    escrever_json("measures.json", numerizar(md_rows, "measures"))
    escrever_json("measure_nutrients.json", numerizar(mn_rows, "measure_nutrients"))

    inventario = OrderedDict([
        ("gerado_em", __import__("time").strftime("%Y-%m-%dT%H:%M:%S")),
        ("fonte", "TBCA - Tabela Brasileira de Composicao de Alimentos (USP/FoRC)"),
        ("fonte_url", "https://www.tbca.net.br"),
        ("base", "valores por 100 g da parte comestivel"),
        ("licenca", "CC BY-NC-ND 4.0 - citar a fonte; vedado uso comercial e alteracao"),
        ("contagens", OrderedDict([
            ("foods", len(alimentos)),
            ("foods_sem_composicao", len(sem_composicao)),
            ("nutrients", len(nutrients_rows)),
            ("food_nutrients", len(fn_rows)),
            ("measures", len(md_rows)),
            ("measure_nutrients", len(mn_rows)),
        ])),
        ("status_valor_100g", dict(status_100)),
        ("status_valor_medida", dict(status_med)),
        ("alimentos_com_componente_repetido", sorted(duplicados)),
        ("alertas", alertas),
        ("arquivos", {}),
    ])

    for pasta, nome in [("csv", f) for f in
                        ["foods.csv", "nutrients.csv", "food_nutrients.csv", "measures.csv", "measure_nutrients.csv"]] + \
                       [("json", f) for f in
                        ["foods.json", "nutrients.json", "food_nutrients.json", "measures.json", "measure_nutrients.json"]]:
        p = os.path.join(SAIDA, pasta, nome)
        with open(p, "rb") as fh:
            dados = fh.read()
        inventario["arquivos"][f"{pasta}/{nome}"] = {
            "bytes": len(dados),
            "md5": hashlib.md5(dados).hexdigest(),
            "linhas": contar_linhas(p),
        }

    escrever_json("manifest.json", inventario, pasta="json")

    print(json.dumps(inventario["contagens"], indent=2, ensure_ascii=False))
    print("status 100g:", dict(status_100))
    print("status medida:", dict(status_med))
    print("alertas:", len(alertas))
    print("alimentos sem composicao:", len(sem_composicao))
    print("componentes sem mapeamento:", dict(componentes_desconhecidos))
    print("duplicados:", duplicados)


def contar_linhas(caminho):
    import csv as _csv
    with open(caminho, encoding="utf-8", newline="") as fh:
        return sum(1 for _ in _csv.reader(fh))


def primeira_descricao(texto: str) -> str:
    if not texto:
        return ""
    return texto.split("<<")[0].strip()


def traducao(texto: str, pos: int) -> str:
    if not texto:
        return ""
    partes = [p.strip() for p in texto.split("|") if p.strip()]
    return partes[pos] if pos < len(partes) else ""


def fmt(valor):
    if valor is None:
        return ""
    if isinstance(valor, float):
        if valor.is_integer():
            return str(int(valor))
        return f"{valor:.6f}".rstrip("0").rstrip(".")
    return str(valor)


# colunas que no JSON viram numero (ou null), e nao string vazia,
# para poderem ser inseridas direto por supabase-js sem conversao.
NUMERICAS = {
    "foods": {"energy_kcal_per_100g", "energy_kj_per_100g", "measure_count"},
    "food_nutrients": {"value_per_100g"},
    "measures": {"measure_index", "measure_quantity", "measure_grams"},
    "measure_nutrients": {"measure_index", "value_measure", "value_per_100g_derived"},
}
INTEIRAS = {
    "foods": {"measure_count"},
    "measures": {"measure_index"},
    "measure_nutrients": {"measure_index"},
}
BOOLEANAS = {
    "foods": {"composition_collected"},
    "measures": {"is_duplicate_name"},
}


def numerizar(linhas, tabela):
    """Converte para numero/inteiro/bool os campos que o schema espera, no JSON."""
    nums = NUMERICAS.get(tabela, set())
    ints = INTEIRAS.get(tabela, set())
    bools = BOOLEANAS.get(tabela, set())
    saida = []
    for linha in linhas:
        nova = OrderedDict()
        for chave, valor in linha.items():
            if chave in nums:
                if valor == "":
                    nova[chave] = None
                elif chave in ints:
                    nova[chave] = int(float(valor))
                else:
                    nova[chave] = float(valor)
            elif chave in bools:
                nova[chave] = valor == "true"
            else:
                nova[chave] = valor
        saida.append(nova)
    return saida


def fmt_medida(valor, status, casas):
    """Valor publicado para uma medida caseira.

    Regras da TBCA: 'ausente' -> sem valor; 'traco' -> 0 (gravado como 0);
    'valor' -> numero arredondado nas casas do nutriente.
    """
    if status == "ausente" or valor is None:
        return ""
    return fmt(round(float(valor), casas))


def escrever_csv(nome, linhas):
    caminho = os.path.join(SAIDA, "csv", nome)
    with open(caminho, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(linhas[0].keys()), lineterminator="\n")
        w.writeheader()
        w.writerows(linhas)
    print(f"  {nome}: {len(linhas)} linhas")


def escrever_json(nome, dados, pasta="json"):
    caminho = os.path.join(SAIDA, pasta, nome)
    with open(caminho, "w", encoding="utf-8") as fh:
        json.dump(dados, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"  {nome}: {os.path.getsize(caminho) / 1024 / 1024:.1f} MB")


if __name__ == "__main__":
    gerar()
