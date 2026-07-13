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
    import re

    def normalize_header(text):
        if text is None:
            return ''
        normalized = str(text).strip().lower()
        replacements = {
            'á': 'a', 'à': 'a', 'ã': 'a', 'â': 'a', 'é': 'e', 'ê': 'e',
            'í': 'i', 'ó': 'o', 'ô': 'o', 'õ': 'o', 'ú': 'u', 'ç': 'c',
        }
        for old, new in replacements.items():
            normalized = normalized.replace(old, new)
        normalized = re.sub(r'[^a-z0-9]+', '', normalized)
        return normalized

    def make_unique_headers(raw_headers):
        seen = {}
        unique_headers = []
        for raw in raw_headers:
            normalized = normalize_header(raw)
            if not normalized:
                normalized = 'col'
            if normalized in seen:
                seen[normalized] += 1
                normalized = f"{normalized}_{seen[normalized]}"
            else:
                seen[normalized] = 1
            unique_headers.append(normalized)
        return unique_headers

    nomes_possiveis = ['contadorparceiro', 'parceiro', 'nome', 'nomeparceiro', 'nomecontador', 'nomedonegocio']
    emails_possiveis = ['email', 'e-mail', 'enderecoemail', 'emailaddress']

    all_sheets = pd.read_excel(fh, sheet_name=None, header=None)
    df_cru = None
    idx_cabecalho = None
    for sheet_name, sheet_df in all_sheets.items():
        tmp = sheet_df.copy()
        for idx, row in tmp.iterrows():
            valores_linha = [normalize_header(val) for val in row.values if pd.notna(val)]
            has_email = any('email' in val for val in valores_linha)
            has_name = any(any(term in val for term in nomes_possiveis) for val in valores_linha)
            if (has_email and has_name) or (has_email and len(valores_linha) >= 3):
                df_cru = tmp
                idx_cabecalho = idx
                break
        if df_cru is not None:
            break

    if df_cru is None:
        df_cru = next(iter(all_sheets.values()))
        idx_cabecalho = 0

    headers = df_cru.iloc[idx_cabecalho].tolist()
    normalized_headers = make_unique_headers(headers)
    df = df_cru.iloc[idx_cabecalho + 1:].reset_index(drop=True)
    df.columns = normalized_headers

    # --- TRATAMENTO DE COLUNAS DUPLICADAS ---
    novas_colunas = []
    ja_viu_pago = False
    for col in df.columns:
        if col == 'pago':
            if not ja_viu_pago:
                novas_colunas.append('pago_comissao')
                ja_viu_pago = True
            else:
                novas_colunas.append('pago_venda')
        elif col == 'pago_2':
            novas_colunas.append('pago_venda')
        else:
            novas_colunas.append(col)
    df.columns = novas_colunas

    # --- PARTE 3: ATUALIZAR O BANCO DE DADOS DJANGO (PlanilhaRegistro) ---
    contagem_novos = 0
    for _, linha in df.iterrows():
        # Cria um dicionário com os valores das colunas normalizadas
        row = {normalize_header(str(k)): (v if pd.notna(v) else None) for k, v in linha.items()}

        def get(keys, default=None):
            normalized_keys = [normalize_header(k) for k in keys]
            for key in normalized_keys:
                if key in row and row[key] is not None:
                    return row[key]
            for header, value in row.items():
                if value is None:
                    continue
                normalized_header = normalize_header(header)
                if any(key in normalized_header for key in normalized_keys):
                    return value
            return default

        # Mapear campos conforme solicitado
        data_venda_raw = get(['Data da Venda', 'Data Venda', 'Data'], None)
        cliente = get(['Cliente', 'Nome', 'Contador/Parceiro', 'Parceiro', 'Cliente'], '')
        cpf = get(['CPF/CNPJ', 'CPF', 'CNPJ'], '')
        email = get(['email', 'E-mail', 'Email', 'E mail', 'emailaddress', 'enderecoemail'], '')
        contador_parceiro = get(['Contador/Parceiro', 'Contador/Contabilidade', 'Contador Parceiro'], '')
        contador_contabilidade = get(['Contador/Contabilidade', 'Contador Contabilidade'], '')
        telefone1 = get(['Telefone', 'Telefone1', 'Celular', 'Celular1'], '')
        telefone2 = get(['Telefone2', 'Telefone 2', 'Celular2', 'Telefone 2'], '')
        tipo_certificado = get(['Tipo de Certificado', 'Tipo Certificado', 'Tipo Certificado'], '')
        valor_venda_raw = get(['Valor da Venda (R$)', 'Valor da Venda', 'Valor Venda', 'Valor', 'Venda'], None)
        percentual_raw = get(['Percentual de Comissão (%)', 'Percentual de Comissão', 'Percentual Comissão', 'Percentual'], None)
        valor_comissao_raw = get(['Valor da Comissão (R$)', 'Valor da Comissao', 'Valor Comissão', 'Comissao'], None)
        pago_raw = get(['Pago_Comissao', 'Pago', 'Paga', 'Pago Comissão', 'Pago_Comissao '], None)
        chave_pix = get(['Chave PIX', 'Pix', 'Chave'], '')
        data_vencimento_raw = get(['Data de Vencimento', 'Data Vencimento', 'Vencimento'], None)
        pago_venda_raw = get(['Pago_Venda', 'Pago Venda', 'Pago_venda', 'Pagamento'], None)
        forma_pagamento = get(['Forma de pagamento', 'Forma de Pagamento', 'Meio de Pagamento'], '')
        banco = get(['Banco', 'Conta', 'Banco/Conta'], '')
        certificado_feito = get(['Certfificado Feito', 'Certificado Feito', 'Certificado'], '')
        venda = get(['Venda', 'Negocio', 'Transacao'], '')
        custo_certificado_raw = get(['Custo do Certificado', 'Custo Certificado', 'Custo'], None)
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
            return s in ['sim', 'true', '1', 'pago', 'yes', 'ok', 's']

        pago_comissao = bool_from(pago_raw)
        pago_venda = bool_from(pago_venda_raw)

        # Identifica por email, cliente ou contador/parceiro
        if not email and not cliente and not contador_parceiro:
            # ignora linhas sem identificador útil
            continue

        lookup = {}
        if email:
            lookup['email'] = str(email).strip()
        elif cliente:
            lookup['cliente'] = str(cliente).strip()
        else:
            lookup['contador_parceiro'] = str(contador_parceiro).strip()

        registro, criado = PlanilhaRegistro.objects.update_or_create(
            defaults={
                'data_venda': data_venda,
                'contador_parceiro': str(contador_parceiro).strip() if contador_parceiro else '',
                'contador_contabilidade': str(contador_contabilidade).strip() if contador_contabilidade else '',
                'telefone1': str(telefone1).strip() if telefone1 else '',
                'cpf_cnpj': str(cpf).strip() if cpf else '',
                'telefone2': str(telefone2).strip() if telefone2 else '',
                'tipo_certificado': str(tipo_certificado).strip() if tipo_certificado else '',
                'cliente': str(cliente).strip() if cliente else '',
                'email': str(email).strip() if email else '',
                'valor_venda': valor_venda,
                'percentual_comissao': percentual_comissao,
                'valor_comissao': valor_comissao,
                'pago_comissao': pago_comissao,
                'chave_pix': str(chave_pix).strip() if chave_pix else '',
                'data_vencimento': data_vencimento,
                'pago_venda': pago_venda,
                'forma_pagamento': str(forma_pagamento).strip() if forma_pagamento else '',
                'banco': str(banco).strip() if banco else '',
                'certificado_feito': str(certificado_feito).strip() if certificado_feito else '',
                'venda': str(venda).strip() if venda else '',
                'custo_certificado': custo_certificado,
                'valor_liquido': valor_liquido,
            },
            **lookup
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
