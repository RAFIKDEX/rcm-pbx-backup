import re

with open("static/css/glass_theme.css", "r") as f:
    css = f.read()

stats = [
    ".um-stat", ".pm-stat", ".dex-stat", ".ql-stat", ".wb-stat", 
    ".directory-stat", ".res-stat", ".ldap-stat", ".analytics-stat", 
    ".survey-stat", ".cdr-stat", ".sip-stat"
]

stats_str = ",\n".join(stats) + ",\n" + ",\n".join([f"[data-theme='light'] {c}" for c in stats]) + ",\n" + ",\n".join([f"[data-theme='dark'] {c}" for c in stats])

css = css.replace(".studio-card, .media-hero,", f".studio-card, .media-hero,\n{stats_str},")

# Add text color force for their strong tags
strongs = ", ".join([f"{c} strong, {c}-info strong" for c in stats])
css = css.replace(".um-modal-head h2, .um-panel, .um-control,", f"{strongs}, .um-modal-head h2, .um-panel, .um-control,")

# Add text color force for their span tags
spans = ", ".join([f"{c} span, {c}-info span, {c} p" for c in stats])
css = css.replace(".cdr-timeline-title, .cdr-timeline-item p, .cdr-call-summary span {", f"{spans}, .cdr-timeline-title, .cdr-timeline-item p, .cdr-call-summary span {{")

with open("static/css/glass_theme.css", "w") as f:
    f.write(css)

print("Added all stats classes")
