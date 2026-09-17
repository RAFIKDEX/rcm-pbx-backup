with open("static/css/glass_theme.css", "r") as f:
    css = f.read()

missing = [".um-toolbar", ".pm-toolbar"]
new_lines = ",\n".join(missing) + ",\n" + ",\n".join([f"[data-theme='light'] {c}" for c in missing]) + ",\n" + ",\n".join([f"[data-theme='dark'] {c}" for c in missing])

css = css.replace(".studio-card, .media-hero,", f".studio-card, .media-hero,\n{new_lines},")

# Add text color force for headers
css = css.replace(".um-modal-head h2, .um-panel, .um-control,", ".um-title h1, .pm-title h1, .um-modal-head h2, .um-panel, .um-control,")
css = css.replace(".cdr-timeline-title, .cdr-timeline-item p, .cdr-call-summary span {", ".um-title p, .pm-title p, .cdr-timeline-title, .cdr-timeline-item p, .cdr-call-summary span {")

with open("static/css/glass_theme.css", "w") as f:
    f.write(css)

print("Fixed um-toolbar and pm-toolbar")
