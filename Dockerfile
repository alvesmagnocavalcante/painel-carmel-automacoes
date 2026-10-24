# ==========================================
# Estágio 1: Build de dependências com UV
# ==========================================
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

# Instala dependências em um virtualenv isolado
COPY requirements.txt pyproject.toml ./
RUN uv venv /app/.venv && \
    uv pip install --no-cache -r requirements.txt

# ==========================================
# Estágio 2: Imagem final de execução
# ==========================================
FROM python:3.12-slim

WORKDIR /app

# Utilitários mínimos para saúde e certificados
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copia o ambiente virtual pré-instalado
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Copia o código da aplicação
COPY . /app

# Cria usuário não-root por segurança
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app
USER appuser

# Configuração de rede e saída de logs
ENV PYTHONUNBUFFERED=1 \
    PORTAL_HOST=0.0.0.0 \
    PORTAL_PORT=8550

EXPOSE 8550

# Verificação de integridade do container
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://127.0.0.1:8550/ || exit 1

ENTRYPOINT ["python", "main.py"]
