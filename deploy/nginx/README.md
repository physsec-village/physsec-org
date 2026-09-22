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

## Pull request previews

Trusted pull requests from this repository deploy to
`pr-<number>.physsec.org`. Each preview gets an exact, proxied Cloudflare CNAME
and an isolated Compose project on the `psv-previews` Docker network. A small
gateway resolves each project's network alias and listens only on
`127.0.0.1:8081`. PR numbers from 1 through 9999 are supported. Start the
gateway and install the preview virtual host once:

```bash
docker compose -f deploy/preview-gateway/docker-compose.yml up -d
sudo install -D -m 0644 deploy/nginx/previews.physsec.org.conf \
  /etc/nginx/sites-available/physsec-previews.conf
sudo install -D -m 0644 deploy/nginx/cloudflare-real-ip.conf \
  /etc/nginx/snippets/cloudflare-real-ip.conf
sudo ln -sfn /etc/nginx/sites-available/physsec-previews.conf \
  /etc/nginx/sites-enabled/physsec-previews.conf
sudo nginx -t
sudo systemctl reload nginx
```

The config expects the origin certificate at Certbot's conventional
`/etc/letsencrypt/live/physsec.org` path and that certificate must include
`*.physsec.org`. A Let's Encrypt wildcard requires DNS validation. With the DNS
records proxied, Cloudflare supplies its Universal SSL certificate to browsers
and validates the Let's Encrypt certificate at nginx when the zone uses Full
(strict) encryption.

Create a root directory and preview environment file owned by the deployment
account. Start the latter from `.env.preview.example` and use Turnstile test
keys; preview Compose forces the store off. Configure these secrets on the
`previews` GitHub Environment (or as repository secrets):

- `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`, and the existing `DEPLOY_PATH`;
- `PREVIEW_ROOT`, the absolute VPS directory for temporary git worktrees;
- `PREVIEW_ENV_FILE`, the absolute path to the host-managed environment file.

Cloudflare credentials stay on the VPS. Install the constrained helper from a
trusted `main` checkout so the deployment account cannot modify it:

```bash
sudo install -o root -g root -m 0755 deploy/physsec-preview-dns \
  /usr/local/sbin/physsec-preview-dns
sudo install -d -o root -g root -m 0700 /etc/physsec-preview
sudoedit /etc/physsec-preview/cloudflare-zone-id
sudoedit /etc/physsec-preview/cloudflare-curl.conf
sudo chmod 0600 /etc/physsec-preview/cloudflare-*
```

`cloudflare-zone-id` contains only the 32-character zone ID. The curl config
contains the API token without exposing it in a process command line:

```text
silent
show-error
fail-with-body
header = "Authorization: Bearer REPLACE_WITH_ZONE_SCOPED_TOKEN"
```

The token needs only DNS Write access to the `physsec.org` zone. Install a
sudoers rule with `sudo visudo -f /etc/sudoers.d/physsec-preview-dns`, replacing
the username if necessary:

```sudoers
github_deploy_dev_physsec_org ALL=(root) NOPASSWD: /usr/local/sbin/physsec-preview-dns *
```

Although sudo permits arguments, the root-owned helper accepts exactly two and
constructs the hostname, record type, target, and API endpoint internally. Its
only capabilities are creating/updating or deleting `pr-1.physsec.org` through
`pr-9999.physsec.org`. The GitHub runner never receives the Cloudflare token or
zone ID.

The workflow deliberately uses `pull_request_target` so its definition and
secrets come from the trusted base branch. It refuses fork PRs and only deploys
PRs whose authors are owners, members, or collaborators. The Compose definition
also comes from the trusted base checkout; PR code is used only as the image
build context. Closing a PR removes its exact DNS record, containers, media
volume, images, and worktree. The external `psv-previews` gateway network stays
in place for other and future previews.

The checked-in real-IP snippet trusts only Cloudflare's published proxy ranges
before accepting `CF-Connecting-IP`. Compare it periodically with Cloudflare's
current IPv4 and IPv6 lists, reinstall it, validate nginx, and reload when the
published ranges change.

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
