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

def download_files(task_data, aoi_name, token):
    """
    Baixa todos os arquivos de uma tarefa concluída.
    (Idêntico ao script do ECOSTRESS, mas salva em pasta "SMAP_AppEEARS")
    """
    if not task_data or 'files' not in task_data:
        print("Nenhum arquivo encontrado para baixar.")
        return

    # --- MUDANÇA AQUI ---
    output_dir = os.path.join(RAW_TIF_DIR, aoi_name, "SMAP_AppEEARS")
    # --- FIM DA MUDANÇA ---
    os.makedirs(output_dir, exist_ok=True)
    
    headers = {'Authorization': f'Bearer {token}'}
    
    for file_info in task_data['files']:
        file_id = file_info['file_id']
        file_name = file_info['file_name']
        zip_path = os.path.join(output_dir, file_name)
        
        if os.path.exists(zip_path.replace('.zip', '')):
             tqdm.write(f"[OK] Pasta já extraída: {file_name}")
             continue
        
        tqdm.write(f"Baixando: {file_name}...")
        
        # 1. Baixar o ZIP
        download_url = API_URL + "bundle/" + task_data['task_id'] + "/" + file_id
        try:
            response = requests.get(download_url, headers=headers, stream=True)
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            block_size = 1024
            progress_bar = tqdm(total=total_size, unit='B', unit_scale=True, desc=file_name)
            
            with open(zip_path, 'wb') as f:
                for data in response.iter_content(block_size):
                    progress_bar.update(len(data))
                    f.write(data)
            progress_bar.close()

            # 2. Extrair o ZIP
            tqdm.write(f"Extraindo: {file_name}...")
            extract_folder = os.path.join(output_dir, file_name.replace('.zip', ''))
            with zipfile.ZipFile(zip_path, 'r') as z:
                z.extractall(extract_folder)
            
            # 3. Limpar o ZIP
            os.remove(zip_path)
            tqdm.write(f"✅ Extraído e limpo: {file_name}")

        except Exception as e:
            tqdm.write(f"❌ ERRO ao baixar/extrair {file_name}: {e}")