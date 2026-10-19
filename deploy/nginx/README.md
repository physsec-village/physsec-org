# Nginx reverse proxy

These files keep the site's reverse-proxy behavior under version control while
leaving certificates, private keys, and host-specific provisioning outside the
repository.

Both virtual hosts proxy to an `upstream` block whose single `server` line
lives in an include under `/etc/nginx/psv-upstreams/`. `deploy/deploy.sh`
rewrites that include to point at the active blue/green colour and reloads
nginx; see [`../README.md`](../README.md).

The production virtual host (`physsec.org.conf`) assumes:

- the colours listen only on `127.0.0.1:8080` (blue) and `127.0.0.1:8082`
  (green), and the active one is named in
  `/etc/nginx/psv-upstreams/production.conf`;
- the certificate and key exist at `/etc/nginx/host-certs/physsec.org.cert.pem`
  and `/etc/nginx/host-certs/physsec.org.key.pem`, covering `physsec.org` and
  `www.physsec.org`; and
- the distribution uses the conventional `/etc/nginx/sites-available` and
  `/etc/nginx/sites-enabled` layout.

The dev virtual host (`dev.physsec.org.conf`) assumes the same, with colours on
`127.0.0.1:8081` and `127.0.0.1:8083`, the include
`/etc/nginx/psv-upstreams/dev.conf`, and the certificate at
`/etc/nginx/host-certs/dev.physsec.org.{cert,key}.pem`.

Production and dev are provisioned by the `physsec-village/physsec-oci`
`ansible/roles/website` role, which installs these files from the production
checkout, along with the certificates and upstream includes, and reloads
nginx. After changing them, re-run that playbook rather than installing them
by hand; a later playbook run would overwrite manual edits.

On a host that role does not manage, adapt the paths if the host differs,
then install and validate them with:

```bash
# The deploy account must own the include so deploy.sh can rewrite it.
sudo install -d -m 0755 -o psv-deploy -g psv-deploy /etc/nginx/psv-upstreams
echo 'server 127.0.0.1:8080;' | sudo -u psv-deploy tee /etc/nginx/psv-upstreams/production.conf
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

The production virtual host redirects HTTP and `www.physsec.org` requests to
the canonical `https://physsec.org` origin. It proxies the apex domain to the
`psv_production` upstream, the loopback port on which Compose publishes the
active colour. It also replaces `X-Forwarded-For` with `$remote_addr` instead of
using `$proxy_add_x_forwarded_for`. That difference is intentional: the app
trusts nginx's forwarded address for rate limiting, so nginx must discard any
client-supplied forwarding chain.

The dev virtual host redirects HTTP to `https://dev.physsec.org`, proxies to
the `psv_dev` upstream, sends `X-Robots-Tag: noindex, nofollow`, and serves a
disallow-all `robots.txt`.

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
