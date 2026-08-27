# 1. Imagem base do Python
FROM python:3.10-slim

# 2. Instala dependências e adiciona a chave do Google Chrome no formato moderno
RUN apt-get update && apt-get install -y wget gnupg curl \
    && curl -sS https://dl-ssl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

# 3. Define a pasta de trabalho
WORKDIR /app

# 4. Copia os arquivos do projeto para o servidor
COPY . .

# 5. Instala as bibliotecas do projeto
RUN pip install --no-cache-dir -r requirements.txt

# 6. Comando para iniciar a API
CMD ["python", "api_unimed.py"]