with open("static/css/glass_theme.css", "r") as f:
    css = f.read()

# Add text color force for pbx_operation_log
texts = ".log-table td, .diff-row, .change-item, .change-setting"
css = css.replace("/* Force Text Colors to Adapt */", f"/* Force Text Colors to Adapt */\n{texts} {{ color: var(--text-main) !important; }}")

with open("static/css/glass_theme.css", "w") as f:
    f.write(css)

print("Fixed log glass")
