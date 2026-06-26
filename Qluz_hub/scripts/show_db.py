import os, sys
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
os.environ.setdefault('DJANGO_SETTINGS_MODULE','core.settings')
import django
django.setup()
from core.app.models import PlanilhaRegistro
print('COUNT:', PlanilhaRegistro.objects.count())
for r in PlanilhaRegistro.objects.all()[:20]:
    print('-', r.id, r.cliente or '<sem cliente>', r.email or '<sem email>', r.valor_comissao or 0, r.data_registro)
