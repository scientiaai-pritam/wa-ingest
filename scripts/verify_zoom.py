import re
h = open('dashboard/index.html', encoding='utf-8').read()
print('machzoom template:', 'machzoom-tmpl' in h)
print('zoombody empty in modal:', '<div id="zoombody"></div>' in h)
print('closeZoom clears:', bool(re.search(r'closeZoom\(\)\{[^}]*zoombody', h)))
oz = re.search(r'function openZoom\(\)\{[\s\S]*?\n\}', h).group(0)
print('openZoom injects from template:', 'machzoom-tmpl' in oz)
