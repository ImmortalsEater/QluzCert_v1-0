from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import TemplateView
from django.contrib import messages
from django.db import transaction
from django.http import JsonResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
import json
from core.app.services import importar_planilha_do_drive
from .services import save_state_to_drive
from core.app.services import salvar_no_drive_desde_db
from .models import Colaborador, AppState
from core.app.models import PlanilhaRegistro
import io
import pandas as pd
from django.http import HttpResponse


def sincronizar_drive(request):
    """
    Sincroniza parceiros e dados da planilha do Google Drive.
    O ID do arquivo fica na URL: https://docs.google.com/spreadsheets/d/ID_AQUI/edit
    """
    ID_DA_PLANILHA_DO_CLIENTE = 'https://docs.google.com/spreadsheets/d/1L-MX27Y6iwCOyd0e4FqLxZJyRFCpHIP6arYYeFIHLME/edit?gid=1382791784#gid=1382791784'

    try:
        with transaction.atomic():
            PlanilhaRegistro.objects.all().delete()
            total_importado = importar_planilha_do_drive(ID_DA_PLANILHA_DO_CLIENTE)
        messages.success(request, f"Sucesso! Banco limpo e {total_importado} parceiros sincronizados da planilha.")
    except Exception as e:
        messages.error(request, f"Erro ao acessar o Google Drive: {str(e)}")

    return redirect('dashboard')


class DashboardView(TemplateView):
    template_name = 'dashboard.html'  # Certifique-se de que o caminho está correto conforme seus TEMPLATES

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['google_columns'] = [
            {'label':'Data da Venda','field':'data_venda','class':'col-data-venda'},
            {'label':'Contador/Parceiro','field':'contador_parceiro','class':'col-contador-parceiro'},
            {'label':'Contador/Contabilidade','field':'contador_contabilidade','class':'col-contador-contabilidade'},
            {'label':'Telefone','field':'telefone1','class':'col-telefone1'},
            {'label':'Cliente','field':'cliente','class':'col-cliente'},
            {'label':'CPF/CNPJ','field':'cpf_cnpj','class':'col-cpf-cnpj'},
            {'label':'email','field':'email','class':'col-email'},
            {'label':'Telefone2','field':'telefone2','class':'col-telefone2'},
            {'label':'Tipo de Certificado','field':'tipo_certificado','class':'col-tipo-certificado'},
            {'label':'Valor da Venda (R$)','field':'valor_venda','class':'col-valor-venda'},
            {'label':'Percentual de Comissão (%)','field':'percentual_comissao','class':'col-percentual'},
            {'label':'Valor da Comissão (R$)','field':'valor_comissao','class':'col-valor-comissao'},
            {'label':'Pago_Comissao','field':'pago_comissao','class':'col-pago-comissao'},
            {'label':'Chave PIX','field':'chave_pix','class':'col-chave-pix'},
            {'label':'Data de Vencimento','field':'data_vencimento','class':'col-data-vencimento'},
            {'label':'Pago_Venda','field':'pago_venda','class':'col-pago-venda'},
            {'label':'Forma de pagamento','field':'forma_pagamento','class':'col-forma-pagamento'},
            {'label':'Banco','field':'banco','class':'col-banco'},
            {'label':'Certfificado Feito','field':'certificado_feito','class':'col-cert-feito'},
            {'label':'Venda','field':'venda','class':'col-venda'},
            {'label':'Custo do Certificado','field':'custo_certificado','class':'col-custo-cert'},
            {'label':'Valor Liquido','field':'valor_liquido','class':'col-valor-liquido'},
            {'label':'Importado em','field':'data_registro','class':'col-data-registro'},
        ]
        # Monta linhas com lista de células seguindo a ordem de google_columns
        cols = context['google_columns']
        rows = []
        for r in PlanilhaRegistro.objects.order_by('-data_registro'):
            cells = []
            for col in cols:
                field = col['field']
                val = getattr(r, field, '')
                # formata decimais
                if isinstance(val, float) or (hasattr(val, 'quantize')):
                    try:
                        val = f"{float(val):.2f}".replace('.', ',')
                    except Exception:
                        pass
                # formata datas
                from datetime import date, datetime
                if isinstance(val, (date, datetime)):
                    try:
                        val = val.strftime('%d/%m/%Y')
                    except Exception:
                        pass
                # booleanos para 'Sim'/'Não'
                if isinstance(val, bool):
                    val = 'Sim' if val else 'Não'
                cells.append({'class': col['class'], 'value': val})

            rows.append({'id': r.id, 'cells': cells, 'data_registro': r.data_registro})

        context['google_rows'] = rows
        # Fornece clientes iniciais a partir do AppState salvo (app_Gestor)
        try:
            state = AppState.objects.filter(key='main').first()
            initial_clientes = state.data.get('clientes', []) if state and isinstance(state.data, dict) else []
        except Exception:
            initial_clientes = []

        try:
            parceiros_dict = {}
            for r in PlanilhaRegistro.objects.filter(contador_parceiro__gt=''):
                key = (r.contador_parceiro or '').strip()
                if not key:
                    continue
                if key not in parceiros_dict:
                    parceiros_dict[key] = {
                        'id': key,
                        'nome': r.contador_parceiro,
                        'tipo': 'Parceiro',
                        'comissao': float(r.percentual_comissao) if r.percentual_comissao is not None else None,
                        'contato': r.telefone1 or '',
                        'email': r.email or '',
                    }
            initial_parceiros = list(parceiros_dict.values())
        except Exception:
            initial_parceiros = []

        import json
        try:
            context['initial_clientes_json'] = json.dumps(initial_clientes, default=str)
        except Exception:
            context['initial_clientes_json'] = '[]'
        try:
            context['initial_parceiros_json'] = json.dumps(initial_parceiros, default=str)
        except Exception:
            context['initial_parceiros_json'] = '[]'
        return context


