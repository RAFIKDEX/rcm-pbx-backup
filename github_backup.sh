#!/bin/bash
cd /root/RCM_7021

echo "Syncing Asterisk configuration files..."
# Create asterisk_backup folder if it doesn't exist
mkdir -p /root/RCM_7021/asterisk_backup

# Sync /etc/asterisk to asterisk_backup, excluding large sqlite3/db files if any exist there
rsync -a --exclude='*.db' --exclude='*.sqlite3' /etc/asterisk/ /root/RCM_7021/asterisk_backup/

# Check if there are changes
if [ -n "$(git status --porcelain)" ]; then
    echo "Changes detected, backing up to GitHub..."
    git add .
    git commit -m "Auto backup $(date +'%Y-%m-%d %H:%M:%S')"
    git push origin main
    echo "Backup completed successfully."
else
    echo "No changes to backup."
fi
