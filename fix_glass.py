import re

with open("static/css/glass_theme.css", "r") as f:
    css = f.read()

# Let's remove the duplicated blocks by recreating the file properly if it's messed up, or just stripping the duplicates.
# Actually, the easiest way is to rebuild the file from `stars.css` and the theme template.
