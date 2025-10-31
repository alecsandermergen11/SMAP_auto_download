import questionary
import sys
import os
import time 
from datetime import datetime
from tqdm import tqdm 
import pandas as pd
from config import RAW_TIF_DIR, CSV_DIR

# Reutiliza configs e utils
from config import setup_directories
from utils import find_shapefiles, get_aoi_as_geojson

# Importa do nosso novo script de lógica SMAP
from smap_api_ops import (
    api_login,
    submit_task,
    check_task_status,
    download_files,
    SMAP_PRODUCTS  # <-- MUDANÇA AQUI
)

def main():
    """
    Ferramenta principal para baixar dados SMAP via API AppEEARS.
    """
    
    print("==================================================")
    print("     Ferramenta de Download SMAP (API AppEEARS)   ")
    print("==================================================")

    # --- 1. Setup: Criar pastas ---
    setup_directories()
    
    # --- 2. Autenticação (CRÍTICA) ---
    token = api_login()
    if not token:
        sys.exit(1) 

    # --- 3. Selecionar AOIs ---
    shapefiles = find_shapefiles()
    if not shapefiles:
        sys.exit(1) 

    selected_aoi_basenames = questionary.checkbox(
        "Quais Áreas de Interesse (AOI) você quer usar?",
        choices=[os.path.basename(shp) for shp in shapefiles]
    ).ask()

    if not selected_aoi_basenames:
        print("Nenhuma AOI selecionada. Saindo.")
        sys.exit(0)

    # --- 4. Selecionar Datas ---
    def is_valid_date(date_str):
        try:
            datetime.strptime(date_str, '%Y-%m-%d')
            return True
        except ValueError:
            return "Formato inválido. Use AAAA-MM-DD"

    start_date = questionary.text(
        "Digite a data de INÍCIO (AAAA-MM-DD):",
        validate=is_valid_date,
        default='2015-04-01' # Data de início do SMAP
    ).ask()

    end_date = questionary.text(
        "Digite a data de FIM (AAAA-MM-DD):",
        validate=is_valid_date,
        default=datetime.now().strftime('%Y-%m-%d')
    ).ask()

    # *** INÍCIO DA MUDANÇA: DIVIDIR DATAS EM "PEDAÇOS" ANUAIS ***
    try:
        total_start_dt = datetime.strptime(start_date, '%Y-%m-%d')
        total_end_dt = datetime.strptime(end_date, '%Y-%m-%d')
        
        start_year = total_start_dt.year
        end_year = total_end_dt.year
        
        date_chunks = []
        for year in range(start_year, end_year + 1):
            # Define o início do ano
            chunk_start_dt = datetime(year, 1, 1)
            # Define o fim do ano
            chunk_end_dt = datetime(year, 12, 31)
            
            # Ajusta o primeiro ano para a data de início real
            if year == start_year and total_start_dt > chunk_start_dt:
                chunk_start_dt = total_start_dt
            
            # Ajusta o último ano para a data de fim real
            if year == end_year and total_end_dt < chunk_end_dt:
                chunk_end_dt = total_end_dt
                
            date_chunks.append((
                chunk_start_dt.strftime('%Y-%m-%d'), 
                chunk_end_dt.strftime('%Y-%m-%d')
            ))
            
        print(f"Período total dividido em {len(date_chunks)} lotes anuais.")
        
    except Exception as e:
        print(f"Erro ao processar datas: {e}")
        sys.exit(1)
    # *** FIM DA MUDANÇA ***

    # --- 5. Selecionar Coleções ---
    available_products = list(SMAP_PRODUCTS.keys())
    selected_products = questionary.checkbox(
        "Quais produtos SMAP você quer baixar?",
        choices=available_products
    ).ask()

    if not selected_products:
        print("Nenhum produto selecionado. Saindo.")
        sys.exit(0)

    # --- 6. Confirmação ---
    print("\n=== RESUMO DA TAREFA APpeears ===")
    print(f"  AOIs a processar: {', '.join(selected_aoi_basenames)}")
    print(f"  Período: {start_date} até {end_date}")
    print(f"  Lotes: {len(date_chunks)} tarefas anuais POR AOI.")
    print(f"  Produtos: {', '.join(selected_products)}")
    print("\nAVISO: Este processo enviará TODOS os lotes de uma AOI em paralelo.")
    print("O script ficará monitorando todas as tarefas simultaneamente.")
    
    confirm = questionary.confirm(
        "Tudo certo? Deseja iniciar o processo?",
        default=True
    ).ask()

    if not confirm:
        print("Operação cancelada.")
        sys.exit(0)

    # --- 7. Loop de Processamento (Lógica de monitoramento paralelo) ---
    
    for aoi_basename in selected_aoi_basenames:
        print(f"\n\n=======================================================")
        print(f"   Iniciando processamento para a AOI: {aoi_basename} ")
        print(f"=======================================================")
        
        aoi_path_full = next(shp for shp in shapefiles if shp.endswith(aoi_basename))
        aoi_name = os.path.splitext(aoi_basename)[0]
        
        try:
            aoi_geojson = get_aoi_as_geojson(aoi_path_full)
            if aoi_geojson is None:
                print(f"Erro ao carregar geometria para {aoi_basename}. Pulando esta AOI.")
                continue 
        except Exception as e:
            print(f"Erro fatal ao carregar o shapefile {aoi_basename}: {e}")
            continue 

        # --- A. ENVIAR TODAS AS TAREFAS PRIMEIRO ---
        tasks_to_monitor = [] # Lista de tarefas ativas
        
        print(f"Enviando {len(date_chunks)} tarefas para a NASA...")
        for chunk_start, chunk_end in tqdm(date_chunks, desc="Enviando Tarefas"):
            task_id = submit_task(aoi_name, aoi_geojson, selected_products, chunk_start, chunk_end, token)
            
            if task_id:
                tasks_to_monitor.append({
                    "id": task_id,
                    "aoi_name": aoi_name,
                    "period": f"{chunk_start}_to_{chunk_end}"
                })
            else:
                print(f"Falha ao enviar tarefa para o período: {chunk_start}")
        
        if not tasks_to_monitor:
            print("Nenhuma tarefa foi enviada com sucesso. Pulando para a próxima AOI.")
            continue

        # --- B. MONITORAR TODAS AS TAREFAS EM LOOP ---
        print(f"\n✅ {len(tasks_to_monitor)} tarefas enviadas. Iniciando monitoramento...")
        
        total_progress_bar = tqdm(total=len(tasks_to_monitor), desc=f"Progresso (AOI: {aoi_name})")
        
        while tasks_to_monitor:
            num_tasks_antes = len(tasks_to_monitor)
            print(f"\nVerificando status de {len(tasks_to_monitor)} tarefas pendentes... (Próxima verificação em 2 min)")
            
            for task in list(tasks_to_monitor):
                task_status_data = check_task_status(task["id"], token)
                
                if not task_status_data:
                    tqdm.write(f"❌ Erro ao verificar {task['id']}. Será verificado novamente.")
                    continue
                
                status = task_status_data.get('status')
                
                if status == 'done':
                    tqdm.write(f"\n🎉 TAREFA CONCLUÍDA: {task['id']} ({task['period']})")
                    tqdm.write("Iniciando download...")
                    download_files(task_status_data, task['aoi_name'], token)
                    tasks_to_monitor.remove(task) 
                    total_progress_bar.update(1) 
                
                elif status == 'failed':
                    tqdm.write(f"\n❌ ERRO: A tarefa {task['id']} falhou no processamento da NASA.")
                    tqdm.write(f"   Mensagem: {task_status_data.get('message', 'Sem detalhes')}")
                    tasks_to_monitor.remove(task) 
                    total_progress_bar.update(1) 
                else:
                    pass # Continua pendente
            
            if tasks_to_monitor:
                num_completas = num_tasks_antes - len(tasks_to_monitor)
                if num_completas > 0:
                     print(f"{num_completas} tarefa(s) concluída(s) nesta verificação.")
                time.sleep(120) 
        
        total_progress_bar.close()
        print(f"\n--- Processamento da AOI {aoi_name} concluído ---")

    print("\n\n===================================")
    print("  Processamento de todas as tarefas concluído!  ")
    print(f"  TIFs salvos em: {RAW_TIF_DIR}")
    print("===================================")


if __name__ == '__main__':
    main()