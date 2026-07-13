from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import TemplateView
from django.contrib import messages
from django.db import transaction
from .services import importar_planilha_do_drive, salvar_no_drive_desde_db
from .models import Colaborador, PlanilhaRegistro


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


class ParceirosView(TemplateView):
    template_name = 'parceiros.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from datetime import date, datetime
        
        # Extrai parceiros únicos da tabela PlanilhaRegistro
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