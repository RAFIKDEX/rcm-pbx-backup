with open('/root/RCM_7021/storage_providers.py', 'r') as f:
    content = f.read()

# Replace NAS connect
old_nas_connect = """            if self.protocol == 'smb':
                cmd = ['mount', '-t', 'cifs', f"//{self.server}/{self.share.strip('/')}", self.mount_point]
                if self.username:
                    cmd.extend(['-o', f"username={self.username},password={self.password},dir_mode=0777,file_mode=0777"])
                else:
                    cmd.extend(['-o', 'guest,dir_mode=0777,file_mode=0777'])
            elif self.protocol == 'nfs':
                cmd = ['mount', '-t', 'nfs', f"{self.server}:{self.share}", self.mount_point]
            else:
                raise ValueError("Unsupported protocol")

            result = subprocess.run(cmd, capture_output=True, text=True)"""

new_nas_connect = """            # Clean up share path (handle backslashes and redundant server IP)
            clean_share = self.share.replace('\\\\', '/').strip('/')
            if clean_share.startswith(self.server):
                clean_share = clean_share[len(self.server):].strip('/')
                
            if self.protocol == 'smb':
                server_share = f"//{self.server}/{clean_share}"
                cmd = ['sudo', '/usr/local/bin/rcm_mount_helper.sh', 'mount_cifs', server_share, self.mount_point, self.username, self.password]
            elif self.protocol == 'nfs':
                server_share = f"{self.server}:{clean_share}"
                cmd = ['sudo', '/usr/local/bin/rcm_mount_helper.sh', 'mount_nfs', server_share, self.mount_point]
            else:
                raise ValueError("Unsupported protocol")

            result = subprocess.run(cmd, capture_output=True, text=True)"""

content = content.replace(old_nas_connect, new_nas_connect)

# Replace USB connect
old_usb_connect = """        try:
            cmd = ['mount', self.device_path, self.mount_point]
            result = subprocess.run(cmd, capture_output=True, text=True)"""

new_usb_connect = """        try:
            cmd = ['sudo', '/usr/local/bin/rcm_mount_helper.sh', 'mount_usb', self.device_path, self.mount_point]
            result = subprocess.run(cmd, capture_output=True, text=True)"""

content = content.replace(old_usb_connect, new_usb_connect)

with open('/root/RCM_7021/storage_providers.py', 'w') as f:
    f.write(content)
