import os
import re

template_dir = 'templates'
count = 0

for root, _, files in os.walk(template_dir):
    for file in files:
        if file.endswith('.html'):
            filepath = os.path.join(root, file)
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Remove inline solid background-colors (e.g. style="background-color: #1a1a1a;")
            # but keep the rest of the style string
            new_content = re.sub(r'(style="[^"]*)background-color:\s*#[0-9a-fA-F]+;?', r'\1', content)
            new_content = re.sub(r'(style="[^"]*)background:\s*#[0-9a-fA-F]+;?', r'\1', new_content)
            new_content = re.sub(r'(style="[^"]*)background:\s*white;?', r'\1', new_content)
            new_content = re.sub(r'(style="[^"]*)background:\s*black;?', r'\1', new_content)
            
            # Clean up empty style attributes
            new_content = re.sub(r'style="\s*"', '', new_content)
            
            if new_content != content:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                count += 1

print(f"Scrubbed inline backgrounds from {count} files.")
