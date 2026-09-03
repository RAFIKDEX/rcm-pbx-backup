import re

content = open('/etc/asterisk/extensions_gui.conf', 'r').read()

# Let's split by section headers [section_name]
sections = {}
current_sec = None
current_lines = []

for line in content.splitlines():
    m = re.match(r'^\[([^\]]+)\]', line.strip())
    if m:
        if current_sec:
            sections[current_sec] = current_lines
        current_sec = m.group(1)
        current_lines = [line]
    else:
        if current_sec:
            current_lines.append(line)
        else:
            if 'header' not in sections:
                sections['header'] = []
            sections['header'].append(line)

if current_sec:
    sections[current_sec] = current_lines

# Group sections by feature
ivr_sects = {}
ann_sects = {}
pickup_sects = {}
ring_sects = {}
queue_sects = {}
paging_sects = {}
speed_sects = {}
feature_sects = {}
other_sects = {}

for sec_name, lines in sections.items():
    if sec_name == 'header':
        continue
    if sec_name.startswith('ivr-'):
        ivr_sects[sec_name] = lines
    elif sec_name.startswith('ann-'):
        ann_sects[sec_name] = lines
    elif sec_name.startswith('pickup-'):
        pickup_sects[sec_name] = lines
    elif sec_name == 'rcm-ring-groups':
        ring_sects[sec_name] = lines
    elif sec_name.startswith('queue-') or sec_name.startswith('rcm-queue-'):
        queue_sects[sec_name] = lines
    elif sec_name == 'rcm-paging-intercom':
        paging_sects[sec_name] = lines
    elif sec_name == 'speed-dials':
        speed_sects[sec_name] = lines
    elif sec_name == 'queue-feature-codes':
        queue_sects[sec_name] = lines
    else:
        other_sects[sec_name] = lines

# Process [internal] context
internal_lines = other_sects.get('internal', [])
basic_internal = []
ivr_internal = []
ann_internal = []
ring_internal = []
queue_internal = []
paging_internal = []
speed_internal = []

for line in internal_lines:
    if line.strip().startswith('[internal]'):
        basic_internal.append(line)
        continue
    stripped = line.strip()
    if 'Goto(ivr-' in stripped:
        ivr_internal.append(line)
    elif 'Goto(ann-' in stripped:
        ann_internal.append(line)
    elif 'Goto(rcm-ring-groups' in stripped:
        ring_internal.append(line)
    elif 'Goto(queue' in stripped or 'queue-feature-codes' in stripped or 'rcm-queue-' in stripped:
        queue_internal.append(line)
    elif 'Goto(rcm-paging-intercom' in stripped:
        paging_internal.append(line)
    elif 'speed-dials' in stripped:
        speed_internal.append(line)
    elif 'rcm-queue-routes' in stripped or 'rcm-queue-features' in stripped:
        queue_internal.append(line)
    else:
        basic_internal.append(line)

# Write extensions.ivr.gui.conf
ivr_content = ""
if ivr_internal:
    ivr_content += "[internal](+)\n" + "\n".join(ivr_internal) + "\n\n"
for sname, slines in ivr_sects.items():
    ivr_content += "\n".join(slines) + "\n\n"
open('/etc/asterisk/extensions.ivr.gui.conf', 'w').write(ivr_content)

# Write extensions.announcement.gui.conf
ann_content = ""
if ann_internal:
    ann_content += "[internal](+)\n" + "\n".join(ann_internal) + "\n\n"
for sname, slines in ann_sects.items():
    ann_content += "\n".join(slines) + "\n\n"
open('/etc/asterisk/extensions.announcement.gui.conf', 'w').write(ann_content)

# Write extensions.pickup_groups.gui.conf
pickup_content = ""
for sname, slines in pickup_sects.items():
    pickup_content += "\n".join(slines) + "\n\n"
open('/etc/asterisk/extensions.pickup_groups.gui.conf', 'w').write(pickup_content)

# Write extensions.ringgroup.gui.conf
ring_content = ""
if ring_internal:
    ring_content += "[internal](+)\n" + "\n".join(ring_internal) + "\n\n"
for sname, slines in ring_sects.items():
    ring_content += "\n".join(slines) + "\n\n"
open('/etc/asterisk/extensions.ringgroup.gui.conf', 'w').write(ring_content)

# Write extensions.queue.gui.conf
queue_content = ""
if queue_internal:
    queue_content += "[internal](+)\n" + "\n".join(queue_internal) + "\n\n"
for sname, slines in queue_sects.items():
    queue_content += "\n".join(slines) + "\n\n"
open('/etc/asterisk/extensions.queue.gui.conf', 'w').write(queue_content)

# Write extensions.paging.gui.conf
paging_content = ""
if paging_internal:
    paging_content += "[internal](+)\n" + "\n".join(paging_internal) + "\n\n"
for sname, slines in paging_sects.items():
    paging_content += "\n".join(slines) + "\n\n"
open('/etc/asterisk/extensions.paging.gui.conf', 'w').write(paging_content)

# Write extensions.speed_dial.gui.conf
speed_content = ""
if speed_internal:
    speed_content += "[internal](+)\n" + "\n".join(speed_internal) + "\n\n"
for sname, slines in speed_sects.items():
    speed_content += "\n".join(slines) + "\n\n"
open('/etc/asterisk/extensions.speed_dial.gui.conf', 'w').write(speed_content)

# Create empty extensions.feature_codes.gui.conf
open('/etc/asterisk/extensions.feature_codes.gui.conf', 'w').write("; Feature Codes Configuration\n")

# Rewrite extensions_gui.conf with basic extensions only
new_ext_gui = ""
if 'header' in sections:
    new_ext_gui += "\n".join(sections['header']) + "\n"
if 'globals' in other_sects:
    glines = other_sects['globals']
    new_ext_gui += "\n".join(glines) + "\n\n"
new_ext_gui += "\n".join(basic_internal) + "\n\n"
for sname, slines in other_sects.items():
    if sname in ['globals', 'internal']:
        continue
    new_ext_gui += "\n".join(slines) + "\n\n"

open('/etc/asterisk/extensions_gui.conf', 'w').write(new_ext_gui)
print("Migration completed successfully!")
