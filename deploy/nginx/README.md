# Nginx reverse proxy

These files keep the site's reverse-proxy behavior under version control while
leaving certificates, private keys, and host-specific provisioning outside the
repository.

The supplied virtual host assumes:

- the application listens only on `127.0.0.1:8080`;
- the host-managed certificate and key exist at
  `/etc/nginx/host-certs/physsec.org.cert.pem` and
  `/etc/nginx/host-certs/physsec.org.key.pem`, and the certificate covers both
  `physsec.org` and `www.physsec.org`; and
- the distribution uses the conventional `/etc/nginx/sites-available` and
  `/etc/nginx/sites-enabled` layout.

If the host uses different paths, update the installed copy or adapt the paths
before enabling it. Install and validate it with:

```bash
sudo install -D -m 0644 deploy/nginx/security-headers.conf \
  /etc/nginx/snippets/physsec-security-headers.conf
sudo install -D -m 0644 deploy/nginx/physsec.org.conf \
  /etc/nginx/sites-available/physsec-org.conf
sudo ln -sfn /etc/nginx/sites-available/physsec-org.conf \
  /etc/nginx/sites-enabled/physsec-org.conf
sudo nginx -t
sudo systemctl reload nginx
```

Run the reload only after `nginx -t` succeeds. Remove or disable any older
virtual host that claims these domain names so nginx does not select an
unexpected server block.

## Development site

`dev.physsec.org.conf` proxies the isolated development Compose project on
`127.0.0.1:8081`. Before enabling it, point the `dev.physsec.org` DNS record at
the VPS and provision a certificate at the paths declared in the config. Then:

```bash
sudo install -D -m 0644 deploy/nginx/dev.physsec.org.conf \
  /etc/nginx/sites-available/dev.physsec-org.conf
sudo ln -sfn /etc/nginx/sites-available/dev.physsec-org.conf \
  /etc/nginx/sites-enabled/dev.physsec-org.conf
sudo nginx -t
sudo systemctl reload nginx
```

The development deployment uses its own checkout, `.env.dev`, image names,
Compose project, media directory, loopback port, and rollback image. Do not
reuse production database, Stripe, or Turnstile secrets. At minimum,
`.env.dev` must set `TURNSTILE_ALLOWED_HOSTNAMES=dev.physsec.org` and
`STORE_PUBLIC_ORIGIN=https://dev.physsec.org`; use Turnstile test keys if the
test environment should not process real challenges. Start from the committed
`.env.dev.example` and keep the populated file only on the VPS.

The production virtual host redirects HTTP and `www.physsec.org` requests to
the canonical `https://physsec.org` origin. It proxies the apex domain to
`127.0.0.1:8080`, the concrete loopback address on which Compose publishes the
application. It also replaces `X-Forwarded-For` with `$remote_addr` instead of
using `$proxy_add_x_forwarded_for`. That difference is intentional: the app
trusts nginx's forwarded address for rate limiting, so nginx must discard any
client-supplied forwarding chain.

## Content Security Policy rollout

The CSP is intentionally `Report-Only` for launch. The current templates use
inline CSS and JavaScript and load Google Fonts, Font Awesome from cdnjs, and
Cloudflare Turnstile. Test every route and both forms while checking browser CSP
violations. Once inline code has been moved to static files (or protected with
nonces), remove the corresponding `unsafe-inline` allowances and change the
header name to `Content-Security-Policy`.

HSTS is enabled for the apex domain without `includeSubDomains`; that avoids
committing unrelated subdomains to HTTPS. Add it only after confirming every
subdomain supports HTTPS.
