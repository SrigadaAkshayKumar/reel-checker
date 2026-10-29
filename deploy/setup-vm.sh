#!/usr/bin/env bash
# One-time setup of a fresh Ubuntu 22.04 / 24.04 VM (Oracle Cloud Always Free, or any VPS).
#   curl -fsSL https://raw.githubusercontent.com/SrigadaAkshayKumar/reel-checker/main/deploy/setup-vm.sh -o setup-vm.sh
#   less setup-vm.sh && sudo bash setup-vm.sh
# Safe to run again. See docs/deploy.md for the whole procedure.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "run with sudo"; exit 1; }
USER_NAME=${SUDO_USER:-ubuntu}
REPO=${REPO:-https://github.com/SrigadaAkshayKumar/reel-checker.git}
DIR=/home/$USER_NAME/reel-checker

echo "== packages and automatic security updates"
apt-get update -q
DEBIAN_FRONTEND=noninteractive apt-get install -yq ca-certificates curl git unattended-upgrades iptables-persistent
dpkg-reconfigure -f noninteractive unattended-upgrades

echo "== Docker"
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi
usermod -aG docker "$USER_NAME"
systemctl enable --now docker

echo "== firewall: allow HTTP/HTTPS"
# Oracle's Ubuntu images ship iptables rules that reject everything but SSH, even after the
# cloud security list allows 80/443. Insert accepts before the REJECT rule and persist them.
for spec in "tcp 80" "tcp 443" "udp 443"; do
  set -- $spec
  iptables -C INPUT -p "$1" --dport "$2" -m state --state NEW -j ACCEPT 2>/dev/null \
    || iptables -I INPUT 5 -p "$1" --dport "$2" -m state --state NEW -j ACCEPT
done
netfilter-persistent save >/dev/null

echo "== swap (small VMs)"
if [[ $(awk '/MemTotal/ {print $2}' /proc/meminfo) -lt 3000000 && ! -f /swapfile ]]; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  echo "/swapfile none swap sw 0 0" >> /etc/fstab
fi

echo "== code"
if [[ ! -d $DIR/.git ]]; then
  sudo -u "$USER_NAME" git clone "$REPO" "$DIR"
fi
if [[ ! -f $DIR/.env ]]; then
  sudo -u "$USER_NAME" cp "$DIR/.env.example" "$DIR/.env"
  chmod 600 "$DIR/.env"
fi

echo "== nightly backup at 03:30"
cat > /etc/cron.d/reel-checker-backup <<CRON
30 3 * * * $USER_NAME cd $DIR && docker compose exec -T api python run.py backup --keep 14 >> /home/$USER_NAME/reel-checker-backup.log 2>&1
CRON

cat <<DONE

Done. Next (as $USER_NAME, after logging out and in again so the docker group applies):
  cd $DIR && nano .env          # domains, ACME_EMAIL, API keys: see docs/deploy.md
  docker compose up -d --build
  deploy/smoke-test.sh \$API_DOMAIN \$APP_DOMAIN
Also allow TCP 80 and 443 (and UDP 443) in the VM's cloud firewall (Oracle: VCN security list).
DONE
