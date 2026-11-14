FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.lock pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.lock
COPY app app
COPY scripts scripts
COPY migrations migrations
COPY alembic.ini ./
RUN pip install --no-cache-dir --no-deps . && useradd --uid 10001 --create-home ignis \
    && install -d -o ignis -g ignis /home/ignis/.cache
USER ignis
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
