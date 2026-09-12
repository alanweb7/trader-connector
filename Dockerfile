FROM python:3.11-slim

WORKDIR /app

# Instalar dependências do sistema
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copiar arquivos de dependência
COPY pyproject.toml .
COPY src/ src/

# Instalar dependências
RUN pip install --no-cache-dir -e .

# Copiar resto do código
COPY . .

# Expor porta
EXPOSE 8000

# Comando para executar
CMD ["uvicorn", "src.server:app", "--host", "0.0.0.0", "--port", "8000"]