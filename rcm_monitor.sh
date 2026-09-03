#!/bin/bash
# RCM Self-Healing Service Monitor
# Checks if vital RCM services are running and restarts them if they are dead.

check_and_start() {
    SERVICE=$1
    if ! systemctl is-active --quiet $SERVICE; then
        echo "$(date) - Service $SERVICE is dead. Attempting to start..." >> /var/log/rcm_monitor.log
        systemctl start $SERVICE
    fi
}

check_and_start "rcm-queue-collector.service"
# Can add other services here like asterisk.service if needed
