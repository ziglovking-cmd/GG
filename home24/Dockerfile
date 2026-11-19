FROM node:20-bookworm-slim AS web
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM python:3.12-slim AS bot
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY bot ./bot
COPY data ./data
COPY .env.example ./

FROM node:20-bookworm-slim
WORKDIR /app
RUN apt-get update \
  && apt-get install -y --no-install-recommends python3 python3-pip ca-certificates \
  && rm -rf /var/lib/apt/lists/*
COPY --from=web /app/public ./public
COPY --from=web /app/.next/standalone ./
COPY --from=web /app/.next/static ./.next/static
COPY requirements.txt ./
RUN pip install --no-cache-dir --break-system-packages -r requirements.txt
COPY bot ./bot
COPY data ./data
COPY docker/start.sh ./start.sh
RUN chmod +x ./start.sh
ENV NODE_ENV=production
ENV PORT=43147
ENV HOSTNAME=0.0.0.0
EXPOSE 43147
CMD ["./start.sh"]
