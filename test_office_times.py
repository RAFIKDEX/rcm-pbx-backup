import sys
sys.path.append("/root/RCM_7021")
import db
import asterisk_helper

# Clear existing
conn = db.get_db()
cursor = conn.cursor()
cursor.execute("DELETE FROM office_time_classes")
cursor.execute("DELETE FROM office_time_rules")
conn.commit()
conn.close()

print("Saving sample classes...")

# 1. Morning Shift (enabled)
db.save_office_time_class("morning", "Morning Shift", "Morning schedule", 1, [
    {"day_of_week": "Sunday", "start_time": "04:00", "end_time": "09:00"},
    {"day_of_week": "Monday", "start_time": "08:00", "end_time": "17:00"},
    {"day_of_week": "Tuesday", "start_time": "08:00", "end_time": "17:00"}
])

# 2. Evening Shift (disabled)
db.save_office_time_class("evening", "Evening Shift", "Evening schedule", 0, [
    {"day_of_week": "Sunday", "start_time": "16:00", "end_time": "21:00"},
    {"day_of_week": "Monday", "start_time": "17:00", "end_time": "23:00"}
])

# 3. Split Shift (enabled)
db.save_office_time_class("split", "Split Shift", "Split schedule", 1, [
    {"day_of_week": "Sunday", "start_time": "09:00", "end_time": "13:00"},
    {"day_of_week": "Sunday", "start_time": "14:00", "end_time": "18:00"}
])

print("Classes saved.")
print("Retrieving all classes from DB:")
classes = db.get_office_times()
for c in classes:
    print(f"Class: {c['name']} (ID: {c['id']}, Enabled: {c['enabled']}, Desc: {c['description']})")
    for r in c['rules']:
        print(f"  Rule: {r['day_of_week']} -> {r['start_time']} - {r['end_time']}")

print("\nGenerating Asterisk dialplan...")
asterisk_helper.sync_inbound_routes_dialplan()

print("Reading generated dialplan config...")
try:
    with open("/etc/asterisk/extensions.inbound.gui.conf", "r") as f:
        lines = f.readlines()
    
    # Print lines containing office check subroutines
    in_office_section = False
    for line in lines:
        line_str = line.strip()
        if line_str.startswith("; --- Office Time Subroutines ---"):
            in_office_section = True
        elif line_str.startswith("; --- Holiday Subroutines ---"):
            in_office_section = False
        if in_office_section:
            print(line_str)
except Exception as e:
    print("Error reading dialplan config:", e)
