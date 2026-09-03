import re

with open('templates/queue_stats.html', 'r') as f:
    content = f.read()

with open('/tmp/queue_stats_styles.css', 'r') as f:
    old_styles = f.read()

new_content = re.sub(r'<style>.*?</style>', old_styles, content, flags=re.DOTALL)

with open('templates/queue_stats.html', 'w') as f:
    f.write(new_content)

print("Restored old CSS.")
