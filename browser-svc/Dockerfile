FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy

WORKDIR /app

# Tectonic — self-contained LaTeX engine for local CV compilation (no Overleaf/browser needed)
RUN curl --proto '=https' --tlsv1.2 -fsSL https://drop-sh.fullyjustified.net | sh \
    && mv tectonic /usr/local/bin/

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium --with-deps

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "9002"]
