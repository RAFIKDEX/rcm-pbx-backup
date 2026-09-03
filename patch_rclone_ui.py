import re

with open('/root/RCM_7021/templates/ext_storage_providers.html', 'r') as f:
    content = f.read()

target = """<h3 style="color: white; margin: 0 0 10px 0;">Google Drive</h3>
        <p style="color: #94a3b8; font-size: 0.9rem;">Backup directly to a Google Account.</p>"""
replacement = """<h3 style="color: white; margin: 0 0 10px 0;">Google Drive (rclone)</h3>
        <p style="color: #94a3b8; font-size: 0.9rem;">Backup to Google Drive using rclone config.</p>"""
content = content.replace(target, replacement)

target2 = """<h3 style="color: #34d399; margin-top: 0;"><i class="fa-brands fa-google-drive"></i> Connect Google Drive</h3>"""
replacement2 = """<h3 style="color: #34d399; margin-top: 0;"><i class="fa-brands fa-google-drive"></i> Connect Google Drive (via rclone)</h3>"""
content = content.replace(target2, replacement2)

target3 = """<label style="display: block; color: #94a3b8; margin: 15px 0 5px;">Google Service Account JSON / Auth Token</label>
    <textarea name="credentials_json" required rows="5" placeholder="Paste the Google API JSON content here..." """
replacement3 = """<label style="display: block; color: #94a3b8; margin: 15px 0 5px;">rclone.conf Content</label>
    <textarea name="credentials_json" required rows="5" placeholder="[drive]\ntype = drive\nclient_id = ...\nclient_secret = ...\nscope = drive\ntoken = {...}" """
content = content.replace(target3, replacement3)

target4 = """<label style="display: block; color: #94a3b8; margin: 15px 0 5px;">Folder ID (Optional)</label>
    <input type="text" name="folder_id" placeholder="Leave blank for Root folder" """
replacement4 = """<label style="display: block; color: #94a3b8; margin: 15px 0 5px;">Remote Name (from rclone.conf)</label>
    <input type="text" name="folder_id" value="drive" required placeholder="e.g. drive" """
content = content.replace(target4, replacement4)

with open('/root/RCM_7021/templates/ext_storage_providers.html', 'w') as f:
    f.write(content)
