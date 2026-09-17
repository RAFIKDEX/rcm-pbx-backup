with open("static/css/glass_theme.css", "r") as f:
    css = f.read()

missing = [".um-stat", ".pm-stat"]
new_lines = ",\n".join(missing) + ",\n" + ",\n".join([f"[data-theme='light'] {c}" for c in missing]) + ",\n" + ",\n".join([f"[data-theme='dark'] {c}" for c in missing])

css = css.replace(".studio-card, .media-hero,", f".studio-card, .media-hero,\n{new_lines},")

# Add text color force for them
css = css.replace(".um-modal-head h2, .um-panel, .um-control,", ".um-stat-info strong, .pm-stat-info strong, .um-modal-head h2, .um-panel, .um-control,")
css = css.replace(".cdr-timeline-title, .cdr-timeline-item p, .cdr-call-summary span {", ".um-stat-info span, .pm-stat-info span, .cdr-timeline-title, .cdr-timeline-item p, .cdr-call-summary span {")

with open("static/css/glass_theme.css", "w") as f:
    f.write(css)

print("Fixed um-stat and pm-stat")
