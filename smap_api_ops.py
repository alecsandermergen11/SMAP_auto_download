import requests
import getpass
import json
import time
import os
import zipfile
from tqdm import tqdm
from config import RAW_TIF_DIR, CSV_DIR # Reutilizamos a config
from datetime import datetime

# URL da API
API_URL = "https://appeears.earthdatacloud.nasa.gov/api/"

# === DICIONÁRIO DE PRODUTOS SMAP (AppEEARS) ===
SMAP_PRODUCTS = {
    'SMAP_L4_ET_flux_09km (SPL4SMGP.008)': {
        'id': 'SPL4SMGP.008',
        'layers': ['Geophysical_Data_land_evapotranspiration_flux']
    },
    'SMAP_L4_LST_09km (SPL4SMGP.008)': {
        'id': 'SPL4SMGP.008',
        'layers': ['Geophysical_Data_surface_temp']
    },
    'SMAP_L4_SM_09km (SPL4SMGP.008)': {
        'id': 'SPL4SMGP.008',
        'layers': ['Geophysical_Data_sm_surface']
    },
    'SMAP_L4_GPP_9km (SPL4CMDL.008)': {
        'id': 'SPL4CMDL.008',
        'layers': ['GPP_gpp_mean']
    },
    'SMAP_L4_NEE_9km (SPL4CMDL.008)': {
        'id': 'SPL4CMDL.008',
        'layers': ['NEE_nee_mean']
    },
    'SMAP_L4_Reco_9km (SPL4CMDL.008)': {
        'id': 'SPL4CMDL.008',
        'layers': ['RH_rh_mean']
    },
    'SMAP_L4_LAI_09km (SPL4SMGP.008)': {
        
        'id': 'SPL4SMGP.008',
        'layers': ['Geophysical_Data_leaf_area_index']
    },
    'SMAP_L4_Rg_09km (SPL4SMGP.008)': {
        'id': 'SPL4SMGP.008',
        'layers': ['Geophysical_Data_radiation_shortwave_downward_flux']
    },
}
# ================================================


def api_login():
    """
    Solicita o login do NASA Earthdata e obtém um token de autenticação.
    (Idêntico ao script do ECOSTRESS)
    """
    print("--- Autenticação NASA Earthdata ---")
    print("Usando a mesma conta de: https://urs.earthdata.nasa.gov/users/new")
    username = input("Usuário (login) Earthdata: ")
    password = getpass.getpass("Senha Earthdata (não será exibida): ")
    
    auth_url = API_URL + "login"
    try:
        response = requests.post(auth_url, auth=(username, password))
        response.raise_for_status() # Verifica se há erros HTTP
        token = response.json()['token']
        print("✅ Autenticação bem-sucedida.")
        return token
    except requests.exceptions.HTTPError as e:
        print("❌ ERRO DE LOGIN: Verifique seu usuário e senha.")
        return None
    except Exception as e:
        print(f"❌ Erro inesperado no login: {e}")
        return None

def submit_task(aoi_name, aoi_geojson, selected_products, start_date, end_date, token):
    """
    Constrói e envia a tarefa de download para a API AppEEARS.
    (Idêntico ao script do ECOSTRESS, mas usa SMAP_PRODUCTS)
    """
    task_name = f"SMAP_{aoi_name}_{start_date}_to_{end_date}"
    task_url = API_URL + "task"
    
    # Converte as datas
    try:
        dt_start = datetime.strptime(start_date, '%Y-%m-%d')
        dt_end = datetime.strptime(end_date, '%Y-%m-%d')
        api_start_date = dt_start.strftime('%m-%d-%Y')
        api_end_date = dt_end.strftime('%m-%d-%Y')
    except ValueError:
        print("Erro interno de formatação de data.")
        return None
    
    # Montar a lista de camadas (layers)
    layers_list = []
    for key in selected_products:
        prod = SMAP_PRODUCTS[key] # <--- ÚNICA MUDANÇA AQUI
        for layer_name in prod['layers']:
            layers_list.append({
                "product": prod['id'],
                "layer": layer_name
            })

    # Montar o JSON completo da requisição
    task_payload = {
        "task_type": "area",
        "task_name": task_name,
        "params": {
            "dates": [{"startDate": api_start_date, "endDate": api_end_date}],
            "layers": layers_list,
            "output": {"format": {"type": "geotiff"}, "projection": "geographic"},
            "geo": aoi_geojson,
        }
    }
    
    # Enviar a requisição (POST)
    headers = {'Authorization': f'Bearer {token}'}
    try:
        response = requests.post(task_url, json=task_payload, headers=headers)
        response.raise_for_status()
        task_id = response.json()['task_id']
        print(f"✅ Tarefa enviada com sucesso! ID da Tarefa: {task_id}")
        return task_id
    except requests.exceptions.HTTPError as e:
        print(f"❌ ERRO AO ENVIAR TAREFA: {e.response.text}") 
        return None
    except Exception as e:
        print(f"❌ Erro inesperado no envio: {e}")
        return None

