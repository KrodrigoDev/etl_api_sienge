"""
stages/transform/transform_consulta_parcela.py
-----------------------------------------------
Versão adaptada para fonte via API (bulk-data/v1/outcome).

Diferenças em relação à versão com CSV manual:
  - Campos inexistentes no bulk endpoint são inicializados como NA
    e sinalizados com flag_fonte_api = True para rastreabilidade.
  - status_da_parcela, dias_de_atraso e diferenca_data_vencimento
    são calculados aqui (não vêm prontos da API).
  - _parse_banco / _parse_pix removidos (campos não disponíveis).
  - dim_fornecedor simplificada (sem banco/PIX).

Campos indisponíveis no bulk (criados como NA):
  chave_nfe, ciencia_do_titulo, cnpj/cpf, conta_contabil,
  data_de_alteracao, data_de_competencia, forma_de_pagamento,
  informacoes_bancarias_do_credor, nn_lote, observacao_do_titulo,
  parcela_agrupada, pix_do_credor, status_do_lote, tipo_credor,
  tipo_de_baixa, titulo/parcela_agrupada, usuario_que_alterou,
  usuario_que_autorizou, usuario_que_deu_ciencia, vencimento_original
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from stage.transform.utils.normalizer import (
    checar_integridade,
    converter_valor_br,
    expandir_dimensao,
    ler_dados,
    normalizar_colunas,
    salvar_tabela,
    criar_dimensao,
)

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURAÇÃO
# ─────────────────────────────────────────────────────────────────────────────

pasta_origem = Path(__file__).resolve().parents[2]
INPUT_DIR  = pasta_origem / "stage" / "transform" / "files" / "input"
OUTPUT_DIR = pasta_origem / "stage" / "transform" / "files" / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Campos que o bulk endpoint não fornece — serão criados como NA
COLUNAS_INDISPONIVEIS_API = [
    "chave_nfe",
    "ciencia_do_titulo",
    "cnpj/cpf",
    "conta_contabil",
    "data_de_alteracao",
    "data_de_competencia",
    "forma_de_pagamento",
    "informacoes_bancarias_do_credor",
    "nn_lote",
    "observacao_do_titulo",
    "parcela_agrupada",
    "pix_do_credor",
    "status_do_lote",
    "tipo_credor",
    "tipo_de_baixa",
    "titulo/parcela_agrupada",
    "usuario_que_alterou",
    "usuario_que_autorizou",
    "usuario_que_deu_ciencia",
    "vencimento_original",
]


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS PRIVADOS
# ─────────────────────────────────────────────────────────────────────────────

def _parse_date(series: pd.Series) -> pd.Series:
    """Tenta ISO 8601 (API) e DD/MM/YYYY (CSV manual) — aceita os dois."""
    parsed = pd.to_datetime(series, format="%Y-%m-%d", errors="coerce")
    mask_nat = parsed.isna()
    if mask_nat.any():
        parsed[mask_nat] = pd.to_datetime(
            series[mask_nat], format="%d/%m/%Y", errors="coerce"
        )
    return parsed


def _calcular_status_parcela(df: pd.DataFrame, hoje: date) -> pd.Series:
    """
    Deriva status_da_parcela a partir dos campos disponíveis na API.

    Regra:
      - data_do_pagamento preenchida                      → PAGA
      - data_vencimento < hoje  e sem pagamento           → VENCIDA
      - data_vencimento >= hoje e sem pagamento           → A_VENCER
    """
    hoje_ts = pd.Timestamp(hoje)
    status = pd.Series("A_VENCER", index=df.index)
    status[df["data_vencimento"] < hoje_ts] = "VENCIDA"
    status[df["data_do_pagamento"].notna()] = "PAGA"
    return status


def _faixa_atraso(dias: pd.Series) -> pd.Series:
    bins   = [-1, 0, 7, 14, 21, 28, float("inf")]
    labels = ["Em dia", "1-7d", "8-14d", "15-21d", "22-28d", "29+d"]
    return pd.cut(dias.fillna(0), bins=bins, labels=labels, right=True)


def _faixa_saldo(saldo: pd.Series) -> pd.Series:
    bins   = [0, 7000, 15000, 20000, 50000, 100000, float("inf")]
    labels = [
        "A. Até 7 mil", "B. 7 mil a 15 mil", "C. 15 mil a 20 mil",
        "D. 20 mil a 50 mil", "E. 50 mil a 100 mil", "F. Acima de 100 mil",
    ]
    return pd.cut(saldo.fillna(0), bins=bins, labels=labels, right=True)


# ─────────────────────────────────────────────────────────────────────────────
# PONTO DE ENTRADA
# ─────────────────────────────────────────────────────────────────────────────

def executar(input_dir: Path = INPUT_DIR, output_dir: Path = OUTPUT_DIR) -> None:

    hoje = date.today()

    # ── 1. Leitura ────────────────────────────────────────────────────────────
    print("\n── 1. Leitura ──────────────────────────────────────────────────────")

    df = pd.read_csv((input_dir / "contas_pagas.csv"), sep=';')
    df = normalizar_colunas(df)

    print(f"Total de linhas: {len(df):,}  |  colunas: {len(df.columns)}")

    # Inicializa campos ausentes da API como NA
    for col in COLUNAS_INDISPONIVEIS_API:
        if col not in df.columns:
            df[col] = pd.NA

    # Marca origem para rastreabilidade no BI
    df["flag_fonte_api"] = True

    # ── 2. Deduplicação ───────────────────────────────────────────────────────
    print(f"  Antes dedup:  {df.shape}")
    df = df.drop_duplicates(
        subset=["grupo", "cod_empresa", "documento", "cod_credor", "titulo"]
    ).reset_index(drop=True)
    print(f"  Após dedup:   {df.shape}")

    # ── 3. Conversão de tipos ─────────────────────────────────────────────────
    print("\n── 3. Conversão de tipos ───────────────────────────────────────────")

    COLUNAS_VALOR = [
        "valor_no_vencimento", "valor_bruto", "acrescimo", "desconto",
        "valor_imposto_retido", "valor_liquido", "valor_da_baixa", "saldo_em_aberto",
    ]
    for col in COLUNAS_VALOR:
        if col in df.columns:
            # API já entrega float; converter_valor_br trata os dois formatos
            df[col] = converter_valor_br(df[col])

    COLUNAS_DATA = [
        "data_vencimento", "data_do_pagamento", "data_base", "data_emissao",
        "data_de_cadastro", "data_contabil", "data_do_calculo",
        # abaixo são NA vindos da API, mas _parse_date tolera NaT
        "data_de_alteracao", "data_de_competencia", "vencimento_original",
    ]
    for col in COLUNAS_DATA:
        if col in df.columns:
            df[col] = _parse_date(df[col])

    df["titulo"]      = pd.to_numeric(df.get("titulo"),      errors="coerce").astype("Int64")
    df["cod_empresa"] = pd.to_numeric(df.get("cod_empresa"), errors="coerce").astype("Int64")
    df["cod_credor"]  = pd.to_numeric(df.get("cod_credor"),  errors="coerce").astype("Int64")

    print(f"  saldo_em_aberto max: R$ {df['saldo_em_aberto'].max():,.2f}")

    # ── 4. Campos calculados (substitutos dos que a API não entrega) ──────────
    print("\n── 4. Campos calculados ────────────────────────────────────────────")

    # status_da_parcela — derivado de data_do_pagamento + data_vencimento
    df["status_da_parcela"] = _calcular_status_parcela(df, hoje)

    # dias_de_atraso — só faz sentido para VENCIDA
    hoje_ts = pd.Timestamp(hoje)
    df["dias_de_atraso"] = (
        (hoje_ts - df["data_vencimento"])
        .dt.days
        .where(df["status_da_parcela"] == "VENCIDA", other=0)
        .fillna(0)
        .astype(int)
    )

    # diferenca_data_vencimento — indisponível sem vencimento_original; deixa 0
    df["diferenca_data_vencimento"] = (
        (df["data_vencimento"] - df["vencimento_original"])
        .dt.days
        .fillna(0)
        .astype(int)
        if df["vencimento_original"].notna().any()
        else 0
    )

    print(f"  PAGA:     {(df['status_da_parcela']=='PAGA').sum():,}")
    print(f"  VENCIDA:  {(df['status_da_parcela']=='VENCIDA').sum():,}")
    print(f"  A_VENCER: {(df['status_da_parcela']=='A_VENCER').sum():,}")

    # ── 5. Flags calculadas ───────────────────────────────────────────────────
    print("\n── 5. Flags calculadas ─────────────────────────────────────────────")

    data_ontem = hoje_ts - pd.Timedelta(days=1)

    df["flag_vencida"]         = df["status_da_parcela"] == "VENCIDA"
    df["flag_a_vencer"]        = df["status_da_parcela"] == "A_VENCER"
    df["flag_paga"]            = df["status_da_parcela"] == "PAGA"
    df["flag_vence_hoje"]      = df["data_vencimento"].dt.normalize() == hoje_ts.normalize()
    df["flag_pago_antecipado"] = (
        df["data_do_pagamento"].notna()
        & df["data_vencimento"].notna()
        & (df["data_do_pagamento"] < df["data_vencimento"])
    )
    df["flag_pago_atraso"] = (
        df["data_do_pagamento"].notna()
        & df["data_vencimento"].notna()
        & (df["data_do_pagamento"] > df["data_vencimento"])
    )
    # tipo_de_baixa indisponível → flag sempre False
    df["flag_substituida"]     = False
    df["flag_critico"]         = df["dias_de_atraso"] >= 15
    df["flag_sem_credor"]      = df["cod_credor"].isna()
    df["flag_sem_obra"]        = df.get("cod_obra", pd.Series(pd.NA, index=df.index)).isna()
    df["flag_autorizada"]      = (
        df.get("parcela_autorizada", pd.Series("", index=df.index))
        .astype(str).str.strip().str.lower() == "sim"
    )
    df["flag_venc_fds"] = df["data_vencimento"].dt.dayofweek.isin([5, 6])

    dias_ajuste = (
        df["data_vencimento"].dt.dayofweek
        .map({5: 2, 6: 1})
        .fillna(0)
        .astype(int)
    )
    df["proximo_util_apos_fds"] = df["data_vencimento"] + pd.to_timedelta(dias_ajuste, unit="D")
    df["flag_venc_fds_paga_hoje"] = (
        df["flag_venc_fds"]
        & (df["proximo_util_apos_fds"].dt.normalize() == hoje_ts.normalize())
        & df["flag_vencida"]
    )
    df["flag_venceu_ontem"] = df["data_vencimento"].dt.normalize() == data_ontem.normalize()
    df["flag_operacao_hoje"] = (
        df["flag_vence_hoje"]
        | (
            df["flag_venc_fds"]
            & (df["proximo_util_apos_fds"].dt.normalize() == hoje_ts.normalize())
            & ~df["flag_paga"]
        )
    )

    df["faixa_atraso"] = _faixa_atraso(df["dias_de_atraso"]).astype(str)
    df["faixa_saldo"]  = _faixa_saldo(df["saldo_em_aberto"])

    print(f"  flag_vencida:         {df['flag_vencida'].sum():,}")
    print(f"  flag_vence_hoje:      {df['flag_vence_hoje'].sum():,}")
    print(f"  flag_pago_antecipado: {df['flag_pago_antecipado'].sum():,}")
    print(f"  flag_critico (≥15d):  {df['flag_critico'].sum():,}")
    print(f"  flag_sem_credor:      {df['flag_sem_credor'].sum():,}")

    # ── 6. Campos de pesquisa e prazo ─────────────────────────────────────────
    df["nn_lote_pesquisa"] = np.where(
        df["nn_lote"].notna(), "nº " + df["nn_lote"].astype(str), ""
    )
    df["titulo_pesquisa"] = np.where(
        df["titulo"].notna(), "t " + df["titulo"].astype(str), ""
    )
    df["dias_titulo_c_obra"]       = (df["data_de_cadastro"] - df["data_emissao"]).dt.days
    df["dias_ate_vencimento"]      = (df["data_vencimento"]  - df["data_de_cadastro"]).dt.days
    df["dias_atraso_pgto"]         = (df["data_do_pagamento"] - df["data_vencimento"]).dt.days
    df["dias_lancamento_ate_pgto"] = (df["data_do_pagamento"] - df["data_de_cadastro"]).dt.days

    def _faixa_titulo_c_obra(dias):
        bins   = [-1, 7, 15, 30, 60, float("inf")]
        labels = ["A. Até 7d", "B. 8-15d", "C. 16-30d", "D. 31-60d", "E. Acima 60d"]
        return pd.cut(dias.fillna(0), bins=bins, labels=labels, right=True).astype(str)

    def _faixa_lancamento_ate_pgto(dias):
        bins   = [-float("inf"), -1, 0, 15, 30, float("inf")]
        labels = ["A. Retroativo (pago antes)", "B. Mesmo dia", "C. 1-15d", "D. 16-30d", "E. Acima 30d"]
        return pd.cut(dias.fillna(0), bins=bins, labels=labels, right=True).astype(str)

    def _faixa_atraso_pgto(dias):
        bins   = [-float("inf"), -1, 0, 7, 30, float("inf")]
        labels = ["A. Antecipado", "B. No prazo", "C. Atraso leve (1-7d)", "D. Atraso médio (8-30d)", "E. Atraso grave (30+d)"]
        return pd.cut(dias.fillna(0), bins=bins, labels=labels, right=True).astype(str)

    df["faixa_titulo_c_obra"]        = _faixa_titulo_c_obra(df["dias_titulo_c_obra"])
    df["faixa_lancamento_ate_pgto"]  = _faixa_lancamento_ate_pgto(df["dias_lancamento_ate_pgto"])
    df["faixa_atraso_pgto"]          = _faixa_atraso_pgto(df["dias_atraso_pgto"])
    df["flag_lancamento_retroativo"] = (
        df["dias_lancamento_ate_pgto"].notna() & (df["dias_lancamento_ate_pgto"] < 0)
    )

    # ── 7. Dimensões ──────────────────────────────────────────────────────────
    print("\n── 7. Dimensões ────────────────────────────────────────────────────")

    dim_empresa = pd.read_csv(output_dir / "dim_empresa.csv", sep=";")
    dim_empresa = expandir_dimensao(
        dim_existente=dim_empresa,
        df_novo=df.rename(columns={"cod_empresa": "cod_empresa", "empresa": "empresa"}),
        colunas_naturais=["cod_empresa", "empresa"],
        nome_id="id_empresa",
        col_pk_natural="cod_empresa",
    )
    print(f"  dim_empresa: {dim_empresa.shape}")

    # dim_fornecedor — sem banco/PIX (não disponíveis na API bulk)
    dim_fornecedor = (
        df[df["cod_credor"].notna()]
        [["cod_credor", "credor"]]
        .drop_duplicates(subset="cod_credor", keep="last")
        .rename(columns={"credor": "nome_fornecedor"})
    )
    CREDOR_INTERNO = pd.DataFrame([{
        "cod_credor": 0, "nome_fornecedor": "INTERNO",
    }])
    dim_fornecedor = pd.concat([CREDOR_INTERNO, dim_fornecedor], ignore_index=True)
    dim_fornecedor["cod_credor"] = dim_fornecedor["cod_credor"].astype("Int64")
    dim_fornecedor = criar_dimensao(
        dim_fornecedor, colunas=["cod_credor", "nome_fornecedor"], nome_id="id_fornecedor"
    )

    # dim_status (domínio fixo)
    dim_status = pd.DataFrame([
        {"id_status": 1, "status_parcela": "PAGA",      "grupo_status": "Quitado"},
        {"id_status": 2, "status_parcela": "VENCIDA",   "grupo_status": "Inadimplente"},
        {"id_status": 3, "status_parcela": "A_VENCER",  "grupo_status": "Em dia"},
        {"id_status": 0, "status_parcela": "SEM_STATUS","grupo_status": "Indefinido"},
    ])

    # tipo_de_baixa indisponível → dimensão com apenas "SEM_DADO"
    dim_tipo_baixa = pd.DataFrame([
        {"id_tipo_baixa": 0, "tipo_baixa": "SEM_DADO", "descricao": "Não disponível via API bulk"},
    ])

    origens = df["origem"].dropna().unique().tolist()
    dim_origem = pd.DataFrame({"id_origem": range(1, len(origens)+1), "origem": origens})

    # forma_de_pagamento indisponível → dimensão vazia
    dim_forma_pagamento = pd.DataFrame(columns=["id_forma_pagamento", "forma_pagamento"])

    # ── 8. Surrogate keys ─────────────────────────────────────────────────────
    print("\n── 8. Surrogate keys ───────────────────────────────────────────────")

    _emp_map    = dim_empresa.drop_duplicates("cod_empresa").set_index("cod_empresa")["id_empresa"].to_dict()
    _forn_map   = dim_fornecedor.drop_duplicates("cod_credor").set_index("cod_credor")["id_fornecedor"].to_dict()
    _status_map = dim_status.set_index("status_parcela")["id_status"].to_dict()
    _origem_map = dim_origem.set_index("origem")["id_origem"].to_dict()

    df["cod_credor_lookup"] = df["cod_credor"].fillna(0).astype(int)
    df["id_empresa"]        = df["cod_empresa"].map(_emp_map)
    df["id_fornecedor"]     = df["cod_credor_lookup"].map(_forn_map)
    df["id_status"]         = df["status_da_parcela"].map(_status_map).fillna(0).astype(int)
    df["id_tipo_baixa"]     = 0   # indisponível
    df["id_origem"]         = df["origem"].map(_origem_map)
    df["id_forma_pagamento"]= pd.NA  # indisponível

    for col_id in ("id_empresa", "id_fornecedor", "id_status", "id_origem"):
        n = df[col_id].notna().sum()
        print(f"  {col_id:<22} {n:,} / {len(df):,}  ({n/len(df):.1%})")

    # ── 9. Faixa saldo por fornecedor ─────────────────────────────────────────
    _saldo_forn_map = df.groupby("id_fornecedor")["saldo_em_aberto"].sum().to_dict()
    df["saldo_total_fornecedor"]  = df["id_fornecedor"].map(_saldo_forn_map)
    df["faixa_saldo_fornecedor"]  = _faixa_saldo(df["saldo_total_fornecedor"]).astype(str)

    # ── 10. Montar fato ───────────────────────────────────────────────────────
    print("\n── 10. fato_consulta_parcela ───────────────────────────────────────")

    fato = df[[
        # Surrogate keys
        "id_empresa", "id_fornecedor", "id_status", "id_tipo_baixa",
        "id_origem", "id_forma_pagamento",
        # Chaves naturais
        "cod_empresa", "cod_credor", "titulo", "parcela", "grupo",
        "documento", "nn_documento", "conta_contabil",
        # Datas
        "data_vencimento", "data_do_pagamento", "data_emissao",
        "data_de_competencia", "data_contabil", "data_de_cadastro", "vencimento_original",
        # Métricas financeiras
        "valor_no_vencimento", "valor_bruto", "acrescimo", "desconto",
        "valor_imposto_retido", "valor_liquido", "valor_da_baixa", "saldo_em_aberto",
        # Prazo
        "dias_de_atraso", "diferenca_data_vencimento",
        "faixa_atraso", "faixa_saldo", "faixa_saldo_fornecedor", "saldo_total_fornecedor",
        "dias_titulo_c_obra", "dias_ate_vencimento", "dias_atraso_pgto",
        "dias_lancamento_ate_pgto", "faixa_titulo_c_obra",
        "faixa_lancamento_ate_pgto", "faixa_atraso_pgto",
        # Flags
        "flag_vencida", "flag_a_vencer", "flag_paga", "flag_vence_hoje",
        "flag_pago_antecipado", "flag_pago_atraso", "flag_substituida",
        "flag_critico", "flag_sem_credor", "flag_sem_obra", "flag_autorizada",
        "flag_venc_fds", "proximo_util_apos_fds", "flag_venc_fds_paga_hoje",
        "flag_venceu_ontem", "flag_operacao_hoje", "flag_lancamento_retroativo",
        "flag_fonte_api",
        # Atributos de workflow / auditoria
        "ciencia_do_titulo", "parcela_autorizada", "parcela_agrupada",
        "titulo/parcela_agrupada", "nn_lote", "status_do_lote", "indexador",
        "tipo_de_operacao", "historico", "chave_nfe", "autenticacao_eletronica",
        "usuario_que_deu_ciencia", "usuario_que_autorizou",
        "usuario_que_cadastrou", "usuario_que_alterou",
        "observacao_do_titulo", "descricao_do_pagamento",
        "titulo_pesquisa", "nn_lote_pesquisa",
    ]].copy()

    # ── 10.5 Enriquecimento cod_obra / chave_cc ───────────────────────────────
    print("\n── 10.5. Enriquecimento cod_obra / chave_cc ────────────────────────")

    dim_titulo_obra_dedup = pd.read_csv(output_dir / "dim_titulo_obra_dedup.csv", sep=";")
    _dedup_join = (
        dim_titulo_obra_dedup[["titulo", "cod_obra", "obra"]]
        .drop_duplicates(subset="titulo")
        .copy()
    )
    _dedup_join["titulo"]   = pd.to_numeric(_dedup_join["titulo"],   errors="coerce").astype("Int64")
    _dedup_join["cod_obra"] = pd.to_numeric(_dedup_join["cod_obra"], errors="coerce").astype("Int64")

    fato = fato.merge(_dedup_join, on="titulo", how="left", suffixes=("", "_dedup"))

    dim_conta_cc = pd.read_excel(INPUT_DIR / "reference/dim_conta_cc.xlsx", sheet_name="conta_cc")
    dim_conta_cc = dim_conta_cc.dropna(subset=["cod_obra"])
    dim_conta_cc["cod_obra"] = dim_conta_cc["cod_obra"].astype(int)
    dim_conta_cc["chave_cc_preview"] = dim_conta_cc.apply(
        lambda x: str(x["cod_obra"]).strip()
        if pd.isna(x["tipo_documento"])
        else f"{x['cod_obra']}_{x['tipo_documento']}".strip(),
        axis=1,
    )

    cod_obras_especiais_str = set(
        dim_conta_cc.loc[~dim_conta_cc["tipo_documento"].isna(), "cod_obra"]
        .astype(int).astype(str)
    )
    DOCS_ESPECIAIS: set[str] = {"FL", "TRCT"}

    _cod_obra_str = fato["cod_obra"].apply(lambda x: str(int(x)) if pd.notna(x) else pd.NA)
    _doc_upper    = fato["documento"].fillna("").str.strip().str.upper()
    _tem_obra     = fato["cod_obra"].notna()
    _doc_especial = _doc_upper.isin(DOCS_ESPECIAIS)

    fato["chave_cc"] = pd.NA
    fato.loc[_tem_obra, "chave_cc"] = _cod_obra_str[_tem_obra]
    mask_composta = _tem_obra & _doc_especial & _cod_obra_str.isin(cod_obras_especiais_str)
    fato.loc[mask_composta, "chave_cc"] = _cod_obra_str[mask_composta] + "_" + _doc_upper[mask_composta]

    fato["flag_sem_conta_mapeada"] = fato["chave_cc"].isna()
    fato["data_carga"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print(f"  fato_consulta_parcela: {fato.shape}")
    print(f"  PAGA:     {fato['flag_paga'].sum():,}")
    print(f"  VENCIDA:  {fato['flag_vencida'].sum():,}")
    print(f"  A_VENCER: {fato['flag_a_vencer'].sum():,}")
    print(f"  Saldo vencido: R$ {fato.loc[fato['flag_vencida'], 'saldo_em_aberto'].sum():,.2f}")

    # ── 11. Validação ─────────────────────────────────────────────────────────
    print("\n── 11. Validação ───────────────────────────────────────────────────")
    checar_integridade(fato, "id_empresa",    dim_empresa,    "id_empresa",    "fato → dim_empresa")
    checar_integridade(fato, "id_fornecedor", dim_fornecedor, "id_fornecedor", "fato → dim_fornecedor")
    checar_integridade(fato, "id_status",     dim_status,     "id_status",     "fato → dim_status")
    checar_integridade(fato, "id_origem",     dim_origem,     "id_origem",     "fato → dim_origem")

    # ── 12. Exportação ────────────────────────────────────────────────────────
    print("\n── 12. Exportação ──────────────────────────────────────────────────")
    salvar_tabela(dim_empresa,          "dim_empresa",                       output_dir)
    salvar_tabela(dim_fornecedor,       "dim_fornecedor_consulta_parcela",   output_dir)
    salvar_tabela(dim_status,           "dim_status",                        output_dir)
    salvar_tabela(dim_tipo_baixa,       "dim_tipo_baixa",                    output_dir)
    salvar_tabela(dim_origem,           "dim_origem",                        output_dir)
    salvar_tabela(dim_forma_pagamento,  "dim_forma_pagamento",               output_dir)
    salvar_tabela(dim_conta_cc,         "dim_conta_cc",                      output_dir)
    salvar_tabela(fato,                 "fato_consulta_parcela",             output_dir)

    print("\n── Resumo ──────────────────────────────────────────────────────────")
    for nome, tab in {
        "dim_empresa":          dim_empresa,
        "dim_fornecedor":       dim_fornecedor,
        "dim_status":           dim_status,
        "dim_tipo_baixa":       dim_tipo_baixa,
        "dim_origem":           dim_origem,
        "dim_forma_pagamento":  dim_forma_pagamento,
        "fato_consulta_parcela": fato,
    }.items():
        print(f"  {nome:<35} {str(tab.shape):>12}")


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    executar()