import os, sys
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
os.environ.setdefault('DJANGO_SETTINGS_MODULE','core.settings')
import django
django.setup()
from django.test import Client
c = Client()
resp = c.get('/')
print('STATUS:', resp.status_code)
# Decodifica e imprime o HTML completo
content = resp.content.decode('utf-8')
print(content)
