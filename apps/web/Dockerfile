# Static Next.js export served by nginx, with /api proxied to the FastAPI
# service on the same origin. Same-origin keeps the session cookie simple:
# no CORS, no cross-site cookies.

FROM node:22-alpine AS build
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY . .
RUN npm run build:static

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/out /usr/share/nginx/html
EXPOSE 80
