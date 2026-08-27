"""API para consultar hospitais no Guia Médico da Unimed."""
import os
import re
import threading
import time

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


class ErroNaConsulta(RuntimeError):
    """Erro esperado ao consultar o site da Unimed."""


def buscar_hospitais_unimed(cep: str) -> list[dict[str, str]]:
    """Pesquisa o CEP no Guia Médico e retorna os hospitais encontrados."""
    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--remote-debugging-pipe")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
    )
    chrome_bin = os.environ.get("CHROME_BIN")
    if chrome_bin:
        chrome_options.binary_location = chrome_bin

    try:
        driver = webdriver.Chrome(options=chrome_options)
    except WebDriverException as exc:
        raise ErroNaConsulta(
            "Não foi possível iniciar o Chrome. Verifique se o Google Chrome "
            "está instalado e atualizado."
        ) from exc

    try:
        resposta_cep = requests.get(
            f"https://brasilapi.com.br/api/cep/v2/{re.sub(r'\D', '', cep)}",
            timeout=15,
        )
        resposta_cep.raise_for_status()
        coordenadas = resposta_cep.json()["location"]["coordinates"]
        driver.execute_cdp_cmd(
            "Browser.grantPermissions",
            {"origin": "https://www.unimed.coop.br", "permissions": ["geolocation"]},
        )
        driver.execute_cdp_cmd(
            "Emulation.setGeolocationOverride",
            {
                "latitude": float(coordenadas["latitude"]),
                "longitude": float(coordenadas["longitude"]),
                "accuracy": 50,
            },
        )

        driver.get("https://www.unimed.coop.br/site/web/guest/guia-medico")
        wait = WebDriverWait(driver, 30)

        botoes_cookie = driver.find_elements(
            By.CSS_SELECTOR, "[data-testid='actionButton-reject']"
        )
        if botoes_cookie:
            driver.execute_script("arguments[0].click()", botoes_cookie[0])

        campo_servico = wait.until(
            EC.presence_of_element_located((By.ID, "react-select-2-input"))
        )
        opcao_hospital = None
        for _ in range(3):
            driver.execute_script("arguments[0].focus()", campo_servico)
            campo_servico.clear()
            campo_servico.send_keys("hospital")
            try:
                opcao_hospital = WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located(
                        (
                            By.XPATH,
                            "//div[contains(@id, 'react-select-2-option')]"
                            "[normalize-space(.)='Hospital']",
                        )
                    )
                )
                break
            except TimeoutException:
                campo_servico.clear()
                time.sleep(1)

        if opcao_hospital is None:
            raise ErroNaConsulta(
                "O site da Unimed não retornou a opção Hospital. Tente novamente."
            )

        driver.execute_script("arguments[0].click()", opcao_hospital)
        botao_pesquisar = wait.until(
            lambda navegador: next(
                (
                    elemento
                    for elemento in navegador.find_elements(
                        By.CSS_SELECTOR, "button[type='submit']"
                    )
                    if elemento.is_displayed()
                    and elemento.text.strip() == "Pesquisar"
                ),
                False,
            )
        )
        driver.execute_script("arguments[0].click()", botao_pesquisar)
        wait.until(lambda navegador: "#/results/" in navegador.current_url)
        wait.until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, ".ProviderCard .Provider--name")
            )
        )

        soup = BeautifulSoup(driver.page_source, "html.parser")
        hospitais = []
        for card in soup.select(".ProviderCard"):
            elem_nome = card.select_one(".Provider--name")
            elem_endereco = card.select_one(".ProviderAddressAsGrid--address-link")
            elem_distancia = card.select_one(".ProviderAddressAdditional")
            if elem_nome:
                hospitais.append(
                    {
                        "hospital": elem_nome.get_text(" ", strip=True),
                        "endereco": (
                            elem_endereco.get_text(" ", strip=True)
                            if elem_endereco
                            else "Endereço não informado"
                        ),
                        "distancia": (
                            elem_distancia.get_text(" ", strip=True)
                            if elem_distancia
                            else None
                        ),
                    }
                )
        return hospitais
    except ErroNaConsulta:
        raise
    except requests.RequestException as exc:
        raise ErroNaConsulta("Não foi possível localizar o CEP informado.") from exc
    except (TimeoutException, WebDriverException) as exc:
        raise ErroNaConsulta(
            "O site da Unimed demorou para responder. Tente novamente em instantes."
        ) from exc
    except Exception as exc:
        raise ErroNaConsulta("Não foi possível concluir a consulta na Unimed.") from exc
    finally:
        driver.quit()


@app.get("/")
def inicio():
    return jsonify({"status": "online", "uso": "/api/hospitais?cep=33080-315"})


@app.get("/api/hospitais")
@app.get("/api/hospitais")
def api_buscar_hospitais():
    cep_recebido = request.args.get("cep", "").strip()
    cep_numerico = re.sub(r"\D", "", cep_recebido)
    if len(cep_numerico) != 8:
        return jsonify({"erro": "Forneça um CEP válido com 8 dígitos."}), 400

    cep_formatado = f"{cep_numerico[:5]}-{cep_numerico[5:]}"

    # Aguarda até 60 segundos na fila em vez de rejeitar de imediato
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

    return jsonify(
        {
            "cep_buscado": cep_formatado,
            "quantidade": len(resultado),
            "hospitais": resultado,
        }
    )


if __name__ == "__main__":
    from waitress import serve

    porta = int(os.environ.get("PORT", 5000))
    print(f"API disponível na porta {porta}")
    serve(app, host="0.0.0.0", port=porta, threads=2)
