with open("static/css/glass_theme.css", "r") as f:
    css = f.read()

missing = [".q-header-card", ".survey-card", ".q-section"]
new_lines = ",\n".join(missing) + ",\n" + ",\n".join([f"[data-theme='light'] {c}" for c in missing]) + ",\n" + ",\n".join([f"[data-theme='dark'] {c}" for c in missing])

# Instead of replacing, just inject it right before body {
css = css.replace("body {", f"{new_lines},\nbody {{")

# Also inject text colors for survey
texts = ".header-title, .survey-card-header h3, .q-section-title h2"
css = css.replace("/* Force Text Colors to Adapt */", f"/* Force Text Colors to Adapt */\n{texts} {{ color: var(--text-main) !important; }}\n.header-subtitle {{ color: var(--text-muted) !important; }}")

with open("static/css/glass_theme.css", "w") as f:
    f.write(css)

print("Fixed survey module")
