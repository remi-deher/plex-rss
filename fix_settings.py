import re

with open("app/templates/settings.html", "r", encoding="utf-8") as f:
    text = f.read()

# remove tab button
text = re.sub(r'<li class="nav-item"[^>]*>\s*<button[^>]*data-bs-target="#tab-templates"[^>]*>.*?</li>', '', text, flags=re.DOTALL)

# remove tab content inclusion
text = re.sub(r'\{% include "settings/_templates\.html" %\}', '', text)

# remove codemirror/tinymce stuff from bottom
text = re.sub(r'<link rel="stylesheet" href="https://cdnjs\.cloudflare\.com/ajax/libs/codemirror.*?</script>', '', text, flags=re.DOTALL)
text = re.sub(r'<script src="https://cdnjs\.cloudflare\.com/ajax/libs/tinymce.*?</script>', '', text, flags=re.DOTALL)
text = re.sub(r'<style>\n#tab-templates \.CodeMirror \{ height: 100% !important; font-family: var\(--bs-font-monospace\); font-size: 13px; \}\n</style>', '', text)


with open("app/templates/settings.html", "w", encoding="utf-8") as f:
    f.write(text)
