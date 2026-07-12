import re

with open("app/static/js/settings.js", "r", encoding="utf-8") as f:
    text = f.read()

idx = text.find("const tmplTypes = ['request', 'available', 'upgrade', 'failed'];")
if idx != -1:
    text = text[:idx]

with open("app/static/js/settings.js", "w", encoding="utf-8") as f:
    f.write(text)
