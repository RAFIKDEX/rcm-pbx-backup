import re

filepath = "/root/RCM_7021/app.py"
with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

target = r"""@app.before_request
def check_auth\(\):
    if app\.config\.get\('TESTING'\) and not request\.headers\.get\('X-Enforce-Security'\) and not request\.environ\.get\('enforce_security'\):
        return"""

replacement = """@app.before_request
def check_auth():
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_urlsafe(24)
    if app.config.get('TESTING') and not request.headers.get('X-Enforce-Security') and not request.environ.get('enforce_security'):
        return"""

content = re.sub(target, replacement, content)

with open(filepath, "w", encoding="utf-8") as f:
    f.write(content)
