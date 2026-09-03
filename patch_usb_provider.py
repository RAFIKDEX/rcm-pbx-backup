with open('/root/RCM_7021/storage_providers.py', 'r') as f:
    content = f.read()

usb_class_old = """class USBStorageProvider(StorageProvider):
    def connect(self):
        # TODO: Implement local USB mount logic
        pass

    def test_write(self):
        pass

    def upload_file(self, local_path, external_path):
        pass

    def delete_file(self, external_path):
        pass

    def get_capacity(self):
        pass"""

usb_class_new = """class USBStorageProvider(StorageProvider):
    def __init__(self, provider_id, config):
        super().__init__(provider_id, config)
        self.device_path = self.config.get('device_path') # e.g. /dev/sdb1
        self.mount_point = f"/mnt/rcm_external_storage/usb_{self.provider_id}"
        self.base_folder = self.config.get('base_folder', 'RCM').strip('/')

    def _is_mounted(self):
        return os.path.ismount(self.mount_point)

    def connect(self):
        os.makedirs(self.mount_point, exist_ok=True)
        if self._is_mounted():
            self._update_status('Connected')
            return True
        try:
            cmd = ['mount', self.device_path, self.mount_point]
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
        if not self.connect(): return False
        try:
            tf = os.path.join(self.mount_point, '.test')
            with open(tf, 'w') as f: f.write('1')
            os.remove(tf)
            return True
        except:
            return False

    def upload_file(self, local_path, relative_external_path):
        if not self.connect():
            return False, None, "USB not mounted"
        try:
            dest_path = os.path.join(self.mount_point, self.base_folder, relative_external_path)
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            shutil.copy2(local_path, dest_path)
            if os.path.getsize(local_path) != os.path.getsize(dest_path):
                os.remove(dest_path)
                return False, None, "Size mismatch"
            return True, dest_path, None
        except Exception as e:
            return False, None, str(e)

    def delete_file(self, external_path):
        if not self.connect(): return False
        try:
            if os.path.exists(external_path): os.remove(external_path)
            return True
        except:
            return False

    def get_capacity(self):
        if not self.connect(): return 0,0,0
        try:
            return shutil.disk_usage(self.mount_point)
        except:
            return 0,0,0"""

content = content.replace(usb_class_old, usb_class_new)

with open('/root/RCM_7021/storage_providers.py', 'w') as f:
    f.write(content)
