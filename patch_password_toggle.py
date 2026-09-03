import re

filepath = "/root/RCM_7021/templates/ext_storage_providers.html"
with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

target = r"""                <div>
                    <label style="display: block; color: #94a3b8; margin-bottom: 5px;">Password</label>
                    <input type="password" name="password" class="form-control" autocomplete="new-password" style="width: 100%; padding: 10px; background: rgba\(0,0,0,0.2\); color: white; border: 1px solid rgba\(255,255,255,0.1\); border-radius: 6px;">
                </div>"""

replacement = """                <div>
                    <label style="display: block; color: #94a3b8; margin-bottom: 5px;">Password</label>
                    <div style="position: relative;">
                        <input type="password" id="nas_password" name="password" class="form-control" autocomplete="new-password" style="width: 100%; padding: 10px; background: rgba(0,0,0,0.2); color: white; border: 1px solid rgba(255,255,255,0.1); border-radius: 6px; padding-right: 40px;">
                        <button type="button" onclick="togglePassword()" style="position: absolute; right: 10px; top: 50%; transform: translateY(-50%); background: none; border: none; color: #94a3b8; cursor: pointer;"><i id="nas_pwd_icon" class="fa-solid fa-eye"></i></button>
                    </div>
                </div>"""

content = re.sub(target, replacement, content)

target_script = r"</script>"
replacement_script = """
function togglePassword() {
    var pwdInput = document.getElementById('nas_password');
    var pwdIcon = document.getElementById('nas_pwd_icon');
    if (pwdInput.type === "password") {
        pwdInput.type = "text";
        pwdIcon.classList.remove('fa-eye');
        pwdIcon.classList.add('fa-eye-slash');
    } else {
        pwdInput.type = "password";
        pwdIcon.classList.remove('fa-eye-slash');
        pwdIcon.classList.add('fa-eye');
    }
}
</script>"""

content = content.replace(target_script, replacement_script)

with open(filepath, "w", encoding="utf-8") as f:
    f.write(content)
