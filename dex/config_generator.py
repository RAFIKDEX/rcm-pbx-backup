import hashlib
import grp
import os
import re
import tempfile
import socket
import xml.etree.ElementTree as ET
from pathlib import Path

from .constants import PROVISION_ROOT
from .drivers import UnsupportedOperation
from .validators import normalize_mac, safe_filename


class ConfigGenerationError(ValueError):
    pass


class FanvilFiberMeConfigGenerator:
    """Generate the verified minimal partial configuration grammar.

    The generator intentionally emits only managed fields.  It never loads or
    rewrites the 39KB export; unrecognised phone settings therefore remain on
    the phone exactly as they are.
    """

    HEADER = "<<VOIP CONFIG FILE>>Version:2.0000000000"

    def __init__(self, engine, repository, pbx_db, root=PROVISION_ROOT):
        self.engine = engine
        self.repository = repository
        self.pbx_db = pbx_db
        self.root = Path(root)

    def _extension(self, extension):
        from .rcm_data import get_extension
        record = get_extension(str(extension))
        if not record or not int(record.get("enabled", 0)):
            raise ConfigGenerationError("Selected extension is not an enabled RCM extension.")
        return record

    def _ldap(self, config):
        config = dict(config)
        # LDAP enable/disable is controlled explicitly by DEX Config. Never
        # silently re-enable it from the legacy RCM LDAP table.
        if not config.get("ldap_enabled"):
            return config
        if not config.get("ldap_use_rcm_settings"):
            return config
        from .rcm_data import get_ldap_settings
        values = get_ldap_settings()
        if not values:
            raise ConfigGenerationError("RCM LDAP settings are not available.")
        config.update({
            "ldap_enabled": 1,
            "ldap_base": values.get("base_dn") or "",
            "ldap_username": values.get("username") or "",
            "ldap_password": values.get("password") or "",
        })
        return config

    def render(self, device, config=None):
        model = device
        if not model.get("provisionable") or model.get("sip_account_count") is None:
            raise ConfigGenerationError("Model is not provisionable with verified account capability.")
        config = self._ldap(config or self.repository.get_config())
        accounts = device.get("accounts") or []
        if len(accounts) != int(model["sip_account_count"]):
            raise ConfigGenerationError("Device account assignments do not match the model capability.")
        lines = [self.HEADER, "", "<SIP CONFIG MODULE>", "", "--SIP Line List--  :"]
        import db
        try:
            sip_port = int((db.get_pbx_settings().get("sip_settings") or {}).get("udp_port") or 5060)
        except Exception:
            sip_port = 5060
        for account in accounts:
            if not account.get("enabled"):
                continue
            extension = self._extension(account.get("extension"))
            lines.extend(self.engine.render_account_lines(
                account["account_index"], extension["ext"],
                config.get("provisioning_ip") or "", sip_port,
                extension.get("secret") or "", extension.get("name") or extension["ext"],
            ))
        lines.extend(["", "<PHONE FEATURE MODULE>", "--DateTime Config--:", f"Enable SNTP        :{1 if config.get('sntp_enabled') else 0}"])
        if config.get("sntp_enabled") and config.get("primary_ntp"):
            lines.append(f"SNTP Server        :{config['primary_ntp']}")
        if config.get("sntp_enabled") and config.get("secondary_ntp"):
            lines.append(f"Second SNTP Server :{config['secondary_ntp']}")
        if config.get("sntp_enabled") and config.get("timezone"):
            lines.append(f"Time Zone          :{config['timezone']}")
        if config.get("sntp_enabled") and config.get("timezone_name"):
            lines.append(f"Time Zone Name     :{config['timezone_name']}")
        date_display_lines = []
        if config.get("date_format") not in (None, ""):
            date_display_lines.append(f"Date Display Style :{config['date_format']}")
        if config.get("time_format") not in (None, ""):
            date_display_lines.append(f"Time Display Style :{config['time_format']}")
        if config.get("date_separator") not in (None, ""):
            date_display_lines.append(f"Date Separator     :{config['date_separator']}")
        if date_display_lines:
            lines.append("--DateTime Display--:")
            lines.extend(date_display_lines)

        ldap = config
        if ldap.get("ldap_enabled"):
            lines.extend(["", "--LDAP Config--    :"])
            pairs = [
                ("LDAP1 Title", ldap.get("ldap_title", "FCM")),
                ("LDAP1 Server", ldap.get("ldap_server", "")),
                ("LDAP1 port", ldap.get("ldap_port", 389)),
                ("LDAP1 Base", ldap.get("ldap_base", "")),
                ("LDAP1 Use SSL", ldap.get("ldap_use_ssl", 0)),
                ("LDAP1 Version", ldap.get("ldap_version", 3)),
                ("LDAP1 Calling Line", ldap.get("ldap_calling_line", -1)),
                ("LDAP1 Bind Line", ldap.get("ldap_bind_line", -1)),
                ("LDAP1 In Call Search", ldap.get("ldap_in_call_search", 1)),
                ("LDAP1 Out Call Search", ldap.get("ldap_out_call_search", 1)),
                ("LDAP1 Authenticate", ldap.get("ldap_authenticate", 3)),
                ("LDAP1 Username", ldap.get("ldap_username", "")),
                ("LDAP1 Password", ldap.get("ldap_password", "")),
                ("LDAP1 Tel Attr", ldap.get("ldap_tel_attr", "telephoneNumber")),
                ("LDAP1 Mobile Attr", ldap.get("ldap_mobile_attr", "mobile")),
                ("LDAP1 Other Attr", ldap.get("ldap_other_attr", "other")),
                ("LDAP1 Name Attr", ldap.get("ldap_name_attr", "cn sn ou")),
                ("LDAP1 Sort Attr", ldap.get("ldap_sort_attr", "cn")),
                ("LDAP1 Displayname", ldap.get("ldap_displayname", "cn")),
                ("LDAP1 Number Filter", ldap.get("ldap_number_filter", "(|(telephoneNumber=%)(mobile=%)(other=%))")),
                ("LDAP1 Name Filter", ldap.get("ldap_name_filter", "(|(cn=%)(sn=%))")),
                ("LDAP1 Max Hits", ldap.get("ldap_max_hits", 50)),
            ]
            for key, value in pairs:
                if value not in (None, ""):
                    lines.append(f"{key:<24}:{value}")

        if config.get("mmi_username") or config.get("mmi_password"):
            lines.extend(["", "<MMI CONFIG MODULE>", "--MMI Account--    :"])
            if config.get("mmi_username"):
                lines.append(f"Account1 Name               :{config['mmi_username']}")
            if config.get("mmi_password"):
                lines.append(f"Account1 Password           :{config['mmi_password']}")

        blf_keys = device.get("blf_keys") or []
        rendered_keys = []
        if blf_keys:
            if not model.get("blf_mapping_verified"):
                raise ConfigGenerationError("BLF mapping is not verified for this model.")
            for key in blf_keys:
                if not key.get("enabled"):
                    # An unassigned/disabled physical key is intentionally
                    # omitted from a partial file so the phone's existing key
                    # programming remains untouched.
                    continue
                render_key = dict(key)
                if render_key.get("semantic_type") == "BLF":
                    monitored_extension = self._extension(render_key.get("value"))
                    # Fanvil/FiberMe BLF syntax uses the monitored extension,
                    # the sending SIP account, and the verified directed
                    # pickup suffix.  Account 1 and ``bc`` are the tested
                    # defaults when the administrator leaves those fields
                    # empty.  The driver adds the literal ``/b`` prefix;
                    # therefore the stored suffix is ``c`` to produce the
                    # verified wire value ``/bc``.
                    render_key["account_index"] = render_key.get("account_index") or 1
                    render_key["pickup"] = render_key.get("pickup") or "c"
                    render_key["title"] = render_key.get("title") or monitored_extension.get("name") or str(render_key.get("value"))
                rendered = self.engine.render_blf_lines(render_key)
                if isinstance(rendered, UnsupportedOperation):
                    raise ConfigGenerationError(rendered.reason)
                rendered_keys.extend(rendered)

        # Verified user-supplied SoftDSS mapping for the LDAP contacts
        # shortcut.  It is intentionally emitted as a managed partial block;
        # all other DSS and desktop softkey values remain untouched.
        lines.extend(["", "<DSSKEY CONFIG MODULE>"])
        if rendered_keys:
            lines.extend(["--Sidekey Config1--:"])
            lines.extend(rendered_keys)
        lines.extend([
            "--SoftDss Config-- :",
            "Fkey1 Type               :3",
            "Fkey1 Value              :F_LDAPCONTACTS:1",
            "Fkey1 Title              :Contact",
            "Fkey1 ICON               :Green",
        ])
        lines.extend([
            "",
            "<PHONE FEATURE MODULE>",
            "--Softkey Config-- :",
            "Softkey Mode       :1",
            "SoftKey Exit Style :2",
            "Desktop Softkey    :history;dss1;dnd;menu;",
        ])

        try:
            # The verified FiberMe/Fanvil partial-file evidence is ASCII.
            # Reject non-ASCII display names explicitly instead of leaking a
            # Python codec traceback through the form.
            return ("\r\n".join(lines) + "\r\n").encode("ascii", "strict")
        except UnicodeEncodeError as exc:
            raise ConfigGenerationError("The verified phone configuration format accepts ASCII only; use Latin characters for the display name.") from exc

    def validate(self, data, normalized_mac):
        if not data.startswith((self.HEADER + "\r\n").encode("ascii")):
            raise ConfigGenerationError("Invalid DEX configuration header.")
        if b"{{" in data or b"}}" in data:
            raise ConfigGenerationError("Unresolved template placeholder detected.")
        if b"\n" in data.replace(b"\r\n", b""):
            raise ConfigGenerationError("Configuration must use CRLF line endings.")
        if re.search(rb"(?im)^\s*(SIP\d+\s+Register\s+Pswd|LDAP1\s+Password|Account1\s+Password)\s*:\s*$", data):
            raise ConfigGenerationError("Required secret value is empty.")
        expected = f"{normalize_mac(normalized_mac)}.cfg".encode("ascii")
        if not expected:
            raise ConfigGenerationError("Invalid MAC filename.")
        return {"valid": True, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}

    def publish(self, device, data):
        normalized = normalize_mac(device["normalized_mac"])
        filename = self.engine.expected_filename(normalized)
        self.root.mkdir(mode=0o750, parents=True, exist_ok=True)
        if self.root.is_symlink():
            raise ConfigGenerationError("Provisioning directory may not be a symlink.")
        self._ensure_publish_permissions(self.root, writable=True)
        final_path = self.root / filename
        if final_path.parent != self.root:
            raise ConfigGenerationError("Unsafe publication path.")
        archive_root = self.root.parent / (self.root.name + "-archive")
        archive_root.mkdir(mode=0o750, parents=True, exist_ok=True)
        self._ensure_publish_permissions(archive_root, writable=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{filename}.", suffix=".tmp", dir=str(self.root))
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o640)
            # Apache/Nginx reads through the provisioning directory's group.
            # Preserve that group on every atomic replacement; otherwise a
            # root-run Flask process would publish a root:root file that the
            # phone correctly rejects with HTTP 403.
            try:
                directory_stat = os.stat(self.root)
                if os.geteuid() == 0:
                    os.chown(temporary, 0, directory_stat.st_gid)
            except OSError as exc:
                raise ConfigGenerationError("Could not set the provisioning file group safely.") from exc
            if final_path.exists() and final_path.is_symlink():
                raise ConfigGenerationError("Refusing to replace a symlinked configuration file.")
            if final_path.exists():
                archive = archive_root / f"{filename}.{hashlib.sha256(data).hexdigest()[:12]}"
                # Archives can outlive the process that created them.  Make
                # an existing archive writable by the DEX publication group
                # before opening it for replacement, otherwise a root-created
                # 0640 root:root file causes Errno 13 under www-data.
                if archive.exists():
                    try:
                        archive_stat = os.stat(archive)
                        if os.geteuid() == 0:
                            archive_group = os.stat(archive_root).st_gid
                            os.chown(archive, 0, archive_group)
                            os.chmod(archive, 0o660)
                        elif archive_stat.st_uid == os.geteuid():
                            os.chmod(archive, 0o660)
                    except OSError as exc:
                        raise ConfigGenerationError("Could not normalize DEX archive permissions.") from exc
                with open(final_path, "rb") as old:
                    old_data = old.read()
                if old_data != data:
                    with open(archive, "wb") as backup:
                        backup.write(old_data)
                    try:
                        if os.geteuid() == 0:
                            archive_group = os.stat(archive_root).st_gid
                            os.chown(archive, 0, archive_group)
                            os.chmod(archive, 0o660)
                        elif os.stat(archive).st_uid == os.geteuid():
                            os.chmod(archive, 0o660)
                    except OSError as exc:
                        raise ConfigGenerationError("Could not set DEX archive permissions safely.") from exc
            os.replace(temporary, final_path)
            return {"path": str(final_path), "filename": filename, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        finally:
            try:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            except OSError:
                pass

    def _ensure_publish_permissions(self, path, writable=False):
        """Keep the DEX-owned publication directories usable by the app.

        The Apache account and the RCM application use the controlled
        ``www-data`` group in this deployment.  Existing directories created
        manually with an unrelated group must not make atomic tempfile
        creation fail.  No parent directory is changed.
        """
        # Custom roots are used by tests and controlled maintenance jobs.  Do
        # not change their ownership merely because the application is running
        # as root; only the production DEX publication tree is normalized.
        production_root = Path(PROVISION_ROOT).resolve()
        try:
            controlled_path = Path(path).resolve()
        except OSError:
            return
        if os.geteuid() != 0 or controlled_path != production_root and controlled_path != production_root.parent / (production_root.name + "-archive"):
            return
        try:
            group_id = grp.getgrnam("www-data").gr_gid
            os.chown(path, 0, group_id)
            os.chmod(path, 0o770 if writable else 0o750)
        except (KeyError, OSError) as exc:
            raise ConfigGenerationError("DEX provisioning directory permissions are not usable.") from exc


class GrandstreamXmlConfigGenerator(FanvilFiberMeConfigGenerator):
    """Render the small alias XML payload used by GRP260x and GXV33xx."""

    def render(self, device, config=None, include_assignments=True):
        model = str(device.get("detected_model") or device.get("model_name") or "").upper()
        if include_assignments and (not device.get("provisionable") or device.get("sip_account_count") is None):
            raise ConfigGenerationError("Model is not provisionable with verified account capability.")
        accounts = device.get("accounts") or [] if include_assignments else []
        if include_assignments and len(accounts) != int(device["sip_account_count"]):
            raise ConfigGenerationError("Device account assignments do not match the model capability.")
        config = self._ldap(config or self.repository.get_config())
        try:
            import db
            sip_port = int((db.get_pbx_settings().get("sip_settings") or {}).get("udp_port") or 5060)
        except Exception:
            sip_port = 5060
        root = ET.Element("gs_provision", {"version": "1"})
        xml_config = ET.SubElement(root, "config", {"version": "2"})

        def item(name, value):
            ET.SubElement(xml_config, "item", {"name": name}).text = str(value)

        def parts_item(name, parts):
            element = ET.SubElement(xml_config, "item", {"name": name})
            for part_name, value in parts:
                ET.SubElement(element, "part", {"name": part_name}).text = str(value)

        for account in accounts:
            if not account.get("enabled"):
                continue
            extension = self._extension(account.get("extension"))
            index = int(account["account_index"])
            prefix = f"account.{index}"
            display_name = extension.get("name") or extension["ext"]
            if model.startswith("GRP"):
                # GRP2602P firmware 1.0.7.66 applies the exported grouped
                # account grammar.  The flattened alias spelling downloads
                # successfully but does not reliably apply Account 1.
                parts_item(prefix, (("enable", "Yes"), ("name", display_name)))
                parts_item(f"{prefix}.sip", (
                    ("authenticateIncomingInvite", "No"),
                    ("publishForPresence", "No"),
                    ("registration", "Yes"),
                    ("registerExpiration", "60"),
                    ("userid", extension["ext"]),
                    ("localPort", str(sip_port)),
                    ("transport", "UDP"),
                    ("registrationFailureRetryWaitTime", "20"),
                    ("accountDisplay", "User Name"),
                    ("listeningMode", "Transport_Only"),
                    ("specialFeature", "Standard"),
                ))
                parts_item(f"{prefix}.sip.subscriber", (
                    ("userid", extension["ext"]),
                    ("password", extension.get("secret") or ""),
                ))
                parts_item(f"{prefix}.sip.server.1", (("address", config.get("provisioning_ip") or ""),))
            else:
                # The alias spelling differs between the GXV and GRP
                # templates; retain the established GXV flat grammar.
                auth_key = f"{prefix}.sip.subscriber.userId" if model.startswith("GXV") else f"{prefix}.sip.subscriber.userid"
                values = (
                    (f"{prefix}.enable", "Yes"),
                    (f"{prefix}.name", display_name),
                    (f"{prefix}.sip.server.1.address", config.get("provisioning_ip") or ""),
                    (f"{prefix}.sip.userid", extension["ext"]),
                    (auth_key, extension["ext"]),
                    (f"{prefix}.sip.subscriber.password", extension.get("secret") or ""),
                    (f"{prefix}.sip.subscriber.name", display_name),
                    (f"{prefix}.sip.registration", "Yes"),
                    (f"{prefix}.sip.registerExpiration", "60"),
                    (f"{prefix}.sip.registrationFailureRetryWaitTime", "20"),
                    (f"{prefix}.sip.localPort", str(sip_port)),
                    (f"{prefix}.sip.transport", "UDP"),
                )
                for name, value in values:
                    item(name, value)

        for key in (device.get("blf_keys") or []) if include_assignments else []:
            if not key.get("enabled"):
                continue
            render_key = dict(key)
            if render_key.get("semantic_type") == "BLF":
                monitored_extension = self._extension(render_key.get("value"))
                current_title = str(render_key.get("title") or "").strip()
                monitored_value = str(render_key.get("value") or "").strip()
                # A blank title (or a title copied from the monitored number)
                # should show the extension's display name on the phone key.
                # Preserve an explicitly customized label.
                if not current_title or current_title == monitored_value:
                    render_key["title"] = monitored_extension.get("name") or monitored_value
            rendered = self.engine.render_blf_parts(render_key)
            if isinstance(rendered, UnsupportedOperation):
                raise ConfigGenerationError(rendered.reason)
            parts_item(rendered["name"], rendered["parts"])

        # These keys are present in the supplied GRP260x alias template and
        # map the DEX-wide NTP/LDAP settings without changing unrelated phone
        # preferences. LDAP is intentionally omitted when disabled so an
        # existing phone address book is preserved.
        if config.get("sntp_enabled"):
            ntp_parts = []
            if config.get("primary_ntp"):
                ntp_parts.append(("1", config["primary_ntp"]))
            if config.get("secondary_ntp"):
                ntp_parts.append(("2", config["secondary_ntp"]))
            if ntp_parts:
                parts_item("dateTime.ntp.server", ntp_parts)
            item("dateTime.ntp.updateInterval", "1440")
            item("dateTime.override.dhcp.allowOption42", "No")

        # GRP firmware uses the grouped dateTime grammar from the supplied
        # Grandstream template.  DEX currently exposes the deployed UTC+3
        # default as 12 / UTC+3; keep the supported choices intentionally
        # limited to Cairo (+2) and Baghdad (+3).
        timezone_value = str(config.get("timezone") or "").strip()
        timezone_name = str(config.get("timezone_name") or "").strip().upper()
        if (
            "BAGHDAD" in timezone_name
            or "IRAQ" in timezone_name
            or "UTC+3" in timezone_name
            or "UTC+03" in timezone_name
            or timezone_value in {"12", "+3", "UTC+3", "UTC+03", "ASIA/BAGHDAD"}
        ):
            grandstream_timezone = "Baghdad, Iraq"
        else:
            grandstream_timezone = "Cairo"
        parts_item("dateTime", (
            ("showOnStatusBar", "Yes"),
            ("timezone", grandstream_timezone),
        ))
        item("dateTime.override.dhcp.allowOption2", "No")
        parts_item("dateTime.format", (
            ("date", "yyyy-mm-dd"),
            ("time", "12Hour" if str(config.get("time_format") or "0") == "1" else "24Hour"),
        ))

        # The supplied GRP26xx template leaves this item commented out, but
        # it is the Grandstream alias used for the phone's web administrator
        # password.  DEX stores the value encrypted and services.py decrypts
        # it into ``mmi_password`` before generation.  Omit it when the DEX
        # setting is blank so a partial file cannot accidentally clear an
        # existing phone password.
        if config.get("mmi_password"):
            item("users.admin.password", config["mmi_password"])

        if config.get("ldap_enabled"):
            ldap_number_attributes = " ".join(
                value for value in (
                    config.get("ldap_tel_attr", "telephoneNumber"),
                    config.get("ldap_mobile_attr", "mobile"),
                    config.get("ldap_other_attr", "other"),
                ) if str(value or "").strip()
            ) or "telephoneNumber mobile other"
            ldap_values = (
                ("contact.source.priority", "Local,Remote,BSXSI,LDAPPhonebook,NETWorkSignaling"),
                ("language.inputMethod.ldap", "123"),
                ("ldap.ucmAutoConfigOnLCD.enable", "No"),
                ("ldap.protocol", "LDAP"),
                ("ldap.version", "version3" if int(config.get("ldap_version") or 3) == 3 else f"version{config.get('ldap_version')}"),
                ("ldap.server", config.get("ldap_server", "")),
                ("ldap.port", config.get("ldap_port", 389)),
                ("ldap.base", config.get("ldap_base", "")),
                ("ldap.username", config.get("ldap_username", "")),
                ("ldap.password", config.get("ldap_password", "")),
                ("ldap.ldapNumberFilter", config.get("ldap_number_filter", "")),
                ("ldap.ldapNameFilter", config.get("ldap_name_filter", "")),
                ("ldap.ldapMailFilter", config.get("ldap_mail_filter", "")),
                ("ldap.ldapPositionFilter", config.get("ldap_position_filter", "")),
                ("ldap.ldapDepartmentFilter", config.get("ldap_department_filter", "")),
                ("ldap.ldapNameAttributes", config.get("ldap_name_attr", "cn sn ou")),
                ("ldap.ldapNumberAttributes", ldap_number_attributes),
                ("ldap.ldapMailAttributes", config.get("ldap_mail_attr", "")),
                ("ldap.ldapPositionAttributes", config.get("ldap_position_attr", "")),
                ("ldap.ldapDepartmentAttributes", config.get("ldap_department_attr", "")),
                ("ldap.ldapDisplayName", config.get("ldap_displayname", "cn")),
                ("ldap.maxHits", config.get("ldap_max_hits", 50)),
                ("ldap.searchTimeout", config.get("ldap_search_timeout", 30)),
                ("ldap.sortResults", config.get("ldap_sort_results", "No")),
                ("ldap.ldapLookup", "Yes" if config.get("ldap_in_call_search") else "No"),
                ("ldap.outgoingCalls", "Yes" if config.get("ldap_out_call_search") else "No"),
                ("ldap.lookupDisplayName", config.get("ldap_lookup_display_name", "")),
                ("ldap.defaultAccount", config.get("ldap_default_account", "Default")),
                ("ldap.exactSearch.enable", "Yes" if config.get("ldap_exact_search") else "No"),
            )
            for name, value in ldap_values:
                # Emit the complete template grammar, including empty filter
                # and credential fields, so an older phone cannot retain a
                # stale LDAP value after a DEX update.
                item(name, "" if value is None else value)
        data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        try:
            ET.fromstring(data)
        except ET.ParseError as exc:
            raise ConfigGenerationError("Generated Grandstream XML is invalid.") from exc
        if b"{{" in data or b"}}" in data or b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
            raise ConfigGenerationError("Unsafe or unresolved XML content detected.")
        return data

    def validate(self, data, normalized_mac):
        try:
            root = ET.fromstring(data)
        except ET.ParseError as exc:
            raise ConfigGenerationError("Invalid Grandstream XML configuration.") from exc
        if root.tag != "gs_provision" or root.attrib.get("version") != "1":
            raise ConfigGenerationError("Invalid Grandstream provisioning root.")
        if b"{{" in data or b"}}" in data:
            raise ConfigGenerationError("Unresolved template placeholder detected.")
        for element in root.findall(".//item"):
            name = str(element.attrib.get("name") or "").lower()
            if name.endswith("password") and not str(element.text or ""):
                raise ConfigGenerationError("Required Grandstream password value is empty.")
        return {"valid": True, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}

    def publish(self, device, data):
        published = super().publish(device, data)
        normalized = normalize_mac(device["normalized_mac"])
        # Grandstream requests the extensionless MAC name first and then the
        # .xml form. Keep both aliases identical in the DEX directory.
        alias = self.root / safe_filename(f"cfg{normalized}")
        if alias != Path(published["path"]):
            self._publish_alias(alias, data)
        return published

    def _publish_alias(self, final_path, data):
        if final_path.exists() and final_path.is_symlink():
            raise ConfigGenerationError("Refusing to replace a symlinked configuration file.")
        fd, temporary = tempfile.mkstemp(prefix=f".{final_path.name}.", suffix=".tmp", dir=str(self.root))
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o640)
            try:
                directory_stat = os.stat(self.root)
                if os.geteuid() == 0:
                    os.chown(temporary, 0, directory_stat.st_gid)
            except OSError as exc:
                raise ConfigGenerationError("Could not set the provisioning file group safely.") from exc
            os.replace(temporary, final_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
