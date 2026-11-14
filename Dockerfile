FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TIKTOKEN_CACHE_DIR=/opt/tiktoken
COPY requirements.lock pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.lock \
    && python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"
COPY app app
COPY scripts scripts
COPY migrations migrations
COPY alembic.ini ./
RUN pip install --no-cache-dir --no-deps . && useradd --uid 10001 --create-home ignis
USER ignis
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
