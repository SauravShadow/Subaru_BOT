FROM python:3.12-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt
RUN pip install --no-cache-dir --prefix=/install playwright

FROM python:3.12-slim AS runtime

WORKDIR /app

ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

COPY --from=builder /install /usr/local

RUN playwright install chromium --with-deps && chmod -R o+rx /ms-playwright

RUN groupadd -g 1000 nexus && useradd -m -u 1000 -g nexus nexus

COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh

EXPOSE 3030

ENTRYPOINT ["./entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "3030", "--reload", "--reload-dir", "/app"]
