filepath = "/etc/asterisk/extensions.conf"

with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

content = content.replace("\r\n", "\n")
lines = content.splitlines()

includes_to_move = [
    "#include extensions_gui.conf",
    "#include context_exten.conf",
    "#include extensions.context.conf",
    "#include rcm_outbound_routes.conf",
    "#include rcm_ring_groups.conf"
]

filtered_lines = []
for line in lines:
    if line.strip() in includes_to_move:
        continue
    filtered_lines.append(line)

new_content = "\n".join(filtered_lines) + "\n\n; --- Moved dynamic includes to the end ---\n" + "\n".join(includes_to_move) + "\n"

with open(filepath, "w", encoding="utf-8") as f:
    f.write(new_content)

print("Moved includes successfully!")
