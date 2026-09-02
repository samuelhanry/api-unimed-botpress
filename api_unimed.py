"""API para consultar hospitais no Guia Médico da Unimed."""
import os
import re
import threading
import time
from functools import lru_cache

import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, request
from flask_cors import CORS
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})
consulta_em_andamento = threading.Lock()

navegador_global = None

class ErroNaConsulta(RuntimeError):
    """Erro esperado ao consultar o site da Unimed."""

def obter_navegador():
    """Gerencia a instância do Chrome para reutilizá-la e poupar tempo de inicialização."""
    global navegador_global
    
    try:
        if navegador_global:
            _ = navegador_global.current_url
            return navegador_global
    except Exception:
        navegador_global = None

    print("▶️ [SISTEMA] Iniciando uma nova instância do Chrome (apenas uma vez)...")
    chrome_options = webdriver.ChromeOptions()
    
    # Voltamos para 'eager' para garantir que a base do site exista antes de buscar os botões
    chrome_options.page_load_strategy = 'eager' 
    
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--blink-settings=imagesEnabled=false")
    chrome_options.add_argument("--window-size=1280,720")
    
    prefs = {
        "profile.managed_default_content_settings.images": 2,
        "profile.managed_default_content_settings.stylesheets": 2,
        "profile.default_content_setting_values.notifications": 2
    }
    chrome_options.add_experimental_option("prefs", prefs)

    chrome_bin = os.environ.get("CHROME_BIN")
    if chrome_bin:
        chrome_options.binary_location = chrome_bin

    navegador_global = webdriver.Chrome(options=chrome_options)
    
    navegador_global.execute_cdp_cmd("Network.enable", {})
    navegador_global.execute_cdp_cmd("Network.setBlockedURLs", {
        "urls": ["*google-analytics.com*", "*googletagmanager.com*", "*.woff2", "*.woff", "*.ttf", "*hotjar.com*"]
    })
    
    return navegador_global

@lru_cache(maxsize=100)
def buscar_hospitais_unimed(cep: str) -> list[dict[str, str]]:
    """Pesquisa o CEP no Guia Médico e retorna os hospitais com carregamento estável."""
    print(f"▶️ [PASSO 1] Iniciando busca para o CEP {cep}...")
    
    try:
        driver = obter_navegador()
    except WebDriverException as exc:
        raise ErroNaConsulta("Não foi possível iniciar o Chrome.") from exc

    try:
        print("▶️ [PASSO 2] Buscando coordenadas na BrasilAPI...")
        resposta_cep = requests.get(
            f"https://brasilapi.com.br/api/cep/v2/{re.sub(r'\D', '', cep)}",
            timeout=10,
        )
        resposta_cep.raise_for_status()
        coordenadas = resposta_cep.json()["location"]["coordinates"]
        
        driver.execute_cdp_cmd("Browser.grantPermissions", {"origin": "https://www.unimed.coop.br", "permissions": ["geolocation"]})
        driver.execute_cdp_cmd("Emulation.setGeolocationOverride", {
            "latitude": float(coordenadas["latitude"]),
            "longitude": float(coordenadas["longitude"]),
            "accuracy": 50,
        })

        print("▶️ [PASSO 3] Acessando Unimed...")
        driver.get("https://www.unimed.coop.br/site/web/guest/guia-medico")
        
        # Aumentamos a paciência do robô para 40 segundos, evitando que ele desista cedo
        wait = WebDriverWait(driver, 40) 
        
        print("▶️ [PASSO 4] Procurando o campo de serviço...")
        botoes_cookie = driver.find_elements(By.CSS_SELECTOR, "[data-testid='actionButton-reject']")
        if botoes_cookie:
            driver.execute_script("arguments[0].click()", botoes_cookie[0])

        campo_servico = wait.until(EC.presence_of_element_located((By.ID, "react-select-2-input")))
        opcao_hospital = None
        
        for _ in range(3):
            driver.execute_script("arguments[0].focus()", campo_servico)
            campo_servico.clear()
            campo_servico.send_keys("hospital")
            try:
                opcao_hospital = WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((By.XPATH, "//div[contains(@id, 'react-select-2-option')][normalize-space(.)='Hospital']"))
                )
                break
            except TimeoutException:
                campo_servico.clear()
                time.sleep(1)
        
        if opcao_hospital is None:
            raise ErroNaConsulta("O site da Unimed não retornou a opção Hospital.")

        driver.execute_script("arguments[0].click()", opcao_hospital)
        
        print("▶️ [PASSO 5] Clicando em pesquisar...")
        botao_pesquisar = wait.until(
            lambda nav: next((el for el in nav.find_elements(By.CSS_SELECTOR, "button[type='submit']") if el.is_displayed() and el.text.strip() == "Pesquisar"), False)
        )
        driver.execute_script("arguments[0].click()", botao_pesquisar)
        wait.until(lambda nav: "#/results/" in nav.current_url)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".ProviderCard .Provider--name")))

        print("✅ [SUCESSO] Dados extraídos!")
        soup = BeautifulSoup(driver.page_source, "html.parser")
        hospitais = []
        for card in soup.select(".ProviderCard"):
            elem_nome = card.select_one(".Provider--name")
            if elem_nome:
                elem_endereco = card.select_one(".ProviderAddressAsGrid--address-link")
                elem_distancia = card.select_one(".ProviderAddressAdditional")
                hospitais.append({
                    "hospital": elem_nome.get_text(" ", strip=True),
                    "endereco": elem_endereco.get_text(" ", strip=True) if elem_endereco else "Endereço não informado",
                    "distancia": elem_distancia.get_text(" ", strip=True) if elem_distancia else None,
                })
        return hospitais
    except Exception as exc:
        raise ErroNaConsulta("Houve uma lentidão no site da Unimed. Tente novamente.") from exc

@app.get("/")
def inicio():
    return jsonify({"status": "online", "uso": "/api/hospitais?cep=33080-315"})

@app.get("/api/hospitais")
def api_buscar_hospitais():
    cep_recebido = request.args.get("cep", "").strip()
    cep_numerico = re.sub(r"\D", "", cep_recebido)
    if len(cep_numerico) != 8:
        return jsonify({"erro": "Forneça um CEP válido com 8 dígitos."}), 400

    cep_formatado = f"{cep_numerico[:5]}-{cep_numerico[5:]}"

    if not consulta_em_andamento.acquire(blocking=True, timeout=60):
        return jsonify({"erro": "Servidor ocupado. Tente novamente em instantes."}), 429

    try:
        try:
            resultado = buscar_hospitais_unimed(cep_formatado)
        except ErroNaConsulta as exc:
            app.logger.exception("Erro ao pesquisar o CEP %s", cep_formatado)
            return jsonify({"erro": str(exc)}), 502
    finally:
        consulta_em_andamento.release()

    return jsonify({"cep_buscado": cep_formatado, "quantidade": len(resultado), "hospitais": resultado})

if __name__ == "__main__":
    from waitress import serve
    porta = int(os.environ.get("PORT", 5000))
    print(f"API disponível na porta {porta}")
    serve(app, host="0.0.0.0", port=porta, threads=2)
