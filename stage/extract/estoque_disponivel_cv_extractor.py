import os
import csv
import time
from pathlib import Path
import dotenv
import requests

dotenv.load_dotenv(dotenv_path=r'D:\GitHub\etl_api_sienge\.env')

pasta_origem = Path(__file__).resolve().parents[2]
INPUT_DIR = pasta_origem / "stage" / "transform" / "files" / "input"

headers_v1 = {
    "accept": "application/json",
    "email": os.getenv("EMAIL"),
    "token": os.getenv("TOKEN"),
}

token_v3 = requests.post(
    "https://telesil.cvcrm.com.br/api/v3/auth/token",
    json={
        "email": os.getenv("EMAIL"),
        "senha": os.getenv("SENHACV"),
        "painel": os.getenv("PAINEL"),
    }
).json()["data"]["access_token"]

headers_v3 = {
    "Accept": "application/json",
    "Authorization": f"Bearer {token_v3}",
}

BASE = "https://telesil.cvcrm.com.br"

MAX_RETRIES = 3
RETRY_BACKOFF = [2, 5, 10]  # segundos entre tentativas


def safe_json(response):
    if not response.text.strip():
        return None
    try:
        return response.json()
    except Exception:
        return None


def _get_com_retry(url: str, headers: dict, params: dict) -> requests.Response | None:
    """
    GET com retry e backoff para erros 5xx.
    Retorna Response em caso de sucesso (2xx), None após esgotar tentativas.
    """
    for tentativa in range(MAX_RETRIES):
        try:
            r = requests.get(url, headers=headers, params=params, timeout=30)
            if r.status_code == 200:
                return r
            # 4xx → erro do cliente, não adianta retry
            if r.status_code < 500:
                print(f"    [retry] HTTP {r.status_code} — erro de cliente, sem retry.")
                return None
            espera = RETRY_BACKOFF[min(tentativa, len(RETRY_BACKOFF) - 1)]
            print(f"    [retry] HTTP {r.status_code} — tentativa {tentativa + 1}/{MAX_RETRIES}, aguardando {espera}s...")
            time.sleep(espera)
        except requests.exceptions.RequestException as exc:
            espera = RETRY_BACKOFF[min(tentativa, len(RETRY_BACKOFF) - 1)]
            print(f"    [retry] Exceção de rede: {exc} — tentativa {tentativa + 1}/{MAX_RETRIES}, aguardando {espera}s...")
            time.sleep(espera)
    print(f"    [retry] Esgotadas {MAX_RETRIES} tentativas para {url} params={params}")
    return None


def fetch_mapa_disponibilidade(id_emp: int) -> list[dict]:
    """
    Retorna TODAS as unidades do empreendimento via mapa de disponibilidade,
    independente de situação (Disponível, Vendida, Bloqueada...).

    Estratégia de resiliência contra erros 500:
    1. Retry com backoff por página (até MAX_RETRIES tentativas)
    2. Se ainda falhar, reduz o limite pela metade e tenta de novo
       (serve para servidores que não suportam payloads grandes)
    3. Se mesmo assim falhar, loga e encerra com os registros parciais
    """
    todas: list[dict] = []
    pagina = 1
    limite = 500  # 500 em vez de 1000 — menos pressão por página

    url = f"{BASE}/api/v1/comercial/mapadisponibilidade/{id_emp}"

    while True:
        r = _get_com_retry(url, headers_v1, {"limitePagina": limite, "pag": pagina})

        # Se falhou com limite atual, tenta reduzir pela metade
        if r is None and limite > 50:
            limite = limite // 2
            print(f"    [mapa] Reduzindo limite para {limite} e repetindo página {pagina}...")
            r = _get_com_retry(url, headers_v1, {"limitePagina": limite, "pag": pagina})

        if r is None:
            print(f"    [mapa] ✗ Página {pagina} falhou definitivamente — usando {len(todas)} registros parciais.")
            break

        payload = safe_json(r)
        if not payload or payload.get("status") != "success":
            print(f"    [mapa] ✗ Página {pagina} retornou payload inválido.")
            break

        dados = payload.get("dados", [])
        paginacao = payload.get("paginacao", {})
        todas.extend(dados)

        total_paginas = paginacao.get("total_de_paginas", 1)
        total_registros = paginacao.get("total_de_registros", "?")
        print(f"    [mapa] ✓ Página {pagina}/{total_paginas} → {len(dados)} unidades "
              f"(acumulado: {len(todas)}/{total_registros})")

        if pagina >= total_paginas:
            break
        pagina += 1

    return todas


