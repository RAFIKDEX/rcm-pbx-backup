import re

filepath = "/root/RCM_7021/templates/ext_storage_providers.html"
with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

# Fix the form action and add the hidden provider_type field
target = r'<form method="POST" action="/external-storage/providers/add_nas">'
replacement = '<form method="POST" action="/external-storage/providers/add">\n            <input type="hidden" name="provider_type" value="nas">'

content = content.replace(target, replacement)

with open(filepath, "w", encoding="utf-8") as f:
    f.write(content)
