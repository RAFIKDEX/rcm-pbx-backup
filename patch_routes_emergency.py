with open('/root/RCM_7021/cleanup_routes.py', 'r') as f:
    content = f.read()

target = """        schedule_time = data.get('schedule_time', '03:00')
        schedule_type = data.get('schedule_type', 'daily')
        
        cursor.execute('''
            UPDATE cleanup_auto_config 
            SET enabled=?, rules_json=?, schedule_time=?, schedule_type=?
            WHERE id=1
        ''', (enabled, rules_json, schedule_time, schedule_type))"""

replacement = """        schedule_time = data.get('schedule_time', '03:00')
        schedule_type = data.get('schedule_type', 'daily')
        
        disk_trigger_enabled = data.get('disk_trigger_enabled', 0)
        disk_trigger_percent = data.get('disk_trigger_percent', 90)
        disk_target_percent = data.get('disk_target_percent', 75)
        
        cursor.execute('''
            UPDATE cleanup_auto_config 
            SET enabled=?, rules_json=?, schedule_time=?, schedule_type=?,
                disk_trigger_enabled=?, disk_trigger_percent=?, disk_target_percent=?
            WHERE id=1
        ''', (enabled, rules_json, schedule_time, schedule_type, disk_trigger_enabled, disk_trigger_percent, disk_target_percent))"""

content = content.replace(target, replacement)

target2 = """row = {'enabled': 0, 'schedule_type': 'daily', 'schedule_time': '03:00', 'rules_json': '{}'}"""
replacement2 = """row = {'enabled': 0, 'schedule_type': 'daily', 'schedule_time': '03:00', 'rules_json': '{}', 'disk_trigger_enabled': 0, 'disk_trigger_percent': 90, 'disk_target_percent': 75}"""
content = content.replace(target2, replacement2)

with open('/root/RCM_7021/cleanup_routes.py', 'w') as f:
    f.write(content)
