#!/usr/bin/env bash
# One-shot server bootstrap for CNC Plan & Process Pro (Ubuntu 24.04).
# Run as root on a fresh 2-4 GB VPS:
#   export REPO_URL="https://github.com/vinayakcerti/CNC_codegen-and-Estimation.git"
#   export BRANCH="v4-web-ui"
#   bash setup-server.sh
set -euo pipefail

REPO_URL="${REPO_URL:?set REPO_URL}"
BRANCH="${BRANCH:-v4-web-ui}"

echo "== 1/8 base packages =="
apt-get update -y
apt-get install -y nginx git curl apache2-utils ufw

echo "== 2/8 swap (OCCT memory spikes on small boxes) =="
if [ ! -f /swapfile ]; then
  fallocate -l 4G /swapfile && chmod 600 /swapfile
  mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "== 3/8 app user + repo =="
id -u cnc &>/dev/null || useradd -m -s /bin/bash cnc
sudo -u cnc bash -c "cd ~ && { [ -d app ] || git clone --branch '$BRANCH' '$REPO_URL' app; }"

echo "== 4/8 miniforge + cnc-cadquery env (the OCCT-safe python) =="
sudo -u cnc bash -c '
  cd ~
  if [ ! -d miniforge3 ]; then
    curl -fsSL https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh -o mf.sh
    bash mf.sh -b -p ~/miniforge3 && rm mf.sh
  fi
  ~/miniforge3/bin/conda create -y -n cnc-cadquery python=3.11 || true
  ~/miniforge3/bin/conda install -y -n cnc-cadquery -c conda-forge cadquery
  ~/miniforge3/bin/conda run -n cnc-cadquery pip install fastapi uvicorn python-multipart markdown
'

echo "== 5/8 node + frontend build =="
if ! command -v node &>/dev/null; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y nodejs
fi
sudo -u cnc bash -c 'cd ~/app && npm --prefix frontend install && npm --prefix frontend run build'

echo "== 6/8 systemd service =="
cp /home/cnc/app/deploy/cnc-api.service /etc/systemd/system/cnc-api.service
systemctl daemon-reload
systemctl enable --now cnc-api

echo "== 7/8 nginx + tester password gate =="
SERVER_NAME="${SERVER_NAME:-$(curl -s ifconfig.me | tr '.' '-').sslip.io}"
sed "s/SERVER_NAME_HERE/${SERVER_NAME}/" /home/cnc/app/deploy/nginx-cnc.conf \
  > /etc/nginx/sites-available/cnc
ln -sf /etc/nginx/sites-available/cnc /etc/nginx/sites-enabled/cnc
rm -f /etc/nginx/sites-enabled/default
[ -f /etc/nginx/.htpasswd_cnc ] || htpasswd -bc /etc/nginx/.htpasswd_cnc tester1 ChangeMe123!
nginx -t && systemctl reload nginx

echo "== 8/8 firewall =="
ufw allow OpenSSH && ufw allow 'Nginx Full' && ufw --force enable

echo ""
echo "DONE. App:   http://${SERVER_NAME}   (user tester1 / ChangeMe123! - CHANGE IT)"
echo "HTTPS next:  apt-get install -y certbot python3-certbot-nginx && certbot --nginx -d ${SERVER_NAME}"
echo "Add tester:  htpasswd /etc/nginx/.htpasswd_cnc <username>"
