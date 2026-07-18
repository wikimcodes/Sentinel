# Sentinel — single-service image: Python API + built React UI at one URL.
# Stage 1 builds the UI; stage 2 runs the stdlib server that serves ui/dist + /api.

# ---- stage 1: build the React UI ----
FROM node:20-slim AS ui
WORKDIR /ui
COPY ui/package*.json ./
RUN npm ci
COPY ui/ ./
RUN npm run build

# ---- stage 2: python runtime ----
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
COPY --from=ui /ui/dist ./ui/dist
ENV HOST=0.0.0.0 PORT=8787
EXPOSE 8787
CMD ["python", "server/app.py"]
