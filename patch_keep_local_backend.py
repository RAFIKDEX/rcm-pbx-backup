# 1. Routes
with open('/root/RCM_7021/external_storage_routes.py', 'r') as f:
    content = f.read()

target = """        static_provider_id = request.form.get('static_provider_id') or None
        dynamic_order = request.form.getlist('dynamic_order[]')
        
        conn.execute("UPDATE storage_strategy SET mode=?, static_provider_id=?, dynamic_order_json=? WHERE id=1",
                     (mode, static_provider_id, json.dumps(dynamic_order)))"""

replacement = """        static_provider_id = request.form.get('static_provider_id') or None
        dynamic_order = request.form.getlist('dynamic_order[]')
        keep_local = 1 if request.form.get('keep_local') else 0
        
        conn.execute("UPDATE storage_strategy SET mode=?, static_provider_id=?, dynamic_order_json=?, keep_local=? WHERE id=1",
                     (mode, static_provider_id, json.dumps(dynamic_order), keep_local))"""

if "keep_local=?" not in content:
    content = content.replace(target, replacement)
    with open('/root/RCM_7021/external_storage_routes.py', 'w') as f:
        f.write(content)

# 2. Spooler
with open('/root/RCM_7021/storage_spooler.py', 'r') as f:
    content = f.read()

target2 = """                # Safe Delete Local
                try:
                    os.remove(local_path)
                except Exception as e:"""

replacement2 = """                # Safe Delete Local
                keep_local = strategy['keep_local'] if 'keep_local' in strategy.keys() else 0
                if not keep_local:
                    try:
                        os.remove(local_path)
                    except Exception as e:"""

if "if not keep_local:" not in content:
    content = content.replace(target2, replacement2)
    with open('/root/RCM_7021/storage_spooler.py', 'w') as f:
        f.write(content)

