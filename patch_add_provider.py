import re

filepath = "/root/RCM_7021/external_storage_routes.py"
with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

target = r"""    if provider_type == 'nas':
        config\['protocol'\] = request\.form\.get\('protocol', 'smb'\)
        config\['server'\] = request\.form\.get\('server'\)
        config\['share'\] = request\.form\.get\('share'\)
        config\['username'\] = request\.form\.get\('username', ''\)
        config\['password'\] = request\.form\.get\('password', ''\)
        config\['base_folder'\] = request\.form\.get\('base_folder', 'RCM'\)"""

replacement = """    import sys
    sys.path.append('/root/RCM_7021')
    import crypto_helper
    
    if provider_type == 'nas':
        config['protocol'] = request.form.get('protocol', 'smb')
        config['server'] = request.form.get('server')
        config['share'] = request.form.get('share')
        config['username'] = request.form.get('username', '')
        
        raw_password = request.form.get('password', '')
        config['password'] = crypto_helper.encrypt_secret(raw_password)
        
        config['base_folder'] = request.form.get('base_folder', 'RCM')"""

content = re.sub(target, replacement, content)
with open(filepath, "w", encoding="utf-8") as f:
    f.write(content)
