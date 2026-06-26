import os
import sys
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
os.environ.setdefault('DJANGO_SETTINGS_MODULE','core.settings')
import django
django.setup()
from core.app.services import importar_planilha_do_drive

file_url = 'https://docs.google.com/spreadsheets/d/1L-MX27Y6iwCOyd0e4FqLxZJyRFCpHIP6arYYeFIHLME/edit?gid=1382791784#gid=1382791784'
try:
    res = importar_planilha_do_drive(file_url)
    print('RESULTADO_IMPORT:', res)
except Exception as e:
    print('ERRO_SYNC:', str(e))
