with open("static/css/glass_theme.css", "r") as f:
    css = f.read()

target = "/* Force Text Colors to Adapt */\n"
new_classes = ".um-table td, .pm-table td, .dex-table td, .dex-model-name strong, .dex-capacity strong, .dex-history-row, .dex-notes, .dex-check-label, .dex-compact-select, .modal-content, .dex-card, .dex-page-head h1, .dex-section-title h2, "
css = css.replace(target, target + new_classes)

with open("static/css/glass_theme.css", "w") as f:
    f.write(css)

print("Added text color forces")
