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
    # Lemos o arquivo bruto sem assumir cabeçalho na linha 0 (por causa do título de data)
    df_cru = pd.read_excel(fh, header=None)

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

    idx_cabecalho = None
    nomes_possíveis = ['contadorparceiro', 'parceiro', 'nome', 'nomeparceiro', 'nomecontador', 'nomedonegocio']
    emails_possíveis = ['email', 'email', 'e-mail']
    
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
    novas_colunas = []
    ja_viu_pago = False
    
    for col in df.columns:
        col_nome = str(col).strip()
        if col_nome == 'Pago':
            if not ja_viu_pago:
                novas_colunas.append('Pago_Comissao')
                ja_viu_pago = True
            else:
                novas_colunas.append('Pago_Venda')
        else:
            novas_colunas.append(col_nome)
            
    df.columns = novas_colunas

    # --- PARTE 3: ATUALIZAR O BANCO DE DADOS DJANGO ---
    contagem_novos = 0
    for _, linha in df.iterrows():
        # Tenta encontrar a coluna de nome/parceiro em várias variações
        possiveis_parceiros = [
            linha.get('Contador/Parceiro'),
            linha.get('Contador/Parceiro '),
            linha.get('Parceiro'),
            linha.get('Nome'),
            linha.get('Nome do Parceiro'),
            linha.get('Nome do Contador'),
            linha.get('Negócio'),
            linha.get('Empresa'),
            linha.get('Contato'),
        ]
        parceiro = next((x for x in possiveis_parceiros if pd.notna(x) and str(x).strip()), None)

        # Tenta encontrar a coluna de email em várias variações
        possiveis_emails = [
            linha.get('E-mail'),
            linha.get('Email'),
            linha.get('E mail'),
            linha.get('E-Mail'),
            linha.get('email'),
        ]
        email = next((x for x in possiveis_emails if pd.notna(x) and str(x).strip()), None)

        # Tenta encontrar coluna de comissão
        possiveis_comissao = [
            linha.get('Valor da Comissão (R$)'),
            linha.get('Comissão'),
            linha.get('Valor Comissão'),
            linha.get('Valor da Comissao'),
            linha.get('Comissao'),
        ]
        valor_comissao_cru = next((x for x in possiveis_comissao if pd.notna(x)), None)
        
        # Tenta encontrar coluna de status de pagamento
        possiveis_pago = [
            linha.get('Pago_Comissao'),
            linha.get('Pago'),
            linha.get('Paga'),
            linha.get('Status'),
            linha.get('Status Pagamento'),
            linha.get('Pagamento'),
        ]
        status_pago_cru = next((x for x in possiveis_pago if pd.notna(x)), None)

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