def fetch_tabela_preco(id_emp: int, headers_v1: dict, headers_v3: dict) -> dict[str, dict]:
    """
    Busca todas as tabelas de preço aprovadas do empreendimento e retorna
    um dicionário indexado pelo nome da unidade (uppercase) para lookup O(1).

    Quando a mesma unidade aparece em mais de uma tabela, mantém a última
    (tabelas são ordenadas pela API — a mais recente costuma vir por último).
    """
    tabela_por_unidade: dict[str, dict] = {}

    r_tabelas = requests.get(
        f"{BASE}/api/v3/cadastros/empreendimentos/{id_emp}/tabelas-preco",
        headers=headers_v3,
        params={"aprovado": "S"},
    )
    tabelas_resp = safe_json(r_tabelas)
    tabelas = (tabelas_resp or {}).get("data", [])

    if not tabelas:
        print(f"    [tabela] Sem tabelas aprovadas (HTTP {r_tabelas.status_code})")
        return tabela_por_unidade

    print(f"    [tabela] {len(tabelas)} tabela(s) aprovada(s)")

    for tabela in tabelas:
        id_tabela = tabela.get("idtabela")
        nome_tabela = tabela.get("nome", "")

        r_det = requests.get(
            f"{BASE}/api/v1/cadastros/empreendimentos/{id_emp}/tabelasdepreco/{id_tabela}/detalhada",
            headers=headers_v1,
            params={"tabelasemjson": "true"},
        )
        det = safe_json(r_det)
        dados = (det or {}).get("tabelas", {}).get("dados", [])

        if not dados:
            print(f"    [tabela] '{nome_tabela}' sem dados, pulando.")
            continue

        for item in dados:
            chave = str(item.get("unidade", "")).strip().upper()
            series = {s["nome"]: s["valor"] for s in item.get("series", [])}

            tabela_por_unidade[chave] = {
                "TP_TABELA": nome_tabela,
                "TP_SITUACAO": item.get("situacao", ""),
                "TP_AREA_PRIVATIVA": item.get("area_privativa", ""),
                "TP_VALOR_TOTAL": item.get("valor_total", ""),
                **{f"TP_{k}": v for k, v in series.items()},
            }

        print(f"    [tabela] '{nome_tabela}' → {len(dados)} unidades indexadas")

    return tabela_por_unidade


# ---------------------------------------------------------------------------
# Etapa 1: lista todos os empreendimentos
# ---------------------------------------------------------------------------
empreendimentos = safe_json(requests.get(f"{BASE}/api/v1/cadastros/empreendimentos", headers=headers_v1))
if not empreendimentos:
    print("Erro ao buscar empreendimentos.")
    exit()

print(f"Empreendimentos encontrados: {len(empreendimentos)}")

todos_rows = []
log_empreendimentos = []

