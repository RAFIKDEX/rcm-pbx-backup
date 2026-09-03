#!/bin/bash
set -e

# Make sure we are in noninteractive mode
export DEBIAN_FRONTEND=noninteractive

echo "=== Step 1: Installing ODBC Packages ==="
apt-get install -y unixodbc unixodbc-dev odbc-mariadb

echo "=== Step 2: Locating MariaDB ODBC Driver ==="
DRIVER_PATH=$(dpkg -L odbc-mariadb 2>/dev/null | grep 'libmaodbc.so' | head -n 1)
if [ -z "$DRIVER_PATH" ]; then
    DRIVER_PATH="/usr/lib/x86_64-linux-gnu/odbc/libmaodbc.so"
fi
echo "Using Driver Path: $DRIVER_PATH"

echo "=== Step 3: Configuring /etc/odbcinst.ini ==="
cat <<EOF > /etc/odbcinst.ini
[MariaDB]
Description = ODBC for MariaDB
Driver      = $DRIVER_PATH
Setup       = $DRIVER_PATH
FileUsage   = 1
EOF

echo "=== Step 4: Configuring /etc/odbc.ini ==="
cat <<EOF > /etc/odbc.ini
[asterisk-connector]
Description = MySQL connection to 'asterisk' database
Driver      = MariaDB
Database    = asterisk
Server      = localhost
User        = asterisk_user
Password    = AsteriskPass123!
Port        = 3306
EOF

echo "=== Step 5: Configuring Asterisk ODBC ==="
cat <<EOF > /etc/asterisk/res_odbc.conf
[asterisk]
enabled => yes
dsn => asterisk-connector
username => asterisk_user
password => AsteriskPass123!
pre-connect => yes
EOF

cat <<EOF > /etc/asterisk/extconfig.conf
[settings]
ps_endpoints => odbc,asterisk
ps_auths => odbc,asterisk
ps_aors => odbc,asterisk
ps_registrations => odbc,asterisk
EOF

echo "=== Step 6: Creating Database Tables ==="
mysql asterisk -e "
CREATE TABLE IF NOT EXISTS ps_endpoints (
    id varchar(40) NOT NULL,
    transport varchar(40) DEFAULT NULL,
    aors varchar(200) DEFAULT NULL,
    auth varchar(40) DEFAULT NULL,
    context varchar(40) DEFAULT NULL,
    disallow varchar(200) DEFAULT NULL,
    allow varchar(200) DEFAULT NULL,
    PRIMARY KEY (id)
);
CREATE TABLE IF NOT EXISTS ps_auths (
    id varchar(40) NOT NULL,
    auth_type varchar(40) DEFAULT 'userpass',
    password varchar(80) DEFAULT NULL,
    username varchar(80) DEFAULT NULL,
    PRIMARY KEY (id)
);
CREATE TABLE IF NOT EXISTS ps_aors (
    id varchar(40) NOT NULL,
    max_contacts int(11) DEFAULT '1',
    PRIMARY KEY (id)
);
"

echo "=== Step 7: Restarting Asterisk ==="
if systemctl --version >/dev/null 2>&1 && systemctl status >/dev/null 2>&1; then
    systemctl restart asterisk || echo "Could not restart asterisk via systemctl"
else
    echo "systemd not available or not PID 1. Restarting via service/manual..."
    service asterisk restart || asterisk -rx "core restart now" || echo "Could not restart asterisk service"
fi

echo "=== Completed successfully ==="
