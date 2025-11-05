# 🥦 Coletor de Dados da TBCA

**scrape_tbca.py** é um script em Python que realiza a extração automatizada dos dados da [Tabela Brasileira de Composição de Alimentos (TBCA)](https://www.tbca.net.br), consolidando todas as informações em um único arquivo Excel.

---

## 📋 Visão Geral

O script percorre todas as páginas da base de dados da TBCA, coleta as tabelas de composição de alimentos e exporta o resultado final limpo para:
tabela_composicao_alimentos_completa.xlsx

A coleta é feita utilizando as bibliotecas `requests` e `BeautifulSoup` para o scraping, e `pandas` para tratamento e exportação dos dados.

---

## ⚙️ Funcionalidades

- Coleta automática de todas as páginas da TBCA  
- Identificação de paginação e prevenção de duplicatas  
- Exportação consolidada para Excel  
- Uso de cabeçalhos personalizados e tempo de espera entre requisições para evitar sobrecarga no servidor  

---

## 🧠 Requisitos

- Python 3.8 ou superior  
- Bibliotecas:
  - pandas  
  - requests  
  - beautifulsoup4  

Instale todas as dependências executando:

```bash
pip install -r requirements.txt
