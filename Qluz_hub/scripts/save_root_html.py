import os, sys
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
os.environ.setdefault('DJANGO_SETTINGS_MODULE','core.settings')
import django
django.setup()
from django.test import Client
c = Client()
resp = c.get('/', SERVER_NAME='localhost')
content = resp.content.decode('utf-8', errors='replace')
out_path = os.path.join(project_root, 'scripts', 'latest_dashboard.html')
with open(out_path, 'w', encoding='utf-8') as f:
    f.write(content)
print('STATUS:', resp.status_code)
print('Saved to:', out_path)
