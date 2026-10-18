# Deployment

Production (`https://physsec.org`) and dev (`https://dev.physsec.org`) run
from two checkouts on the OCI app host, `/opt/psv-website` and
`/opt/psv-website-dev`. The host side (deploy account, checkouts, `.env`
files, systemd units, nginx virtual hosts and upstream includes, the `sudo`
rule) is provisioned by the `website` role in
[physsec-oci](https://github.com/physsec-village/physsec-oci); see its
`ansible/README.md`. This file covers the deploy itself and the GitHub side.

## How a deploy works

The deploy workflow SSHes into the host as the deploy account, updates the
checkout (fast-forward to `main` for production; a fresh checkout of the
selected branch for dev), and runs `deploy/deploy.sh`, which:

1. refuses to run unless an enabled nginx config includes the checkout's
   `PSV_UPSTREAM_FILE`, so a host whose vhost predates blue/green cannot lose
   traffic;
2. determines the active colour (`blue` or `green`) from the running
   containers;
3. builds the idle colour, applies pending store migrations, starts it, and
   waits for its compose health check;
4. writes `server 127.0.0.1:<port>;` for the new colour into the upstream
   include, runs `sudo -n nginx -t`, and gracefully reloads nginx;
5. waits for the pre-reload nginx workers to finish their in-flight requests
   (bounded by `PSV_DRAIN_TIMEOUT`, default 60 s), then stops the old colour.

Runs are serialized per checkout with `flock` on `.deploy.lock`, and steps 4
and 5 are serialized across production and dev, which share nginx, with a
lock next to the upstream includes. The include is replaced atomically. If an
old worker has not started shutting down by the drain deadline, nginx rejected
the reload, so the deploy restores the include and fails. If a run is
interrupted with both colours running, the next run first converges nginx on
the colour named in the include (if it is healthy) or reverts to the other.
If step 3, 4 or 5 fails, the previous include is restored and the active colour
keeps serving. There is no separate rollback step: re-deploying the previous
commit is itself a zero-downtime switch. Migrations are not rolled back, so
each must stay compatible with the release that is still serving.

A host still running the pre-blue/green single `app` container is migrated
by the first deploy: it starts `green`, switches nginx, then retires `app`.
If that deploy is interrupted, the next one finishes it first.

## GitHub

The workflow runs on pushes to every branch, and a workflow file on a branch
can be edited by anyone who can push that branch. Two settings stop such an
edit from deploying to production directly (but see the caveat below):

1. **Environment-scoped secrets.** Create GitHub Environments named
   `production` and `dev`, and put all deployment secrets on them rather than
   on the repository: `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`, `DEPLOY_PATH`.
   Remove the repository-level copies. Jobs only receive an Environment's
   secrets when they select it.

   ```text
   DEPLOY_PATH  production: /opt/psv-website   dev: /opt/psv-website-dev
   ```

2. **Production branch policy.** In the `production` Environment's
   **Deployment branches and tags**, choose **Selected branches and tags** and
   add only `main`, so GitHub refuses a `production` job from any other ref
   regardless of the workflow file.

Create a repository variable `DEV_BRANCH` naming the branch dev should track.
To retarget dev, change it, or dispatch the workflow from another branch with
`environment=dev`; the dev checkout is reset to the fetched branch, so
rebased branches deploy cleanly.

**Caveat: push access to any branch is effectively production access.** The
`dev` Environment accepts every branch, so anyone who can push a branch can
edit the workflow there to run arbitrary commands with the dev SSH key. That
key logs in to the same host account as production, which can reach the
production checkout and containers. This is acceptable only while everyone
with push access is also trusted with production. A separate account is not
enough to change that: the `docker` group is root-equivalent and reaches the
production containers, so dev-only access needs a separate host or rootless
Docker.
