import os
import json
import sqlite3
import shutil
import subprocess
from abc import ABC, abstractmethod
from datetime import datetime

class StorageProvider(ABC):
    def __init__(self, provider_id, config):
        self.provider_id = provider_id
        self.config = config
        self.last_error = None

    @abstractmethod
    def connect(self):
        """Establish/Verify connection to the storage. Returns True/False."""
        pass

    @abstractmethod
    def test_write(self):
        """Test write permissions. Returns True/False."""
        pass

    @abstractmethod
    def upload_file(self, local_path, relative_external_path):
        """Upload a single file. Returns (success_bool, external_path_or_id, error_msg)"""
        pass

    @abstractmethod
    def delete_file(self, external_path_or_id):
        """Delete a file from external storage."""
        pass
        
    @abstractmethod
    def get_capacity(self):
        """Return (total_bytes, used_bytes, free_bytes)"""
        pass
        
    def _update_status(self, status, error=None):
        conn = sqlite3.connect("/root/RCM_7021/rcm_7021.db")
        c = conn.cursor()
        c.execute("UPDATE external_storage_providers SET status=?, last_error=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", 
                  (status, str(error) if error else "", self.provider_id))
        conn.commit()
        conn.close()

class NASStorageProvider(StorageProvider):
    def __init__(self, provider_id, config):
        super().__init__(provider_id, config)
        self.mount_point = f"/mnt/rcm_external_storage/provider_{self.provider_id}"
        self.protocol = self.config.get('protocol', 'smb') # smb or nfs
        self.server = self.config.get('server', '')
        self.share = self.config.get('share', '')
        self.username = self.config.get('username', '')
        self.password = self.config.get('password', '')
        self.base_folder = self.config.get('base_folder', 'RCM').strip('/')
        
    def _is_mounted(self):
        if not os.path.ismount(self.mount_point):
            return False
        return True

    def connect(self):
        os.makedirs(self.mount_point, exist_ok=True)
        if self._is_mounted():
            self._update_status('Connected')
            return True
            
        try:
            # Clean up share path (handle backslashes and redundant server IP)
            clean_share = self.share.replace('\\', '/').strip('/')
            if clean_share.startswith(self.server):
                clean_share = clean_share[len(self.server):].strip('/')
                
            if self.protocol == 'smb':
                server_share = f"//{self.server}/{clean_share}"
                
                # Decrypt the password before mounting!
                import sys
                if '/root/RCM_7021' not in sys.path:
                    sys.path.append('/root/RCM_7021')
                import crypto_helper
                
                actual_password = crypto_helper.decrypt_secret(self.password) if self.password else ""
                
                cmd = ['sudo', '/usr/local/bin/rcm_mount_helper.sh', 'mount_cifs', server_share, self.mount_point, self.username, actual_password]
            elif self.protocol == 'nfs':
                server_share = f"{self.server}:{clean_share}"
                cmd = ['sudo', '/usr/local/bin/rcm_mount_helper.sh', 'mount_nfs', server_share, self.mount_point]
            else:
                raise ValueError("Unsupported protocol")

            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise Exception(result.stderr)
                
            self._update_status('Connected')
            return True
        except Exception as e:
            self.last_error = str(e)
            self._update_status('Error', self.last_error)
            return False

    def test_write(self):
        if not self.connect():
            return False
        test_file = os.path.join(self.mount_point, self.base_folder, '.rcm_test_write')
        try:
            os.makedirs(os.path.dirname(test_file), exist_ok=True)
            with open(test_file, 'w') as f:
                f.write('test')
            os.remove(test_file)
            return True
        except Exception as e:
            self.last_error = str(e)
            self._update_status('Error', self.last_error)
            return False

    def upload_file(self, local_path, relative_external_path):
        if not self.connect():
            return False, None, "Failed to connect to NAS"
            
        try:
            dest_path = os.path.join(self.mount_point, self.base_folder, relative_external_path)
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            shutil.copyfile(local_path, dest_path)
            # Verify size
            if os.path.getsize(local_path) != os.path.getsize(dest_path):
                os.remove(dest_path)
                return False, None, "File size mismatch after copy"
            return True, dest_path, None
        except Exception as e:
            return False, None, str(e)

    def delete_file(self, external_path):
        if not self.connect():
            return False
        try:
            if os.path.exists(external_path):
                os.remove(external_path)
            return True
        except:
            return False

    def get_capacity(self):
        if not self.connect():
            return 0, 0, 0
        try:
            total, used, free = shutil.disk_usage(self.mount_point)
            return total, used, free
        except:
            return 0, 0, 0


