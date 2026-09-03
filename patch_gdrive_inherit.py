with open('/root/RCM_7021/storage_providers.py', 'r') as f:
    content = f.read()

content = content.replace("class GoogleDriveStorageProvider(StorageProvider):", "class GoogleDriveStorageProvider(NASStorageProvider):")

with open('/root/RCM_7021/storage_providers.py', 'w') as f:
    f.write(content)
