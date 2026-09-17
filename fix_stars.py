import re

with open("static/css/glass_theme.css", "r") as f:
    css = f.read()

# Make stars more visible in light mode (more opaque)
css = css.replace("--star-color: rgba(15, 23, 42, 0.25);", "--star-color: rgba(15, 23, 42, 0.45);")
css = css.replace("--star-color: rgba(15, 23, 42, 0.2);", "--star-color: rgba(15, 23, 42, 0.45);")

# Increase star sizes
css = re.sub(r'(#stars\s*\{\s*width:\s*)1px(\s*;\s*height:\s*)1px', r'\g<1>2px\g<2>2px', css)
css = re.sub(r'(#stars2\s*\{\s*width:\s*)2px(\s*;\s*height:\s*)2px', r'\g<1>3px\g<2>3px', css)
css = re.sub(r'(#stars3\s*\{\s*width:\s*)3px(\s*;\s*height:\s*)3px', r'\g<1>4px\g<2>4px', css)

# Make sure after pseudoelements match
css = re.sub(r'(#stars:after\s*\{.*?width:\s*)1px(\s*;\s*height:\s*)1px', r'\g<1>2px\g<2>2px', css, flags=re.DOTALL)
css = re.sub(r'(#stars2:after\s*\{.*?width:\s*)2px(\s*;\s*height:\s*)2px', r'\g<1>3px\g<2>3px', css, flags=re.DOTALL)
css = re.sub(r'(#stars3:after\s*\{.*?width:\s*)3px(\s*;\s*height:\s*)3px', r'\g<1>4px\g<2>4px', css, flags=re.DOTALL)

with open("static/css/glass_theme.css", "w") as f:
    f.write(css)
