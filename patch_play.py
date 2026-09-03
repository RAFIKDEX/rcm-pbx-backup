with open('/root/RCM_7021/app.py', 'r') as f:
    content = f.read()

target = "if provider.__class__.__name__ in ['NASStorageProvider', 'USBStorageProvider']:"
replacement = "if provider.__class__.__name__ in ['NASStorageProvider', 'USBStorageProvider', 'GoogleDriveStorageProvider']:"

content = content.replace(target, replacement)

with open('/root/RCM_7021/app.py', 'w') as f:
    f.write(content)
