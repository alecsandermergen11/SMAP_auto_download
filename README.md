# Ferramenta de Download em Lote (SMAP) - API AppEEARS

Este projeto é uma ferramenta de linha de comando (CLI) em Python para baixar dados de **Umidade do Solo SMAP** da NASA usando a API AppEEARS.

Ele é otimizado para lidar com grandes solicitações de dados, dividindo-as em lotes anuais e enviando-os à NASA para processamento em paralelo.

## Fluxo de Trabalho

1.  **🚀 Etapa 1: Enviar Tarefas**
    * Você executa `python smap_tool.py`.
    * O script pede seu login da NASA Earthdata, AOIs, período e quais produtos SMAP você deseja.
    * O script **divide seu período de tempo em lotes de 1 ano**.
    * Ele envia *todos* esses lotes (ex: 7 tarefas para 7 anos) para a fila da AppEEARS de uma vez.

2.  **☕ Etapa 2: Monitorar**
    * O script entra em modo de espera, verificando o status de *todas* as tarefas enviadas a cada 2 minutos.
    * A NASA processa seus pedidos em paralelo na nuvem.

3.  **⬇️ Etapa 3: Baixar**
    * Conforme *qualquer* tarefa (ex: "ano 2020") é concluída, o script a detecta, baixa o(s) arquivo(s) ZIP e os extrai para `data/raw_tifs/[AOI_NOME]/SMAP_AppEEARS/`.
    * Ele continua monitorando as tarefas restantes até que todos os anos sejam baixados.

## Instalação e Configuração

1.  **Copie os Arquivos:**
    * Copie `config.py` e `utils.py` do seu projeto ECOSTRESS para esta pasta.
    * Copie o `environment.yml` do seu projeto ECOSTRESS.

2.  **Crie o Ambiente (se ainda não o fez):**
    ```bash
    conda env create -f environment.yml
    ```

3.  **Ative o Ambiente:**
    ```bash
    conda activate gee_modis_downloader
    ```

4.  **Conta NASA:**
    * Você deve ter uma conta gratuita do [NASA Earthdata](https://urs.earthdata.nasa.gov/users/new).

## Como Usar

1.  **Adicionar AOIs:**
    * Coloque seus arquivos shapefile (`.shp`, `.shx`, etc.) na pasta `/aoi`.

2.  **Executar o Script:**
    * No seu terminal, com o ambiente ativado, execute:
    ```bash
    python smap_tool.py
    ```

3.  **Siga as Instruções:**
    * Faça login com seu usuário e senha do Earthdata.
    * Selecione uma ou mais AOIs.
    * Selecione o período de datas. O script o dividirá em anos.
    * Selecione os produtos SMAP (L3/L4) que deseja.
    * Confirme e deixe o script rodar.

Os arquivos baixados (GeoTIFFs) aparecerão na pasta `data/raw_tifs/` organizados por AOI.