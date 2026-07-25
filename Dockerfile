FROM node:22 AS frontend-builder

WORKDIR /build
COPY sau_frontend/package.json sau_frontend/package-lock.json* ./
RUN npm install
COPY sau_frontend/ ./
RUN npm run build

FROM python:3.10-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libnspr4 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 \
    libatspi2.0-0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libgbm1 libxkbcommon0 libasound2 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir -e '.[web]'

COPY . .
COPY --from=frontend-builder /build/dist ./sau_frontend/dist

RUN mkdir -p /app/team_data /app/cookies \
    && playwright install --with-deps chromium-headless-shell

EXPOSE 5409
CMD ["python", "team_web.py"]
