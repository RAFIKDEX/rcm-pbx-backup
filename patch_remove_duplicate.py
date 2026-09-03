with open('/root/RCM_7021/templates/base.html', 'r') as f:
    lines = f.readlines()

with open('/root/RCM_7021/templates/base.html', 'w') as f:
    skip = False
    for i, line in enumerate(lines):
        if "System Cleanup" in line and 'href="/cleanup/"' in line:
            # We skip this line and the previous one if it contains <li
            pass
        elif "<li" in line and i+1 < len(lines) and "System Cleanup" in lines[i+1]:
            # Skip the <li> wrapper
            pass
        else:
            f.write(line)
