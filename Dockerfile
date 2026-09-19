FROM node:22-bookworm-slim AS console
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY web ./web
COPY scripts/build-web.mjs ./scripts/build-web.mjs
RUN npm run build

FROM python:3.13-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN useradd --create-home --uid 10001 flowpilot
COPY requirements.lock pyproject.toml alembic.ini ./
COPY src ./src
COPY migrations ./migrations
COPY examples ./examples
RUN pip install --no-cache-dir -r requirements.lock && pip install --no-cache-dir --no-deps -e . && pip install --no-cache-dir "psycopg[binary]==3.3.5"
COPY --from=console /build/web/dist ./web/dist
RUN mkdir -p /app/var && chown -R flowpilot:flowpilot /app
USER 10001
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "flowpilot.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
