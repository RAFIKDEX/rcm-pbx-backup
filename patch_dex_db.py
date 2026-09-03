import re

filepath = "/root/RCM_7021/app.py"
with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

target = r"""app = Flask\(__name__\)
app.secret_key = os\.environ\.get\("FLASK_SECRET", os\.urandom\(24\)\) # Secure key for sessions
register_dex\(app\)"""

replacement = """app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", os.urandom(24)) # Secure key for sessions
app.config["DEX_DB_PATH"] = "/root/RCM_7021/rcm_7021.db"
register_dex(app)"""

content = re.sub(target, replacement, content)
with open(filepath, "w", encoding="utf-8") as f:
    f.write(content)
