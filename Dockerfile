FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/.hf-cache \
    PORT=7860

WORKDIR /app

# CPU-only PyTorch first: the default Linux wheel bundles CUDA (~2 GB) that this app never uses.
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt .
RUN pip install -r requirements.txt

# Bake the embedding model and reranker into the image, so a cold start doesn't download ~200 MB.
RUN python -c "from sentence_transformers import SentenceTransformer, CrossEncoder; \
SentenceTransformer('BAAI/bge-small-en-v1.5'); CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')"

COPY . .

# Don't run as root. (Hugging Face Spaces also expects uid 1000.)
RUN useradd -m -u 1000 app && chown -R app /app
USER app

EXPOSE 7860
CMD ["sh", "docker-entrypoint.sh"]
