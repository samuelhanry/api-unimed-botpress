# 1. Escolhe um computador virtual com Python
FROM python:3.10-slim

# 2. Instala o Chromium e o seu motorista (WebDriver) direto da loja oficial do Linux
RUN apt-get update && apt-get install -y chromium chromium-driver

# 3. Define a pasta de trabalho
WORKDIR /app

# 4. Copia os seus arquivos para o servidor
COPY . .

# 5. Instala as bibliotecas do requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 6. Comando para ligar a API
CMD ["python", "api_unimed.py"]