# Imagem para o modo "fontes públicas" (sem Chrome/nodriver).
# As fontes logadas (Vagas/Catho/Workana/99freelas/Jobbol) precisam de Chrome e
# login manual — não fazem sentido em container; deixe-as desligadas no config.
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
# nodriver é opcional (só fontes logadas); ignore falha se não instalar no slim
RUN pip install --no-cache-dir -r requirements.txt || true

COPY . .

# Painel local
EXPOSE 8765

# Forneça config.yaml, perfil.md e .env via volume/secret. Ex:
#   docker run -p 8765:8765 \
#     -v $PWD/config.yaml:/app/config.yaml \
#     -v $PWD/perfil.md:/app/perfil.md \
#     --env-file .env  garimpeiro
CMD ["python", "garimpeiro.py", "schedule"]
