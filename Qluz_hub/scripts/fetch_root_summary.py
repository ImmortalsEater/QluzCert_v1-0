import os, sys
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
os.environ.setdefault('DJANGO_SETTINGS_MODULE','core.settings')
import django
django.setup()
from django.test import Client
c = Client()
resp = c.get('/', SERVER_NAME='localhost')
print('STATUS:', resp.status_code)
content = resp.content.decode('utf-8', errors='replace')
lines = content.splitlines()
for i, line in enumerate(lines[:40], 1):
    print(f'{i:02}: {line}')
