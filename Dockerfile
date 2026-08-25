# Stage 1: build the frontend
FROM node:18-alpine AS frontend-builder
WORKDIR /app/dashboard
COPY dashboard/package.json dashboard/package-lock.json* ./
RUN npm ci --ignore-scripts --no-audit --progress=false
COPY dashboard/ ./
RUN npm run build

# Stage 2: runtime image
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 \
    PORT=8000
WORKDIR /app

# system deps for psycopg2 and build
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    libpq-dev \
    curl \
  && rm -rf /var/lib/apt/lists/*

# copy python requirements
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# copy app source
COPY app ./app

# copy built frontend
COPY --from=frontend-builder /app/dashboard/dist ./dashboard/dist

# expose and run
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
