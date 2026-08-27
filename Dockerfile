# 1. Escolhe um computador virtual com Python
FROM python:3.10-slim

# 2. Instala o Google Chrome no servidor Linux
RUN apt-get update && apt-get install -y wget gnupg unzip && \
    wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - && \
    sh -c 'echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list' && \
    apt-get update && apt-get install -y google-chrome-stable

# 3. Define a pasta de trabalho
WORKDIR /app

# 4. Copia os seus arquivos para o servidor
COPY . .

# 5. Instala as bibliotecas do requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 6. Comando para ligar a API
CMD ["python", "api_unimed.py"]