class GoogleDriveStorageProvider(NASStorageProvider):
    # This now uses rclone via FUSE mount for stability and ease of use.
    def __init__(self, provider_id, config):
        super().__init__(provider_id, config)
        self.rclone_config = self.config.get('credentials_json') # User pastes rclone.conf contents here
        self.remote_name = self.config.get('folder_id', 'drive') # Name of remote in the conf
        if not self.remote_name: self.remote_name = 'drive'
        self.config_path = f"/etc/rclone_provider_{self.provider_id}.conf"

    def connect(self):
        try:
            # Write config file
            with open(self.config_path, 'w') as f:
                f.write(self.rclone_config)
            os.chmod(self.config_path, 0o600)
            
            os.makedirs(self.mount_point, exist_ok=True)
            
            # Check if already mounted
            if os.path.ismount(self.mount_point):
                self._update_status('Connected')
                return True
                
            cmd = ['sudo', '/usr/local/bin/rcm_mount_helper.sh', 'mount_rclone', self.config_path, f"{self.remote_name}:", self.mount_point]
            subprocess.run(cmd)
            
            import time
            time.sleep(2) # Wait for FUSE mount
            
            if os.path.ismount(self.mount_point):
                self._update_status('Connected')
                return True
            else:
                self.last_error = "Failed to mount rclone"
                self._update_status('Error', self.last_error)
                return False
        except Exception as e:
            self.last_error = str(e)
            self._update_status('Error', self.last_error)
            return False

class OldGoogleDriveStorageProvider(StorageProvider):
    # Relies on google-auth, google-auth-oauthlib, google-api-python-client
    def __init__(self, provider_id, config):
        super().__init__(provider_id, config)
        self.credentials_json = self.config.get('credentials_json') # OAuth access_token & refresh_token
        self.folder_id = self.config.get('folder_id', 'root')
        self.service = None

    def _build_service(self):
        if self.service: return True
        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
            if not self.credentials_json:
                raise Exception("Missing OAuth credentials")
                
            creds = Credentials.from_authorized_user_info(json.loads(self.credentials_json))
            self.service = build('drive', 'v3', credentials=creds)
            return True
        except Exception as e:
            self.last_error = str(e)
            return False

    def connect(self):
        if self._build_service():
            try:
                # Test API call
                self.service.about().get(fields="user").execute()
                self._update_status('Connected')
                return True
            except Exception as e:
                self.last_error = str(e)
                self._update_status('Error', self.last_error)
                return False
        self._update_status('Error', self.last_error)
        return False

    def test_write(self):
        return self.connect() # If API works, write usually works unless quota exceeded

    def upload_file(self, local_path, relative_external_path):
        if not self.connect():
            return False, None, "Google Drive API not connected"
        try:
            from googleapiclient.http import MediaFileUpload
            file_metadata = {
                'name': os.path.basename(local_path),
                'parents': [self.folder_id] # TODO: Implement folder hierarchy creation
            }
            media = MediaFileUpload(local_path, resumable=True)
            file = self.service.files().create(body=file_metadata, media_body=media, fields='id').execute()
            return True, file.get('id'), None
        except Exception as e:
            return False, None, str(e)

    def delete_file(self, file_id):
        if not self.connect(): return False
        try:
            self.service.files().delete(fileId=file_id).execute()
            return True
        except:
            return False

    def get_capacity(self):
        if not self.connect(): return 0, 0, 0
        try:
            about = self.service.about().get(fields="storageQuota").execute()
            quota = about.get('storageQuota', {})
            total = int(quota.get('limit', 0))
            used = int(quota.get('usage', 0))
            free = total - used if total > 0 else 0
            return total, used, free
        except:
            return 0, 0, 0


def get_provider_instance(provider_id):
    conn = sqlite3.connect("/root/RCM_7021/rcm_7021.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM external_storage_providers WHERE id=?", (provider_id,))
    row = c.fetchone()
    conn.close()
    
    if not row: return None
        
    config = json.loads(row['config_json'])
    provider_type = row['provider_type']
    
    if provider_type == 'nas':
        return NASStorageProvider(provider_id, config)
    elif provider_type == 'google_drive':
        return GoogleDriveStorageProvider(provider_id, config)
    return None
