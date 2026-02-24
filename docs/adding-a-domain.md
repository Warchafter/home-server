# Adding a Domain Name

This guide upgrades your server from `http://SERVER_IP:PORT` to proper
`https://service.home.yourdomain.com` URLs with automatic TLS certificates.

## 1. Buy a Domain

Cheap options:
- [Porkbun](https://porkbun.com) — `.xyz` domains ~$2/yr
- [Cloudflare Registrar](https://www.cloudflare.com/products/registrar/) — at-cost pricing

Pick whatever you like. Example: `warchafter.xyz`

## 2. Set Up Cloudflare DNS (Free)

1. Create a [Cloudflare account](https://dash.cloudflare.com/sign-up)
2. Add your domain and follow the nameserver setup
3. Add a **wildcard A record**:
   - Type: `A`
   - Name: `*.home`
   - Content: your server's LAN IP (e.g., `192.168.1.100`)
   - Proxy status: **DNS only** (gray cloud)

This makes `anything.home.yourdomain.com` resolve to your server.

## 3. Add DNS Rewrite in AdGuard Home

So devices on your LAN can resolve the domain locally:

1. Open AdGuard Home admin panel
2. Go to **Filters > DNS rewrites**
3. Add: `*.home.yourdomain.com` → `SERVER_IP`

## 4. Update `.env`

```bash
# Uncomment and fill in:
DOMAIN=yourdomain.com
ACME_EMAIL=your@email.com
```

## 5. Update the Caddyfile

In `caddy/Caddyfile`:
1. **Comment out** all port-based blocks (`:80`, `:8090`, `:8091`)
2. **Uncomment** the domain-based blocks at the bottom

Do NOT leave both active — they will conflict.

## 6. Pass Environment Variables to Caddy

In `stacks/caddy.yaml`, uncomment the `environment` block:

```yaml
environment:
  - DOMAIN=${DOMAIN}
  - ACME_EMAIL=${ACME_EMAIL}
```

## 7. Update Caddy Ports and Memory

In `stacks/caddy.yaml`, uncomment the HTTPS port:

```yaml
ports:
  - "80:80"
  - "443:443"    # <-- uncomment this
```

Also increase Caddy's memory limit for TLS certificate management:

```yaml
deploy:
  resources:
    limits:
      memory: 256m    # <-- increase from 128m
```

## 8. Apply Changes

```bash
# Recreate Caddy with new ports and environment variables
# (docker compose restart is NOT enough for port/env changes)
docker compose up -d
```

Caddy will automatically provision Let's Encrypt TLS certificates. Check logs:

```bash
docker compose logs -f caddy
```

## 9. Update Homepage

In `homepage/config/services.yaml`, update the `href` values to use your new domain names.

## 10. Update Uptime Kuma

Update your monitors to use the new URLs.

## Result

| Before | After |
|--------|-------|
| `http://192.168.1.100` | `https://dashboard.home.yourdomain.com` |
| `http://192.168.1.100:8090` | `https://status.home.yourdomain.com` |
| `http://192.168.1.100:8091` | `https://adguard.home.yourdomain.com` |
