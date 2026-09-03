#!/bin/bash
set -e

# Make sure we are in noninteractive mode for apt/dpkg/debconf
export DEBIAN_FRONTEND=noninteractive

cd /usr/src/asterisk-build/asterisk-20.*/

echo "=== Step 0: Installing Build Prerequisites ==="
contrib/scripts/install_prereq install

echo "=== Step 1: Configuring Asterisk ==="
./configure --with-jansson-bundled

echo "=== Step 2: Building and Installing Asterisk ==="
make -j$(nproc)
make install
make samples
make config
ldconfig

echo "=== Step 3: Starting and Enabling Asterisk Service ==="
if systemctl --version >/dev/null 2>&1 && systemctl status >/dev/null 2>&1; then
    systemctl daemon-reload
    systemctl restart asterisk || echo "Could not restart asterisk via systemctl"
    systemctl enable asterisk || echo "Could not enable asterisk via systemctl"
else
    echo "systemd not available or not PID 1. Using service / manual start..."
    service asterisk restart || /usr/sbin/asterisk -g || echo "Could not start asterisk service"
fi

echo "=== Step 4: Installing MariaDB, Apache, and PHP ==="
apt-get update
apt-get install -y mariadb-server apache2 php php-mysql php-cli php-json php-curl php-xml libapache2-mod-php

echo "=== Step 5: Starting Services ==="
if systemctl --version >/dev/null 2>&1 && systemctl status >/dev/null 2>&1; then
    systemctl start mariadb apache2 || echo "Could not start mariadb/apache2 via systemctl"
    systemctl enable mariadb apache2 || echo "Could not enable mariadb/apache2 via systemctl"
else
    echo "systemd not available or not PID 1. Starting services via service command..."
    service mariadb start || echo "Could not start mariadb"
    service apache2 start || echo "Could not start apache2"
fi

echo "=== Step 6: Setting up Database ==="
# Ensure MariaDB is running
for i in {1..10}; do
    if mysqladmin ping --silent; then
        break
    fi
    echo "Waiting for MariaDB to start..."
    sleep 2
done

mysql -e "CREATE DATABASE IF NOT EXISTS asterisk;"
mysql -e "CREATE USER IF NOT EXISTS 'asterisk_user'@'localhost' IDENTIFIED BY 'AsteriskPass123!';"
mysql -e "GRANT ALL PRIVILEGES ON asterisk.* TO 'asterisk_user'@'localhost';"
mysql -e "FLUSH PRIVILEGES;"

echo "=== Completed successfully ==="