def check_task_status(task_id, token):
    """
    Verifica o status de uma ÚNICA tarefa, UMA vez.
    (Idêntico ao script do ECOSTRESS)
    """
    status_url = API_URL + "status/" + task_id
    headers = {'Authorization': f'Bearer {token}'}
    try:
        response = requests.get(status_url, headers=headers)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"\nErro ao verificar status da tarefa {task_id}: {e}")
        if 'response' in locals() and response.status_code == 404:
             return {"status": "failed", "message": "Tarefa não encontrada (falha/expirada)"}
        return None

def download_files(task, token):
    """
    Baixa todos os arquivos .tif de uma tarefa concluída.
    'task' é um dicionário: {'id': '...', 'aoi_name': '...', 'period': '...'}
    """
    
    # --- ETAPA 1: Obter informações da tarefa ---
    task_id = task['id']
    aoi_name = task['aoi_name']
    period_folder_name = task['period'] # Ex: '2015-04-01_to_2015-12-31'
    
    bundle_url = API_URL + "bundle/" + task_id
    headers = {'Authorization': f'Bearer {token}'}
    
    try:
        tqdm.write(f"Buscando lista de arquivos (bundle) para {task_id}...")
        response = requests.get(bundle_url, headers=headers)
        response.raise_for_status()
        task_data = response.json() 
    except Exception as e:
        tqdm.write(f"❌ ERRO ao obter lista de arquivos (bundle) para tarefa {task_id}: {e}")
        return

    # --- ETAPA 2: Filtrar e preparar o diretório de saída ---
    if not task_data or 'files' not in task_data:
        tqdm.write("Nenhum arquivo encontrado no bundle da tarefa.")
        return

    # Filtra para baixar APENAS os arquivos .tif
    files_to_download = [f for f in task_data['files'] if f['file_name'].endswith('.tif')]
    
    if not files_to_download:
        tqdm.write("AVISO: Tarefa concluída, mas não foram encontrados arquivos .tif nos resultados.")
        return

    tqdm.write(f"Encontrados {len(files_to_download)} arquivos .tif para baixar...")

    # Cria a pasta de saída base (ex: .../SMAP_AppEEARS/2015-04-01_to_2015-12-31)
    output_dir_base = os.path.join(RAW_TIF_DIR, aoi_name, "SMAP_AppEEARS", period_folder_name)
    os.makedirs(output_dir_base, exist_ok=True)
    
    # --- ETAPA 3: Baixar cada .tif individualmente ---
    for file_info in tqdm(files_to_download, desc=f"Baixando TIFs ({period_folder_name})", leave=False):
        
        file_name = file_info['file_name'] # Ex: "PASTA_PRODUTO/ARQUIVO.tif"
        file_id = file_info['file_id']
        
        # --- CORREÇÃO DA SUBPASTA ---
        # 1. Normaliza barras (Windows/Linux)
        relative_file_path = file_name.replace('/', os.path.sep)
        
        # 2. Cria o caminho de salvamento completo
        tif_path = os.path.join(output_dir_base, relative_file_path)
        
        # 3. Obtém o diretório-pai deste arquivo
        tif_dir = os.path.dirname(tif_path)
        
        # 4. Cria o diretório-pai (A CORREÇÃO)
        os.makedirs(tif_dir, exist_ok=True)
        # --- FIM DA CORREÇÃO ---

        if os.path.exists(tif_path):
             tqdm.write(f"[OK] Já existe: {file_name}")
             continue
        
        download_url = API_URL + "bundle/" + task_id + "/" + file_id
        try:
            response = requests.get(download_url, headers=headers, stream=True)
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            block_size = 1024 * 1024 # Chunks de 1MB
            progress_bar = tqdm(total=total_size, unit='B', unit_scale=True, desc=file_name.split(os.path.sep)[-1][:20], leave=False)

            with open(tif_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=block_size):
                    progress_bar.update(len(chunk))
                    f.write(chunk)
            progress_bar.close()
            # tqdm.write(f"✅ Baixado: {file_name}") # Silencioso para não poluir

        except Exception as e:
            tqdm.write(f"❌ ERRO ao baixar {file_name}: {e}")