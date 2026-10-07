import re
h = open('dashboard/index.html', encoding='utf-8').read()
calls = re.findall(r"zoomSvg\('([^']+)'\)", h)
svg_ids = re.findall(r'<svg id="([^"]+)"', h)
print('zoom calls:', sorted(set(calls)))
print('svg ids:', sorted(set(svg_ids)))
print()
for c in sorted(set(calls)):
    print(c, '-> svg exists:', c in svg_ids)
