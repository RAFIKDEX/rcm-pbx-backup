with open("static/css/glass_theme.css", "r") as f:
    css = f.read()

texts = ".cdr-stat-card strong, .cdr-stat-card h3, .cdr-queue-metrics-heading, .cdr-queue-metric strong, .floating-player"
css = css.replace("/* Force Text Colors to Adapt */", f"/* Force Text Colors to Adapt */\n{texts} {{ color: var(--text-main) !important; }}")

spans = ".cdr-stat-card span, .cdr-stat-card p, .cdr-queue-metric span"
css = css.replace(".cdr-timeline-title, .cdr-timeline-item p", f"{spans}, .cdr-timeline-title, .cdr-timeline-item p")

with open("static/css/glass_theme.css", "w") as f:
    f.write(css)

print("Fixed cdr glass texts")
