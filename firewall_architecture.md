# Firewall Settings Implementation Architecture

## Overview
The Firewall Settings module for the RCM project was implemented to manage `nftables` network protection while avoiding disruption to existing services like Tailscale and Fail2Ban.

### 1. Database Schema
Two new tables were added to the SQLite database via `db.py`:
- `rcm_firewall_rules`: Stores logical firewall rules (IP, Subnet Mask (dotted-decimal), Direction, Protocol, Port, Action, Status, Timestamps).
- `rcm_firewall_events`: Tracks firewall actions like applying rules or bulk deletions for auditing purposes.

### 2. Privilege Helper (`rcm_firewall_helper.py`)
To prevent running the Flask application as `root`, a privileged Python script was created at `/usr/local/bin/rcm_firewall_helper.py`. 
- **Permissions:** A sudoers drop-in file (`/etc/sudoers.d/rcm-firewall`) allows the web server (`www-data`) to execute the helper via `sudo` without a password.
- **Backend:** The helper translates logical rules to `nftables` syntax.
- **Isolation:** It operates exclusively on the `inet rcm-firewall` table, hooked into the `input` and `output` chains, preventing accidental flushing of Fail2Ban or Tailscale rules.
- **Atomicity:** The helper writes the complete `nftables` configuration to a temporary file (`/tmp/rcm_nft_apply.nft`) and applies it using `nft -f`. It automatically backs up the previous state and reverts on failure.

### 3. Application Logic (`firewall_manager.py`)
This module abstracts CRUD operations and handles conversions between the dotted-decimal subnet masks presented to the user and the CIDR prefix lengths required by `nftables`.
- **Validation:** Enforces correct IP formatting, non-duplication of rules, and validates all allowed inputs.
- **Admin Lockout Prevention:** Hardcoded logic prevents dropping SSH (22) and Web (80, 443) traffic from `0.0.0.0/0.0.0.0` on inbound/all directions.
- **Security:** Invokes the sudo helper securely using `subprocess.run` with `shell=False`.

### 4. Presentation Layer
- **Routes (`app.py`):** Added the `/security` route and endpoints for adding rules, bulk deleting rules, and applying the firewall. Protected using `@require_permission('firewall', ...)`.
- **Template (`templates/security.html`):** Overwritten to provide a modern, table-driven interface for managing firewall rules. Reuses standard RCM classes, CSRF tokens, search inputs, pagination, and flash messaging logic.

## Test Results
A comprehensive test suite was written in `tests/test_firewall.py` using `pytest`. The suite covers:
- **IP/Mask Translation (`test_ip_to_cidr`):** Validates the translation from dotted-decimal subnet masks to CIDR notations, and confirms `ValueError` raises for invalid formats.
- **Validation Logic (`test_validate_rule_valid`, `test_validate_rule_invalid_fields`):** Tests proper parsing of rule properties and boundary conditions.
- **Lockout Prevention (`test_admin_lockout_prevention`):** Verifies that adding a rule to drop SSH/Web for all IPs raises an exception.
- **CRUD Operations (`test_add_and_get_rules`, `test_delete_rules`):** Ensures that the application appropriately queries and stores in the SQLite database.
- **Duplicate Prevention (`test_duplicate_rule`):** Validates that identical rules cannot be added twice.
- **Apply Flow (`test_apply_firewall`, `test_apply_firewall_failure`):** Mocks the `subprocess` to verify successful translation and handling of backend `nftables` application failures.

All tests simulate expected conditions cleanly through Pytest `monkeypatch` and an in-memory SQLite replica structure.
