import re

with open('/root/RCM_7021/storage_providers.py', 'r') as f:
    content = f.read()

target = """class GoogleDriveStorageProvider(StorageProvider):"""

replacement = """class GoogleDriveStorageProvider(StorageProvider):
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

class OldGoogleDriveStorageProvider(StorageProvider):"""

if "class OldGoogleDriveStorageProvider" not in content:
    content = content.replace(target, replacement)
    with open('/root/RCM_7021/storage_providers.py', 'w') as f:
        f.write(content)
