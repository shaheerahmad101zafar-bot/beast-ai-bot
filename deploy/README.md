# Beast AI Production Deploy

## Local Docker stack

```bash
docker compose build
docker compose up -d
```

- API: proxied via nginx on port 80 → `beast_api:8000`
- Worker: `beast_worker` runs `run_worker.py` (scan loop + Telegram)
- PWA assets served from the API `/static`, `/manifest.json`, `/service-worker.js`

## Let's Encrypt

1. Point DNS at the host.
2. Uncomment the HTTPS server block in `nginx/conf.d/beast.conf` and set your domain.
3. Issue certs:

```bash
docker compose --profile certs run --rm certbot certonly \
  --webroot -w /var/www/certbot \
  -d your.domain \
  --email you@example.com --agree-tos --no-eff-email
docker compose restart nginx
```

## Mobile native packages

```bash
python mobile_builder.py --server-url https://your.domain
cd mobile && npm install && npx cap add android && npx cap sync
```
