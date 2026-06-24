# Frameko — serveur MCP hébergé (SaaS, HTTP multi-tenant)
# Contexte de build : proto/
FROM python:3.13-slim

# onnxruntime (fastembed) nécessite libgomp
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dépendances d'abord (couche mise en cache tant que requirements ne change pas)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Code applicatif (le .env n'est PAS copié — voir .dockerignore ; secrets via l'environnement)
COPY . /app/

# Le modèle d'embedding est mis en cache dans un volume → pas de re-téléchargement au redémarrage
ENV FRAMEKO_MODEL_CACHE=/data/models \
    FRAMEKO_MCP_TRANSPORT=http \
    FRAMEKO_MCP_HOST=0.0.0.0 \
    FRAMEKO_MCP_PORT=8765
VOLUME ["/data/models"]
EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8765/health').status==200 else 1)"

CMD ["python", "mcp_server/server.py"]