def editar_google_row(request, pk):
    registro = get_object_or_404(PlanilhaRegistro, pk=pk)
    if request.method == 'POST':
        registro.cliente = request.POST.get('cliente', registro.cliente) or registro.cliente
        registro.email = request.POST.get('email', registro.email) or registro.email
        # campos numéricos
        def parse_decimal_field(name, current):
            val = request.POST.get(name)
            if val is None:
                return current
            try:
                return float(val.replace(',', '.'))
            except Exception:
                return current

        registro.valor_venda = parse_decimal_field('valor_venda', registro.valor_venda)
        registro.percentual_comissao = parse_decimal_field('percentual_comissao', registro.percentual_comissao)
        registro.valor_comissao = parse_decimal_field('valor_comissao', registro.valor_comissao)

        registro.pago_comissao = request.POST.get('pago_comissao') in ['Sim', 'on', 'true', 'True']
        registro.pago_venda = request.POST.get('pago_venda') in ['Sim', 'on', 'true', 'True']

        registro.save()

        # Reescreve a planilha no Drive com os dados atualizados
        SPREADSHEET_ID = '1L-MX27Y6iwCOyd0e4FqLxZJyRFCpHIP6arYYeFIHLME'
        try:
            salvar_no_drive_desde_db(SPREADSHEET_ID)
            messages.success(request, 'Registro atualizado e planilha no Drive sobrescrita com sucesso.')
        except Exception as e:
            messages.warning(request, f'Registro salvo localmente, falha ao atualizar Drive: {str(e)}')

        return redirect('dashboard')

    return render(request, 'google_edit.html', {'registro': registro})


@csrf_exempt
def app_state(request):
    if request.method == 'GET':
        state = AppState.objects.filter(key='main').first()
        data = state.data if state else {'clientes': [], 'parceiros': [], 'precos': []}
        return JsonResponse(data)

    if request.method == 'POST':
        try:
            payload = json.loads(request.body.decode('utf-8'))
        except Exception:
            return HttpResponseBadRequest('JSON inválido')

        state, _ = AppState.objects.get_or_create(key='main')
        state.data = payload
        state.save()
        return JsonResponse({'saved': True})

    return HttpResponseBadRequest('Método não permitido')


