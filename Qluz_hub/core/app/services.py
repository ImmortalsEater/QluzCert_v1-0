import io
import os
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
import pandas as pd
from .models import Colaborador, PlanilhaRegistro

def sincronizar_processar_e_salvar_copias(file_id):
    """
    1. Detecta o tipo de arquivo no Drive (Google Sheets ou Excel).
    2. Pula o título e localiza a linha de cabeçalho real da QLUZ.
    3. Trata colunas duplicadas ('Pago' da comissão vs 'Pago' da venda).
    4. Alimenta o Banco de Dados do Django.
    5. Salva a cópia offline (.xlsx) e atualiza o Drive.
    """
    SCOPES = ['https://www.googleapis.com/auth/drive']
    
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    creds_path = os.path.join(project_root, 'credentials.json')
    if not os.path.exists(creds_path):
        raise FileNotFoundError(
            f"Arquivo de credenciais não encontrado em {creds_path}. "
            "Coloque seu credentials.json na raiz do projeto Qluz_hub."
        )

    creds = service_account.Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    service = build('drive', 'v3', credentials=creds)

    # Checa o tipo de arquivo no Drive
    metadata = service.files().get(fileId=file_id, fields='mimeType').execute()
    mime_type = metadata.get('mimeType')

    # --- PARTE 1: DOWNLOAD / EXPORTAÇÃO ---
    fh = io.BytesIO()
    if mime_type == 'application/vnd.google-apps.spreadsheet':
        request = service.files().export_media(
            fileId=file_id,
            mimeType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    else:
        request = service.files().get_media(fileId=file_id)
        
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while done is False:
        status, done = downloader.next_chunk()
    
    fh.seek(0)
    
    # --- PARTE 2: TRATAMENTO DINÂMICO DO CABEÇALHO QLUZ ---
    # Funções auxiliares para normalizar e identificar cabeçalho
    def normalize_header(text):
        if text is None:
            return ''
        normalized = str(text).strip().lower()
        replacements = {
            'á': 'a', 'à': 'a', 'ã': 'a', 'â': 'a', 'é': 'e', 'ê': 'e',
            'í': 'i', 'ó': 'o', 'ô': 'o', 'õ': 'o', 'ú': 'u', 'ç': 'c',
            ' ': '', '-': '', '_': ''
        }
        for old, new in replacements.items():
            normalized = normalized.replace(old, new)
        return normalized

    nomes_possíveis = ['contadorparceiro', 'parceiro', 'nome', 'nomeparceiro', 'nomecontador', 'nomedonegocio']
    emails_possíveis = ['email', 'email', 'e-mail']

    # Lemos todas as abas do arquivo bruto sem assumir cabeçalho na linha 0
    # (algumas planilhas podem ter título/abações e o sheet alvo não ser a primeira)
    all_sheets = pd.read_excel(fh, sheet_name=None, header=None)
    df_cru = None
    sheet_used_name = None
    # Tentaremos detectar o cabeçalho em cada aba disponível
    for sheet_name, sheet_df in all_sheets.items():
        # faz uma cópia para análise
        tmp = sheet_df.copy()
        idx_found = None
        for idx, row in tmp.iterrows():
            valores_linha = [normalize_header(val) for val in row.values if pd.notna(val)]

            # Verifica se tem email
            has_email = any(any(email_term in val for email_term in ['email', 'e-mail']) for val in valores_linha)

            # Verifica se tem nome/parceiro
            has_name = any(nome_term in val for nome_term in nomes_possíveis for val in valores_linha)

            if (has_email and has_name) or (has_email and len(valores_linha) >= 3):
                idx_found = idx
                break

        if idx_found is not None:
            df_cru = tmp
            idx_cabecalho = idx_found
            sheet_used_name = sheet_name
            break

    # Se não encontrou em nenhuma aba, usar a primeira aba como fallback (para debug a linha 0)
    if df_cru is None:
        # pega a primeira aba para mensagem de debug
        first_sheet = next(iter(all_sheets.values()))
        df_cru = first_sheet
        idx_cabecalho = None

    idx_cabecalho = None
    
    for idx, row in df_cru.iterrows():
        valores_linha = [normalize_header(val) for val in row.values if pd.notna(val)]
        
        # Verifica se tem email
        has_email = any(any(email_term in val for email_term in emails_possíveis) for val in valores_linha)
        
        # Verifica se tem nome/parceiro
        has_name = any(nome_term in val for nome_term in nomes_possíveis for val in valores_linha)
        
        # Também aceita se tiver apenas email + alguma coluna que não seja vazia
        if (has_email and has_name) or (has_email and len(valores_linha) >= 3):
            idx_cabecalho = idx
            break

    if idx_cabecalho is None:
        # Se não encontrou, mostra as primeiras 10 linhas para debugging
        print(f"\n DEBUG: Não foi encontrado cabeçalho. Primeiras 10 linhas da planilha:")
        for i in range(min(10, len(df_cru))):
            print(f"Linha {i}: {list(df_cru.iloc[i].values)}")
        raise Exception(
            "Não foi possível localizar as colunas de cabeçalho esperadas na planilha. "
            "Verifique se existem colunas como 'Nome', 'E-mail' ou 'Contador/Parceiro'. "
            "Verifique o console para debug das primeiras linhas."
        )


    df_cru.columns = df_cru.iloc[idx_cabecalho]
    df = df_cru.iloc[idx_cabecalho + 1:].reset_index(drop=True)
    
    # --- TRATAMENTO DE COLUNAS DUPLICADAS ---
    # Como existem duas colunas chamadas "Pago", o Pandas por padrão as renomeia para tornar únicas.
    # Vamos renomear manualmente a lista de colunas para sabermos exatamente qual é qual.
    novas_colunas = []
    ja_viu_pago = False
    
    for col in df.columns:
        col_nome = str(col).strip()
        if col_nome == 'Pago':
            if not ja_viu_pago:
                novas_colunas.append('Pago_Comissao') # O primeiro 'Pago' é da comissão
                ja_viu_pago = True
            else:
                novas_colunas.append('Pago_Venda')    # O segundo 'Pago' é da venda
        else:
            novas_colunas.append(col_nome)
            
    df.columns = novas_colunas

    # --- PARTE 3: ATUALIZAR O BANCO DE DADOS DJANGO (PlanilhaRegistro) ---
    contagem_novos = 0
    for _, linha in df.iterrows():
        # Cria um dicionário com os valores das colunas (usando nomes brutos)
        row = {str(k).strip(): (v if pd.notna(v) else None) for k, v in linha.items()}

        def get(keys, default=None):
            for k in keys:
                if k in row and row[k] is not None:
                    return row[k]
            return default

        # Mapear campos conforme solicitado
        data_venda_raw = get(['Data da Venda', 'Data Venda', 'Data'], None)
        cliente = get(['Cliente', 'Nome', 'Contador/Parceiro', 'Parceiro'], '')
        cpf = get(['CPF/CNPJ', 'CPF', 'CNPJ'], '')
        email = get(['email', 'E-mail', 'Email'], '')
        contador_parceiro = get(['Contador/Parceiro', 'Contador/Contabilidade'], '')
        contador_contabilidade = get(['Contador/Contabilidade'], '')
        telefone1 = get(['Telefone', 'Telefone1'], '')
        telefone2 = get(['Telefone '], '')
        tipo_certificado = get(['Tipo de Certificado', 'Tipo Certificado'], '')
        valor_venda_raw = get(['Valor da Venda (R$)', 'Valor da Venda', 'Valor Venda'], None)
        percentual_raw = get(['Percentual de Comissão (%)', 'Percentual de Comissão', 'Percentual Comissão'], None)
        valor_comissao_raw = get(['Valor da Comissão (R$)', 'Valor da Comissao', 'Valor Comissão'], None)
        pago_raw = get(['Pago_Comissao', 'Pago_Comissao ', 'Pago', 'Paga'], None)
        chave_pix = get(['Chave PIX', 'Chave PIX '], '')
        data_vencimento_raw = get(['Data de Vencimento', 'Data Vencimento'], None)
        pago_venda_raw = get(['Pago_Venda', 'Pago_venda', 'Pago '], None)
        forma_pagamento = get(['Forma de pagamento', 'Forma de Pagamento'], '')
        banco = get(['Banco'], '')
        certificado_feito = get(['Certfificado Feito', 'Certificado Feito'], '')
        venda = get(['Venda'], '')
        custo_certificado_raw = get(['Custo do Certificado', 'Custo Certificado'], None)
        valor_liquido_raw = get(['Valor Liquido', 'Valor Líquido', 'Valor Liquido '], None)

        # Conversões
        from datetime import datetime
        def parse_date(val):
            if val is None:
                return None
            if isinstance(val, (pd.Timestamp, datetime)):
                return val.date()
            try:
                return pd.to_datetime(val).date()
            except Exception:
                return None

        def parse_decimal(val):
            if val is None:
                return None
            try:
                return float(val)
            except Exception:
                try:
                    s = str(val).replace('R$', '').replace('.', '').replace(',', '.')
                    return float(s)
                except Exception:
                    return None

        data_venda = parse_date(data_venda_raw)
        data_vencimento = parse_date(data_vencimento_raw)
        valor_venda = parse_decimal(valor_venda_raw)
        percentual_comissao = parse_decimal(percentual_raw)
        valor_comissao = parse_decimal(valor_comissao_raw)
        custo_certificado = parse_decimal(custo_certificado_raw)
        valor_liquido = parse_decimal(valor_liquido_raw)

        def bool_from(val):
            if val is None:
                return False
            s = str(val).strip().lower()
            return s in ['sim', 'true', '1', 'pago', 'yes']

        pago_comissao = bool_from(pago_raw)
        pago_venda = bool_from(pago_venda_raw)

        # Identifica por email + cliente
        if not email and not cliente:
            # ignora linhas sem identificador
            continue

        registro, criado = PlanilhaRegistro.objects.update_or_create(
            email=str(email).strip() if email else None,
            cliente=str(cliente).strip() if cliente else '',
            defaults={
                'data_venda': data_venda,
                'contador_parceiro': str(contador_parceiro) if contador_parceiro else '',
                'contador_contabilidade': str(contador_contabilidade) if contador_contabilidade else '',
                'telefone1': str(telefone1) if telefone1 else '',
                'cpf_cnpj': str(cpf) if cpf else '',
                'telefone2': str(telefone2) if telefone2 else '',
                'tipo_certificado': str(tipo_certificado) if tipo_certificado else '',
                'valor_venda': valor_venda,
                'percentual_comissao': percentual_comissao,
                'valor_comissao': valor_comissao,
                'pago_comissao': pago_comissao,
                'chave_pix': str(chave_pix) if chave_pix else '',
                'data_vencimento': data_vencimento,
                'pago_venda': pago_venda,
                'forma_pagamento': str(forma_pagamento) if forma_pagamento else '',
                'banco': str(banco) if banco else '',
                'certificado_feito': str(certificado_feito) if certificado_feito else '',
                'venda': str(venda) if venda else '',
                'custo_certificado': custo_certificado,
                'valor_liquido': valor_liquido,
            }
        )
        if criado:
            contagem_novos += 1

    # --- PARTE 4: GERAR COPIA ATUALIZADA (OFFLINE) ---
    # --- PARTE 4: GERAR COPIA ATUALIZADA (OFFLINE) ---
    todos = PlanilhaRegistro.objects.all().order_by('-data_registro')
    dados_para_excel = []
    for c in todos:
        dados_para_excel.append({
            'Data da Venda': c.data_venda,
            'Contador/Parceiro': c.contador_parceiro,
            'Contador/Contabilidade': c.contador_contabilidade,
            'Telefone': c.telefone1,
            'Cliente': c.cliente,
            'CPF/CNPJ': c.cpf_cnpj,
            'email': c.email,
            'Telefone2': c.telefone2,
            'Tipo de Certificado': c.tipo_certificado,
            'Valor da Venda (R$)': float(c.valor_venda) if c.valor_venda is not None else None,
            'Percentual de Comissão (%)': float(c.percentual_comissao) if c.percentual_comissao is not None else None,
            'Valor da Comissão (R$)': float(c.valor_comissao) if c.valor_comissao is not None else None,
            'Pago_Comissao': 'Sim' if c.pago_comissao else 'Não',
            'Chave PIX': c.chave_pix,
            'Data de Vencimento': c.data_vencimento,
            'Pago_Venda': 'Sim' if c.pago_venda else 'Não',
            'Forma de pagamento': c.forma_pagamento,
            'Banco': c.banco,
            'Certfificado Feito': c.certificado_feito,
            'Venda': c.venda,
            'Custo do Certificado': float(c.custo_certificado) if c.custo_certificado is not None else None,
            'Valor Liquido': float(c.valor_liquido) if c.valor_liquido is not None else None,
        })

    df_atualizado = pd.DataFrame(dados_para_excel)

    pasta_offline = os.path.join(project_root, 'copias_offline')
    if not os.path.exists(pasta_offline):
        os.makedirs(pasta_offline)
        
    caminho_arquivo_local = os.path.join(pasta_offline, 'planilha_gerenciador_offline.xlsx')
    df_atualizado.to_excel(caminho_arquivo_local, index=False)

    # --- PARTE 5: ATUALIZAR GOOGLE DRIVE (Se não for planilha nativa) ---
    if mime_type != 'application/vnd.google-apps.spreadsheet':
        media = MediaFileUpload(
            caminho_arquivo_local, 
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 
            resumable=True
        )
        service.files().update(fileId=file_id, media_body=media).execute()

    return contagem_novos


def salvar_no_drive_desde_db(file_id):
    """Gera um XLSX local a partir do DB e faz upload para o arquivo do Drive, sobrescrevendo-o.
    Observação: o arquivo na conta do Drive será substituído pelo conteúdo do XLSX.
    """
    SCOPES = ['https://www.googleapis.com/auth/drive']
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    creds_path = os.path.join(project_root, 'credentials.json')
    if not os.path.exists(creds_path):
        raise FileNotFoundError('credentials.json não encontrado para autenticação Google.')

    creds = service_account.Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    drive_service = build('drive', 'v3', credentials=creds)

    headers = [
        'Data da Venda','Contador/Parceiro','Contador/Contabilidade','Telefone','Cliente','CPF/CNPJ','email','Telefone2','Tipo de Certificado',
        'Valor da Venda (R$)','Percentual de Comissão (%)','Valor da Comissão (R$)','Pago_Comissao','Chave PIX','Data de Vencimento','Pago_Venda','Forma de pagamento',
        'Banco','Certfificado Feito','Venda','Custo do Certificado','Valor Liquido'
    ]

    rows = []
    for r in PlanilhaRegistro.objects.order_by('data_registro'):
        rows.append([
            r.data_venda.strftime('%Y-%m-%d') if r.data_venda else '',
            r.contador_parceiro,
            r.contador_contabilidade,
            r.telefone1,
            r.cliente,
            r.cpf_cnpj,
            r.email,
            r.telefone2,
            r.tipo_certificado,
            float(r.valor_venda) if r.valor_venda is not None else None,
            float(r.percentual_comissao) if r.percentual_comissao is not None else None,
            float(r.valor_comissao) if r.valor_comissao is not None else None,
            'Sim' if r.pago_comissao else 'Não',
            r.chave_pix,
            r.data_vencimento.strftime('%Y-%m-%d') if r.data_vencimento else '',
            'Sim' if r.pago_venda else 'Não',
            r.forma_pagamento,
            r.banco,
            r.certificado_feito,
            r.venda,
            float(r.custo_certificado) if r.custo_certificado is not None else None,
            float(r.valor_liquido) if r.valor_liquido is not None else None,
        ])

    # Cria DataFrame e salva XLSX local
    df = pd.DataFrame(rows, columns=headers)
    pasta_offline = os.path.join(project_root, 'copias_offline')
    if not os.path.exists(pasta_offline):
        os.makedirs(pasta_offline)
    caminho_arquivo_local = os.path.join(pasta_offline, 'planilha_gerenciador_upload.xlsx')
    df.to_excel(caminho_arquivo_local, index=False)

    # Faz upload (sobrescreve o arquivo existente no Drive)
    media = MediaFileUpload(
        caminho_arquivo_local,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        resumable=True
    )
    drive_service.files().update(fileId=file_id, media_body=media).execute()

    return True


def _extract_drive_file_id(file_url_or_id):
    if not file_url_or_id:
        return None
    if isinstance(file_url_or_id, str) and 'https://docs.google.com' in file_url_or_id:
        import re
        match = re.search(r'/d/([a-zA-Z0-9_-]+)', file_url_or_id)
        if match:
            return match.group(1)
    return file_url_or_id


def importar_planilha_do_drive(file_id_or_url):
    file_id = _extract_drive_file_id(file_id_or_url)
    if not file_id:
        raise ValueError('ID do arquivo do Google Drive inválido')
    return sincronizar_processar_e_salvar_copias(file_id)
