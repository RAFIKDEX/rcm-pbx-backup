with open("static/css/glass_theme.css", "r") as f:
    css = f.read()

missing = [".cdr-drawer", ".cdr-drawer-header"]
new_lines = ",\n".join(missing) + ",\n" + ",\n".join([f"[data-theme='light'] {c}" for c in missing]) + ",\n" + ",\n".join([f"[data-theme='dark'] {c}" for c in missing])

css = css.replace(".studio-card, .media-hero,", f".studio-card, .media-hero,\n{new_lines},")

with open("static/css/glass_theme.css", "w") as f:
    f.write(css)

print("Added cdr-drawer to glass theme")
