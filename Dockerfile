FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml ./
COPY .streamlit/ ./.streamlit/
COPY app/ ./app/
COPY agents/ ./agents/
COPY graph/ ./graph/
COPY observability/ ./observability/
COPY servers/ ./servers/
COPY data/ ./data/

RUN python -m pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch \
    && python -m pip install --no-cache-dir ".[rag]" \
    && mkdir -p data/private_documents \
    && addgroup --system app \
    && adduser --system --ingroup app app \
    && chown -R app:app /app

USER app

EXPOSE 8501

CMD ["streamlit", "run", "app/app_new.py", "--server.address=0.0.0.0", "--server.port=8501", "--browser.gatherUsageStats=false"]
