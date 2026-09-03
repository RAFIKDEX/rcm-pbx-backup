filepath = "/etc/asterisk/features.conf"

with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

content = content.replace("\r\n", "\n")

# Replace empty [featuremap] with transfer and recording mappings
if "[featuremap]\n" in content:
    content = content.replace("[featuremap]\n", "[featuremap]\nblindxfer => ##\natxfer => *2\nautomixmon => *1\n")
elif "[featuremap]" in content:
    content = content.replace("[featuremap]", "[featuremap]\nblindxfer => ##\natxfer => *2\nautomixmon => *1\n")

with open(filepath, "w", encoding="utf-8") as f:
    f.write(content)

print("Features patch complete!")
