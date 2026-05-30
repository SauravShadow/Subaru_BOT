FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright Chromium + system deps to a world-readable shared path
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN pip install playwright && playwright install chromium --with-deps && chmod -R o+rx /ms-playwright

# Create non-root user matching host uid=1000 (subaru) so volume mounts work
RUN groupadd -g 1000 nexus && useradd -m -u 1000 -g nexus nexus

COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh

EXPOSE 3030

ENTRYPOINT ["./entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "3030", "--reload", "--reload-dir", "/app"]
