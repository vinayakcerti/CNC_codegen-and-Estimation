# Deploying CNC Plan & Process Pro (tester phase)

Target shape: one small VPS · nginx serves the React build and proxies
`/api` to uvicorn · CadQuery runs inside the `cnc-cadquery` conda env
(same OCCT rule as dev) · testers sign in with a username + password
(nginx basic auth) · updates ship with one command.

## Files here

| File | Purpose |
|---|---|
| `setup-server.sh` | one-shot bootstrap of a fresh Ubuntu 24.04 VPS |
| `cnc-api.service` | systemd unit for the FastAPI engine |
| `nginx-cnc.conf` | site config: static frontend + /api proxy + password gate |
| `deploy.sh` | pull + rebuild + restart + health check |

## Quick start

```bash
# on the fresh server, as root:
export REPO_URL="https://github.com/vinayakcerti/CNC_codegen-and-Estimation.git"
export BRANCH="v4-web-ui"
curl -fsSL https://raw.githubusercontent.com/vinayakcerti/CNC_codegen-and-Estimation/v4-web-ui/deploy/setup-server.sh -o setup.sh
bash setup.sh
```

Then HTTPS (uses the free `<ip>.sslip.io` name printed by setup, or your domain):

```bash
apt-get install -y certbot python3-certbot-nginx
certbot --nginx -d <the-server-name> --agree-tos -m you@example.com --redirect
```

Tester accounts:

```bash
htpasswd /etc/nginx/.htpasswd_cnc ramesh        # add/prompt for password
htpasswd -D /etc/nginx/.htpasswd_cnc ramesh     # remove
```

Ship an update (from your PC):

```bash
git push origin v4-web-ui
ssh root@SERVER 'bash /home/cnc/app/deploy/deploy.sh'
```

## Notes / gotchas

- **Private repo?** Use a GitHub fine-grained PAT (read-only, this repo) in
  REPO_URL: `https://<token>@github.com/...`, or add the server's deploy key.
- The sample STEP card needs `test_samples/` on the server (it is
  gitignored). Copy your reference part once:
  `scp "test_samples/3100171001_01 SLIDE BASE-1812 ( FOR TOOL LOADER ).STEP" root@SERVER:/home/cnc/app/test_samples/`
- Analysis is a synchronous ~90–120 s request by design for now; nginx
  timeouts are set to 300 s. The job queue is the first post-tester upgrade.
- Basic auth protects the API too (same server block) — nobody can hit
  `/api/*` without credentials.
- Resize path: this setup moves to a bigger droplet with a snapshot +
  resize, no config changes.
