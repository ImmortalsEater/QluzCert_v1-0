#!/usr/bin/env python
import os
import sys
import django

# Adicionar o diretório do projeto ao path
project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_dir)
os.chdir(project_dir)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from django.test import Client
import re

client = Client()
response = client.get('/parceiros/')
print(f'Status: {response.status_code}')

if response.status_code == 200:
    content = response.content.decode()
    if 'Lista de Parceiros' in content:
        print('✓ Página carregou com sucesso')
        
        # Extrai parceiros únicos da página
        parceiros = re.findall(r'<td class="col-contador">([^<]+)</td>', content)
        print(f'\nParceiros encontrados: {len(set(parceiros))}')
        for p in sorted(set(parceiros)):
            print(f'  - {p}')
        
        # Salvar HTML para inspeção
        with open('scripts/parceiros_output.html', 'w', encoding='utf-8') as f:
            f.write(content)
        print('\nHTML salvo em: scripts/parceiros_output.html')
    else:
        print('✗ Página não contém "Lista de Parceiros"')
        print(content[:500])
else:
    print(f'✗ Erro HTTP {response.status_code}')
