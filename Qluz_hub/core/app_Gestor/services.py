import io
import os
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
import pandas as pd
from .models import Colaborador

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
    df = df_cru.iloc[idx_cabecalho + 1:].reset_index(drop=True)
    df.columns = make_unique_headers(headers)

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

    # --- PARTE 3: ATUALIZAR O BANCO DE DADOS DJANGO ---
    contagem_novos = 0
    for _, linha in df.iterrows():
        row = {normalize_header(str(k)): (v if pd.notna(v) else None) for k, v in linha.items()}

        def get_value(keys, default=None):
            normalized_keys = [normalize_header(key) for key in keys]
            for key in normalized_keys:
                if key in row and row[key] is not None:
                    return row[key]
            for header, value in row.items():
                if value is None:
                    continue
                normalized_header = normalize_header(header)
                if any(norm_key in normalized_header for norm_key in normalized_keys):
                    return value
            return default

        parceiro = get_value([
            'contadorparceiro', 'parceiro', 'nome', 'nomeparceiro', 'nomecontador', 'nomedonegocio',
            'nomecompleto', 'empresa', 'contato', 'negocio'
        ], None)

        email = get_value([
            'email', 'emailaddress', 'enderecoemail', 'e-mail', 'seuemail'
        ], None)

        valor_comissao_cru = get_value([
            'valordacomissao', 'comissao', 'valorcomissao', 'valor dacomissao', 'valorcomissao', 'valorcomissaor' 
        ], None)

        status_pago_cru = get_value([
            'pagocomissao', 'pagovenda', 'pago', 'paga', 'status', 'statuspagamento', 'pagamento', 'pagocomissao', 'pago_venda'
        ], None)

        # Ignora linhas totalmente vazias ou de totais no fim da planilha
        if not parceiro or not email:
            continue
            
        # Tratamento do valor da comissão (converte para float válido)
        try:
            valor_comissao = float(valor_comissao_cru) if pd.notna(valor_comissao_cru) else 50.00
        except ValueError:
            valor_comissao = 50.00

        # Tratamento do Status de Pagamento (Se na planilha estiver 'Sim', True ou 'Pago')
        comissao_paga = False
        if pd.notna(status_pago_cru):
            status_str = str(status_pago_cru).strip().lower()
            if status_str in ['sim', 'true', '1', 'pago', 'paga']:
                comissao_paga = True

        # Injeta ou atualiza no banco de dados do Django
        colaborador, criado = Colaborador.objects.get_or_create(
            email=str(email).strip(),
            defaults={
                'nome': str(parceiro).strip(),
                'valor_comissao': valor_comissao,
                'comissao_paga': comissao_paga
            }
        )
        if criado:
            contagem_novos += 1

    # --- PARTE 4: GERAR COPIA ATUALIZADA (OFFLINE) ---
    todos_colaboradores = Colaborador.objects.all().order_by('-data_registro')
    dados_para_excel = []
    for c in todos_colaboradores:
        dados_para_excel.append({
            'Contador/Parceiro': c.nome,
            'E-mail': c.email,
            'Valor da Comissão (R$)': float(c.valor_comissao),
            'Pago': 'Sim' if c.comissao_paga else 'Não'
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

def save_state_to_drive(state, file_id):
    SCOPES = ['https://www.googleapis.com/auth/drive']
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    creds_path = os.path.join(project_root, 'credentials.json')
    if not os.path.exists(creds_path):
        raise FileNotFoundError('credentials.json não encontrado para autenticação Google.')

    creds = service_account.Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    drive_service = build('drive', 'v3', credentials=creds)

    clientes = state.get('clientes', []) or []
    parceiros = state.get('parceiros', []) or []
    precos = state.get('precos', []) or []

    df_clientes = pd.DataFrame(clientes)
    df_parceiros = pd.DataFrame(parceiros)
    df_precos = pd.DataFrame(precos)

    pasta_offline = os.path.join(project_root, 'copias_offline')
    if not os.path.exists(pasta_offline):
        os.makedirs(pasta_offline)

    caminho_arquivo_local = os.path.join(pasta_offline, 'estado_clientes_parceiros.xlsx')
    with pd.ExcelWriter(caminho_arquivo_local, engine='openpyxl') as writer:
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
