import re

filepath = "/root/RCM_7021/app.py"
with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

target = r"""@app.route\('/logout'\)
def logout\(\):"""

replacement = """@app.route('/forgot-password')
def forgot_password():
    flash("Password reset is not configured. Please contact the system administrator.", "info")
    return redirect(url_for('login'))

@app.route('/logout')
def logout():"""

if "def forgot_password" not in content:
    content = re.sub(target, replacement, content)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
