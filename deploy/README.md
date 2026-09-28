# Deployment Runbook

One-time host and GitHub setup for the blue/green deploy script and the two
environments (production at `https://physsec.org` from `/opt/psv-website`, dev
at `https://dev.physsec.org` from `/opt/psv-website-dev`). Run the host
commands as an administrator with root access; `DEPLOY_USER` is the
unprivileged account that GitHub Actions logs in as and that owns the
checkouts.

## How a deploy works

`deploy/deploy.sh` runs in a checkout and:

1. determines the active colour (`blue` or `green`) from the running
   containers;
2. builds and starts the idle colour and waits for its compose health check;
3. writes `server 127.0.0.1:<port>;` for the new colour into the nginx include
   named by `PSV_UPSTREAM_FILE`, runs `sudo -n nginx -t`, and runs
   `sudo -n systemctl reload nginx` (a graceful reload; existing requests
   finish on the old workers);
4. stops the old colour after a short grace period.

If step 2 or 3 fails, the previous include is restored and the active colour
keeps serving. There is no separate rollback step: re-deploying the previous
commit is itself a zero-downtime switch.

## Shared host prerequisites (once per host)

Create the upstream include directory, owned by the deploy account so the
script can rewrite the includes without root:

```bash
sudo install -d -m 0755 -o DEPLOY_USER -g DEPLOY_USER /etc/nginx/psv-upstreams
```

Install the exact `sudo` rule that lets the deploy account validate and reload
nginx (edit `DEPLOY_USER` in the file first):

```bash
visudo -cf deploy/sudoers/psv-deploy
sudo install -m 0440 deploy/sudoers/psv-deploy /etc/sudoers.d/psv-deploy
sudo -u DEPLOY_USER sudo -n /usr/sbin/nginx -t
```

Install the shared security-header snippet:

```bash
sudo install -D -m 0644 deploy/nginx/security-headers.conf \
  /etc/nginx/snippets/physsec-security-headers.conf
```

## Production: migrating from the single-service layout

The production checkout already runs the old single `app` service on
`127.0.0.1:8080`. The first blue/green deploy handles this without downtime:
it starts `green` on `127.0.0.1:8082`, switches nginx, then retires the legacy
`app` container.

1. In `/opt/psv-website/.env` add:

   ```dotenv
   PSV_UPSTREAM_FILE=/etc/nginx/psv-upstreams/production.conf
   ```

   The Compose defaults (`psv-website`, ports 8080/8082) already match
   production, so nothing else is needed.

2. Seed the include with the port the legacy container is serving on, then
   install the updated virtual host, which now proxies to the
   `psv_production` upstream:

   ```bash
   sudo -u DEPLOY_USER sh -c 'echo "server 127.0.0.1:8080;" > /etc/nginx/psv-upstreams/production.conf'
   sudo install -D -m 0644 deploy/nginx/physsec.org.conf \
     /etc/nginx/sites-available/physsec-org.conf
   sudo nginx -t && sudo systemctl reload nginx
   ```

3. Install the updated unit (its `ExecStop` now covers both colours):

   ```bash
   sudo install -m 0644 psv-website.service /etc/systemd/system/psv-website.service
   sudo systemctl daemon-reload
   ```

4. Trigger a deploy (push to `main` or dispatch the workflow). Watch for
   `Retiring legacy single-service container.` in the log; afterwards
   `docker compose --profile blue --profile green ps` should show only `green`.

## Dev checkout

Clone the repository to `/opt/psv-website-dev` owned by the deploy account:

```bash
sudo git clone git@github.com:physsec-village/physsec-org.git /opt/psv-website-dev
sudo chown -R DEPLOY_USER:DEPLOY_USER /opt/psv-website-dev
sudo -u DEPLOY_USER mkdir -p /opt/psv-website-dev/data/media
```

Create `/opt/psv-website-dev/.env` from `.env.example` with the dev values:

```dotenv
COMPOSE_PROJECT_NAME=psv-website-dev
PSV_IMAGE=psv-website-dev
PSV_BLUE_PORT=8081
PSV_GREEN_PORT=8083
PSV_UPSTREAM_FILE=/etc/nginx/psv-upstreams/dev.conf
TURNSTILE_ALLOWED_HOSTNAMES=dev.physsec.org
STORE_PUBLIC_ORIGIN=https://dev.physsec.org
```

Compose still sets `APP_ENV=production`, so the Turnstile keys are mandatory
and `dev.physsec.org` must be added to the Cloudflare Turnstile widget's
allowed hostnames. If `STORE_ENABLED` is ever true on dev, `DATABASE_URL` must
point at a separate non-production database.

Seed the dev include, confirm the dev certificate exists, and install the dev
virtual host:

```bash
sudo -u DEPLOY_USER sh -c 'echo "server 127.0.0.1:8081;" > /etc/nginx/psv-upstreams/dev.conf'
sudo test -f /etc/nginx/host-certs/dev.physsec.org.cert.pem
sudo test -f /etc/nginx/host-certs/dev.physsec.org.key.pem
sudo install -D -m 0644 deploy/nginx/dev.physsec.org.conf \
  /etc/nginx/sites-available/dev-physsec-org.conf
sudo ln -sfn /etc/nginx/sites-available/dev-physsec-org.conf \
  /etc/nginx/sites-enabled/dev-physsec-org.conf
sudo nginx -t && sudo systemctl reload nginx
```

nginx will return 502 for `dev.physsec.org` until the first deploy starts
blue on 8081. Install and start the dev service, which runs the deploy script:

```bash
sudo install -m 0644 psv-website-dev.service /etc/systemd/system/psv-website-dev.service
sudo systemctl daemon-reload
sudo systemctl enable --now psv-website-dev.service
```

## GitHub

Create GitHub Environments named `production` and `dev`. Add an Environment
secret named `DEPLOY_PATH` to each and remove any repository-level
`DEPLOY_PATH`:

```text
production: /opt/psv-website
dev: /opt/psv-website-dev
```

Keep `VPS_HOST`, `VPS_USER`, and `VPS_SSH_KEY` as repository secrets. Create a
repository variable named `DEV_BRANCH` with the branch that dev should track.

Pushes to `main` deploy production. Pushes to `DEV_BRANCH` deploy dev. Manual
workflow dispatch can deploy any selected branch to dev; production dispatch
is accepted only from `main`.

## Retargeting dev

Either change the `DEV_BRANCH` repository variable, or dispatch the deploy
workflow from the desired branch with `environment=dev`. The dev checkout is
reset to the fetched branch, so rebased branches deploy cleanly.
