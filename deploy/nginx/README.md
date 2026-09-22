# Host nginx reverse proxy

Production uses the existing host nginx as the stable blue/green router.
Compose binds the blue and green application slots to `127.0.0.1:8081` and
`127.0.0.1:8082`; neither is exposed publicly. A small root-owned helper checks
the inactive backend, atomically replaces nginx's upstream include, validates
the complete configuration, and gracefully reloads nginx.

The deployment account cannot write nginx configuration. Sudoers permits only
the helper's fixed slot, live-route query, and rollback commands.
The host must provide `curl`, `flock` (util-linux), `ps` (procps), `awk`,
`nginx`, and `systemctl`; the helper uses only fixed paths and slot names.

## One-time installation and legacy migration

Perform this sequence while the current single container is still serving on
`127.0.0.1:8080`. The committed initial upstream deliberately points there, so
installing the host configuration does not interrupt traffic:

```sh
sudo install -D -o root -g root -m 0644 deploy/nginx/security-headers.conf \
  /etc/nginx/snippets/physsec-security-headers.conf
sudo install -D -o root -g root -m 0644 deploy/nginx/active-upstream.conf \
  /etc/nginx/physsec-active-upstream.conf
sudo install -D -o root -g root -m 0644 deploy/nginx/physsec.org.conf \
  /etc/nginx/sites-available/physsec-org.conf
sudo install -D -o root -g root -m 0755 deploy/nginx/psv-switch-upstream \
  /usr/local/sbin/psv-switch-upstream
sudo install -d -o root -g root -m 0755 /var/lib/physsec-deploy
printf '%s\n' legacy | sudo tee /var/lib/physsec-deploy/active-slot >/dev/null
sudo chown root:root /var/lib/physsec-deploy/active-slot
sudo chmod 0644 /var/lib/physsec-deploy/active-slot
sudo install -o root -g root -m 0440 deploy/nginx/psv-deploy.sudoers \
  /etc/psv-deploy.sudoers.staged
sudo visudo -cf /etc/psv-deploy.sudoers.staged
sudo install -D -o root -g root -m 0440 /etc/psv-deploy.sudoers.staged \
  /etc/sudoers.d/psv-deploy
sudo rm /etc/psv-deploy.sudoers.staged
sudo ln -sfn /etc/nginx/sites-available/physsec-org.conf \
  /etc/nginx/sites-enabled/physsec-org.conf
sudo nginx -t
sudo systemctl reload nginx
```

Remove or disable any older virtual host claiming these domain names before
validation. Adapt certificate or distribution-specific paths in the installed
copy when necessary.

After confirming the site still works, run `./deploy/deploy.sh` as
`github_deploy_dev_physsec_org`. It starts blue on port 8081, waits for health,
switches host nginx, verifies the selected upstream through HTTPS, and only
then persists deployment state. The legacy container remains available for
in-flight old nginx workers and can be removed after the migration is observed.

The checked-in bootstrap include is installation input only. Runtime switches
modify `/etc/nginx/physsec-active-upstream.conf`, never the repository.

## Security and failure behavior

The helper and sudoers file must remain root-owned and not writable by the
deployment account. Slot names map to fixed loopback ports; arbitrary paths,
ports, and nginx directives are not accepted. The helper restores and reloads
the prior upstream if `nginx -t` or reload fails. It retains the previous live
slot in root-owned state so `deploy.sh` can roll back an interrupted first
migration as well as later blue/green switches. Its `current` command queries
the live route through nginx instead of trusting bookkeeping state, so a later
deployment can recover after an untrappable process or host failure.

Before each reload, the helper records the PIDs in the nginx worker generation
that can still use the old backend. Before reusing the inactive slot,
`deploy.sh` waits for those exact workers to exit. This protects in-flight
requests during rapid back-to-back deploys without relying on a guessed delay.

The virtual host replaces untrusted `X-Forwarded-For` input with the nginx peer
address. It adds `X-PSV-Upstream` to responses so deployment verification can
prove that host nginx selected the expected concrete port.

## Content Security Policy rollout

The CSP is intentionally `Report-Only` for launch. Test every route and form
while checking violations. Once inline code is moved to static files or
protected with nonces, remove `unsafe-inline` allowances and change the header
to `Content-Security-Policy`.

HSTS is enabled for the apex domain without `includeSubDomains`; add it only
after confirming every subdomain supports HTTPS.
