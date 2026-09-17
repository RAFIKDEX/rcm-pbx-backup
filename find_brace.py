with open("static/css/glass_theme.css", "r") as f:
    lines = f.readlines()

open_count = 0
close_count = 0

for i, line in enumerate(lines):
    open_count += line.count('{')
    close_count += line.count('}')
    if open_count < close_count:
        print(f"Extra closing brace at line {i+1}")
        break

print(f"Final count: {open_count} open, {close_count} close")
if open_count > close_count:
    # Let's find where the unclosed block is
    stack = []
    for i, line in enumerate(lines):
        for j, char in enumerate(line):
            if char == '{':
                stack.append((i+1, line.strip()))
            elif char == '}':
                if stack:
                    stack.pop()
    for item in stack:
        print(f"Unclosed block started at line {item[0]}: {item[1]}")
