#!/usr/bin/env bash
# Ship an update to the server. Run on the server as root (or via ssh):
#   ssh root@SERVER 'bash /home/cnc/app/deploy/deploy.sh'
set -euo pipefail
sudo -u cnc bash -c 'cd ~/app && git pull && npm --prefix frontend install && npm --prefix frontend run build'
systemctl restart cnc-api
sleep 5
curl -sf http://127.0.0.1:8000/api/health >/dev/null && echo "DEPLOYED OK - API healthy" || {
  echo "API HEALTH CHECK FAILED - check: journalctl -u cnc-api -n 50"; exit 1; }