@csrf_exempt
def app_state_drive(request):
    if request.method != 'POST':
        return HttpResponseBadRequest('Método não permitido')

    try:
        payload = json.loads(request.body.decode('utf-8'))
    except Exception:
        return HttpResponseBadRequest('JSON inválido')

    state, _ = AppState.objects.get_or_create(key='main')
    state.data = payload
    state.save()

    SPREADSHEET_ID = '1L-MX27Y6iwCOyd0e4FqLxZJyRFCpHIP6arYYeFIHLME'
    success = False
    try:
        save_state_to_drive(payload, SPREADSHEET_ID)
        success = True
    except Exception as e:
        messages.warning(request, f'Falha ao salvar na nuvem: {str(e)}')

    return JsonResponse({'saved': True, 'drive': success})


@csrf_exempt
def app_state_download(request):
    """Gera e retorna um arquivo Excel (.xlsx) com o estado enviado no body
    ou com o estado salvo no banco (key='main') quando chamado via GET.
    """
    try:
        if request.method == 'POST':
            payload = json.loads(request.body.decode('utf-8'))
        else:
            state = AppState.objects.filter(key='main').first()
            payload = state.data if state else {'clientes': [], 'parceiros': [], 'precos': []}

        clientes = payload.get('clientes', []) or []
        parceiros = payload.get('parceiros', []) or []
        precos = payload.get('precos', []) or []

        df_clientes = pd.DataFrame(clientes)
        df_parceiros = pd.DataFrame(parceiros)
        df_precos = pd.DataFrame(precos)

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            if not df_clientes.empty:
                df_clientes.to_excel(writer, sheet_name='Clientes', index=False)
            else:
                pd.DataFrame([{'info': 'Nenhum cliente'}]).to_excel(writer, sheet_name='Clientes', index=False)
            if not df_parceiros.empty:
                df_parceiros.to_excel(writer, sheet_name='Parceiros', index=False)
            else:
                pd.DataFrame([{'info': 'Nenhum parceiro'}]).to_excel(writer, sheet_name='Parceiros', index=False)
            if not df_precos.empty:
                df_precos.to_excel(writer, sheet_name='Precos', index=False)
            else:
                pd.DataFrame([{'info': 'Nenhum preco'}]).to_excel(writer, sheet_name='Precos', index=False)

        output.seek(0)
        resp = HttpResponse(output.read(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        resp['Content-Disposition'] = 'attachment; filename="estado_clientes_parceiros.xlsx"'
        return resp
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


class ParceirosView(TemplateView):
    template_name = 'parceiros.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from datetime import date, datetime
        
        # Extrai parceiros únicos da tabela PlanilhaRegistro
        registros = PlanilhaRegistro.objects.filter(contador_parceiro__gt='').distinct('contador_parceiro').values(
            'contador_parceiro', 'cpf_cnpj', 'percentual_comissao', 'telefone1', 'email'
        ).order_by('contador_parceiro')
        
        # Se distinct não funcionar (SQLite não suporta), fazemos manualmente
        parceiros_dict = {}
        for r in PlanilhaRegistro.objects.filter(contador_parceiro__gt=''):
            key = r.contador_parceiro
            if key not in parceiros_dict:
                parceiros_dict[key] = {
                    'contador_parceiro': r.contador_parceiro,
                    'cpf_cnpj': r.cpf_cnpj,
                    'percentual_comissao': r.percentual_comissao,
                    'telefone1': r.telefone1,
                    'email': r.email,
                }
        
        # Monta estrutura de colunas e linhas
        context['columns'] = [
            {'label': 'Contador Parceiro', 'field': 'contador_parceiro', 'class': 'col-contador'},
            {'label': 'CPF/CNPJ', 'field': 'cpf_cnpj', 'class': 'col-cpf'},
            {'label': 'Percentual de Comissão (%)', 'field': 'percentual_comissao', 'class': 'col-percentual'},
            {'label': 'Telefone', 'field': 'telefone1', 'class': 'col-telefone'},
            {'label': 'Email', 'field': 'email', 'class': 'col-email'},
        ]
        
        rows = []
        for parceiro in parceiros_dict.values():
            cells = []
            for col in context['columns']:
                field = col['field']
                val = parceiro.get(field, '')
                
                # Formata decimais
                if isinstance(val, float) or (hasattr(val, 'quantize')):
                    try:
                        val = f"{float(val):.2f}".replace('.', ',')
                    except Exception:
                        pass
                
                cells.append({'class': col['class'], 'value': val})
            
            rows.append({'cells': cells})
        
        context['parceiros_rows'] = rows
        return context
