import re

with open('/root/RCM_7021/storage_providers.py', 'r') as f:
    content = f.read()

content = content.replace("shutil.copy2(local_path, dest_path)", "shutil.copyfile(local_path, dest_path)")

with open('/root/RCM_7021/storage_providers.py', 'w') as f:
    f.write(content)
