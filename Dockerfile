FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/app/data/backend HF_HOME=/app/data/models
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
RUN useradd --create-home appuser && mkdir -p /app/data && chown appuser:appuser /app/data
COPY --chown=appuser:appuser backend ./backend
COPY --chown=appuser:appuser frontend ./frontend
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"
CMD ["uvicorn", "backend.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
