import re

with open('/root/RCM_7021/templates/ext_storage_providers.html', 'r') as f:
    content = f.read()

# Remove Card
target_card = """    <!-- Google Drive Card -->
    <div onclick="showForm('gdrive')" style="background: rgba(15,23,42,0.6); border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; padding: 2rem; text-align: center; cursor: pointer; transition: all 0.3s;" onmouseover="this.style.borderColor='#34d399'; this.style.transform='translateY(-5px)';" onmouseout="this.style.borderColor='rgba(255,255,255,0.1)'; this.style.transform='translateY(0)';">
        <i class="fa-brands fa-google-drive" style="font-size: 3rem; color: #34d399; margin-bottom: 1rem;"></i>
        <h3 style="color: white; margin: 0 0 10px 0;">Google Drive (rclone)</h3>
        <p style="color: #94a3b8; font-size: 0.9rem;">Backup to Google Drive using rclone config.</p>
    </div>"""

content = content.replace(target_card, "")

# Remove Form
target_form = """<!-- Google Drive Form -->
<form id="form_gdrive" method="POST" action="/external-storage/providers/add" style="display: none; background: rgba(15,23,42,0.8); padding: 2rem; border-radius: 12px; border: 1px solid #34d399; margin-bottom: 2rem; max-width: 600px;">
    <h3 style="color: #34d399; margin-top: 0;"><i class="fa-brands fa-google-drive"></i> Connect Google Drive (via rclone)</h3>
    <input type="hidden" name="provider_type" value="google_drive">
    
    <label style="display: block; color: #94a3b8; margin: 15px 0 5px;">Custom Name</label>
    <input type="text" name="name" required placeholder="e.g. IT Dept Drive" style="width: 100%; padding: 10px; background: rgba(0,0,0,0.3); color: white; border: 1px solid rgba(255,255,255,0.1); border-radius: 6px;">
    
    <label style="display: block; color: #94a3b8; margin: 15px 0 5px;">rclone.conf Content</label>
    <textarea name="credentials_json" required rows="5" placeholder="[drive]
type = drive
client_id = ...
client_secret = ...
scope = drive
token = {...}" style="width: 100%; padding: 10px; background: rgba(0,0,0,0.3); color: white; border: 1px solid rgba(255,255,255,0.1); border-radius: 6px; font-family: monospace;"></textarea>
    
    <label style="display: block; color: #94a3b8; margin: 15px 0 5px;">Remote Name (from rclone.conf)</label>
    <input type="text" name="folder_id" value="drive" required placeholder="e.g. drive" style="width: 100%; padding: 10px; background: rgba(0,0,0,0.3); color: white; border: 1px solid rgba(255,255,255,0.1); border-radius: 6px;">
    
    <div style="margin-top: 20px; display: flex; gap: 10px;">
        <button type="submit" style="background: #10b981; color: white; padding: 10px 20px; border: none; border-radius: 6px; cursor: pointer; font-weight: bold;">Connect Google Drive</button>
        <button type="button" onclick="hideForms()" style="background: rgba(255,255,255,0.1); color: white; padding: 10px 20px; border: none; border-radius: 6px; cursor: pointer;">Cancel</button>
    </div>
</form>"""

content = content.replace(target_form, "")

with open('/root/RCM_7021/templates/ext_storage_providers.html', 'w') as f:
    f.write(content)
