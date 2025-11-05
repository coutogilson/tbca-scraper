"""
Script: scraping_tbca.py
Descrição: Extrai e registra os dados da Tabela Brasileira de Composição de Alimentos (TBCA) em arquivo xlsx.
Autor: Lucas Prieto Accorsi
Data: 2025-11-04
Versão: 1.0
"""


import io
import time
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup


# --- VARIÁVEIS DE CONFIGURAÇÃO ---
BASE_URL = "https://www.tbca.net.br/base-dados/composicao_alimentos.php"
OUTPUT_FILENAME = "tabela_composicao_alimentos_completa.xlsx"
DELAY = 1  # Delay entre requisições (em segundos)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/91.0.4472.124 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Connection": "keep-alive",
}

# --- FUNÇÕES PRINCIPAIS ---
def fetch_page_content(session, url):
    """Busca o HTML de uma página e retorna o BeautifulSoup, ou None em caso de erro."""
    
    print(f"--- Processando URL: {url} ---")
    try:
        response = session.get(url, timeout=15)
        response.raise_for_status()
        return BeautifulSoup(response.text, 'html.parser')
    except requests.exceptions.RequestException as e:
        print(f"ERRO DE REQUISIÇÃO ao buscar a URL {url}: {e}")
        return None
    except Exception as e:
        print(f"ERRO INESPERADO ao buscar a URL {url}: {e}")
        return None


def extract_table_data(soup, url):
    """
    Extrai a tabela de composição de alimentos de um objeto BeautifulSoup.
    """
    tables = soup.find_all('table', {'class': 'table table-striped'})
    if tables:
        try:
            df = pd.read_html(io.StringIO(str(tables[0])), header=0)[0]
            print("[SUCESSO] Dados da tabela extraídos.")
            return df
        except Exception as e:
            print(f"[AVISO] Erro ao ler a tabela com pandas.read_html em {url}: {e}")
            return None
    else:
        print(f"[AVISO] Nenhuma tabela de dados (class='table table-striped') encontrada em {url}.")
        return None


def discover_pagination_links(soup, base_url, processed_urls, urls_to_visit):
    """
    Encontra links de paginação e os adiciona à fila de URLs a visitar, se forem novos.
    """
    pagination_div = soup.find('div', {'id': 'block_2', 'class': 'pagination'})
    if pagination_div:
        links = pagination_div.find_all('a', href=True)
        new_links_count = 0

        for link in links:
            href = link['href']
            next_url = urljoin(base_url, href)
            if next_url not in processed_urls and next_url not in urls_to_visit:
                urls_to_visit.append(next_url)
                new_links_count += 1

        if new_links_count > 0:
            print(f"  [INFO] Descobertos {new_links_count} novos links de paginação para a fila.")

# --- FLUXO PRINCIPAL ---
def main_scraper():
    """
    Função principal que coordena o processo de crawling, extração e salvamento de dados.
    """
    print("\nIniciando rastreamento da TBCA...")


    urls_to_visit = [BASE_URL]
    processed_urls = set()
    all_dataframes = []

    with requests.Session() as session:
        session.headers.update(HEADERS)

        while urls_to_visit:
            current_url = urls_to_visit.pop(0)

            if current_url in processed_urls:
                continue

            soup = fetch_page_content(session, current_url)
            processed_urls.add(current_url)

            if soup is None:
                time.sleep(DELAY)
                continue

            df = extract_table_data(soup, current_url)
            if df is not None:
                all_dataframes.append(df)

            discover_pagination_links(soup, BASE_URL, processed_urls, urls_to_visit)

            time.sleep(DELAY)

    print("\n===============================================")
    print(f"RASTREIO FINALIZADO. {len(processed_urls)} URLs únicas processadas.")
    print("===============================================")

    if all_dataframes:
        print("Concatenando e limpando os dados coletados...")
        final_df = pd.concat(all_dataframes, ignore_index=True)

        initial_rows = len(final_df)
        final_df.drop_duplicates(inplace=True)
        removed_duplicates = initial_rows - len(final_df)

        try:
            final_df.to_excel(OUTPUT_FILENAME, index=False)
            print(f"\n[OK] {len(final_df)} registros únicos salvos em '{OUTPUT_FILENAME}'.")

            if removed_duplicates > 0:
                print(f"   ({removed_duplicates} linhas duplicadas removidas durante o pós-processamento.)")
        except Exception as e:
            print(f"\n ERRO ao salvar o arquivo Excel: {e}")
    else:
        print("ATENÇÃO: Nenhum dado foi coletado para salvar.")


if __name__ == "__main__":
    print("Iniciando coleta de dados da TBCA...\n")
    main_scraper()
    print("\nProcesso concluído.")

