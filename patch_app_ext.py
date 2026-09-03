with open('/root/RCM_7021/app.py', 'r') as f:
    content = f.read()

target = "from cleanup_routes import cleanup_bp\napp.register_blueprint(cleanup_bp)"

replacement = """from cleanup_routes import cleanup_bp
app.register_blueprint(cleanup_bp)

try:
    from external_storage_routes import ext_storage_bp
    app.register_blueprint(ext_storage_bp)
except Exception as e:
    print(f"Error registering external storage blueprint: {e}")"""

if target in content:
    content = content.replace(target, replacement)
    with open('/root/RCM_7021/app.py', 'w') as f:
        f.write(content)
    print("Patched successfully")
else:
    print("Target not found")