for emp in empreendimentos:
    id_emp = emp.get("idempreendimento")
    id_emp_sienge = emp.get("idempreendimento_int")
    nome_emp = emp.get("nome", "")

    # if id_emp == 11:
    #     id_emp_sienge = 333

    print(f"\n>>> {nome_emp} (id={id_emp})")

    # --- Etapa 2: mapa de disponibilidade → BASE de todas as unidades ---
    print("  Buscando mapa de disponibilidade...")
    unidades = fetch_mapa_disponibilidade(id_emp)

    if not unidades:
        print("  Sem unidades no mapa, pulando.")
        log_empreendimentos.append({"ID": id_emp, "NOME": nome_emp,
                                    "STATUS": "PULADO", "DETALHE": "Mapa vazio"})
        continue

    print(f"  Total de unidades no mapa: {len(unidades)}")

    # --- Etapa 3: tabela de preço → ENRIQUECIMENTO por unidade ---
    print("  Buscando tabelas de preço...")
    tabela_preco = fetch_tabela_preco(id_emp, headers_v1, headers_v3)
    unidades_com_preco = sum(1 for u in unidades if u.get("unidade", "").strip().upper() in tabela_preco)
    unidades_sem_preco = len(unidades) - unidades_com_preco
    print(f"  Unidades com preço: {unidades_com_preco} | sem preço: {unidades_sem_preco}")

    # --- Etapa 4: monta rows — uma linha por unidade do mapa ---
    for u in unidades:
        nome_unidade = str(u.get("unidade", "")).strip()
        info_tp = tabela_preco.get(nome_unidade.upper(), {})

        row = {
            # --- Identificadores ---
            "ID_EMPREENDIMENTO_CV": id_emp,
            "ID_EMPREENDIMENTO_SIENGE": id_emp_sienge,
            "EMPREENDIMENTO": nome_emp,
            # --- Mapa de disponibilidade (fonte primária) ---
            "CV_IDETAPA": u.get("idetapa"),
            "CV_ETAPA": u.get("etapa"),
            "CV_IDBLOCO": u.get("idbloco"),
            "CV_BLOCO": u.get("bloco"),
            "CV_IDUNIDADE": u.get("idunidade"),
            "CV_IDUNIDADE_INT": u.get("idunidade_int"),
            "CV_UNIDADE": nome_unidade,
            "CV_SITUACAO": u.get("situacao"),
            "CV_DATA_BLOQUEIO": u.get("data_bloqueio"),
            "CV_MOTIVO_BLOQUEIO": u.get("motivo_bloqueio"),
            "CV_DOCUMENTO_BLOQUEIO": u.get("documento_bloqueio"),
            "CV_POSSUI_RESERVA_SOLICITACAO_DISTRATO": u.get("possui_reserva_solicitacao_distrato"),
            # --- Tabela de preço (enriquecimento — vazio se unidade não constar) ---
            **info_tp,
        }
        todos_rows.append(row)

    log_empreendimentos.append({
        "ID": id_emp,
        "NOME": nome_emp,
        "STATUS": "OK",
        "DETALHE": (
            f"{len(unidades)} unidades no mapa | "
            f"{unidades_com_preco} com preço | "
            f"{unidades_sem_preco} sem preço"
        ),
    })

# ---------------------------------------------------------------------------
# Saída
# ---------------------------------------------------------------------------
if todos_rows:
    fieldnames = list(dict.fromkeys(k for row in todos_rows for k in row.keys()))

    output_path = INPUT_DIR / "relatorio_tabela_preco_completo.csv"
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";", extrasaction="ignore")
        writer.writeheader()
        for row in todos_rows:
            writer.writerow(row)

    total_vendidas = sum(1 for r in todos_rows if r.get("CV_SITUACAO") == "Vendida")
    total_bloqueadas = sum(1 for r in todos_rows if r.get("CV_SITUACAO") == "Bloqueada")
    total_disponiveis = sum(1 for r in todos_rows if r.get("CV_SITUACAO") == "Disponível")

    print(f"\n{'=' * 50}")
    print(f"CSV gerado: {output_path}")
    print(f"Total de linhas : {len(todos_rows)}")
    print(f"  Vendidas       : {total_vendidas}")
    print(f"  Bloqueadas     : {total_bloqueadas}")
    print(f"  Disponíveis    : {total_disponiveis}")
    print(f"{'=' * 50}")
else:
    print("\nNenhum dado encontrado.")