"""
stages/transform/contas_recebidas_transformer_2.py
-----------------------------------------------
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
import logging

import numpy as np
import pandas as pd

from stage.transform.utils.normalizer import (
    checar_integridade,
    expandir_dimensao,
    normalizar_colunas,
    salvar_tabela,
    criar_dimensao,
)

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURAÇÃO
# ─────────────────────────────────────────────────────────────────────────────

pasta_origem = Path(__file__).resolve().parents[2]
INPUT_DIR = pasta_origem / "stage" / "transform" / "files" / "input"
REFERENCE_DIR = pasta_origem / "stage" / "transform" / "files" / "reference"
OUTPUT_DIR = pasta_origem / "stage" / "transform" / "files" / "output"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS PRIVADOS
# ─────────────────────────────────────────────────────────────────────────────

def _parse_date(series: pd.Series) -> pd.Series:
    """Tenta ISO 8601 (API) e DD/MM/YYYY (CSV manual)."""

    parsed = pd.to_datetime(series, format="%Y-%m-%d", errors="coerce")

    mask_nat = parsed.isna()
    if mask_nat.any():
        parsed.loc[mask_nat] = pd.to_datetime(
            series.loc[mask_nat],
            format="%d/%m/%Y",
            errors="coerce"
        )

    return parsed


def _faixa_saldo(saldo: pd.Series) -> pd.Series:
    bins = [0, 7000, 15000, 20000, 50000, 100000, float("inf")]
    labels = [
        "A. Até 7 mil", "B. 7 mil a 15 mil", "C. 15 mil a 20 mil",
        "D. 20 mil a 50 mil", "E. 50 mil a 100 mil", "F. Acima de 100 mil",
    ]
    return pd.cut(saldo.fillna(0), bins=bins, labels=labels, right=True)


# ─────────────────────────────────────────────────────────────────────────────
# PONTO DE ENTRADA
# ─────────────────────────────────────────────────────────────────────────────

def executar(input_dir: Path = INPUT_DIR, output_dir: Path = OUTPUT_DIR) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    # ── 1. Leitura ────────────────────────────────────────────────────────────
    print("\n── 1. Leitura ──────────────────────────────────────────────────────")

    df = pd.read_csv((input_dir / "contas_recebidas.csv"), sep=';')
    df = normalizar_colunas(df)

    df['sigla_documento'] = df['sigla_documento'].apply(lambda x: str(x).strip())

    print(f"Total de linhas: {len(df):,}  |  colunas: {len(df.columns)}")

    # Marca origem para rastreabilidade no BI
    df["flag_fonte_api"] = True

    COLUNAS_DATA = [
        "data_vencimento", "data_emissao", "data_contabil", "data_base",
        "data_do_recebimento", "data_do_calculo"
    ]

    for col in COLUNAS_DATA:
        if col in df.columns:
            df[col] = _parse_date(df[col])

    df["titulo"] = pd.to_numeric(df.get("titulo"), errors="coerce").astype("Int64")
    df["cod_empresa"] = pd.to_numeric(df.get("cod_empresa"), errors="coerce").astype("Int64")
    df["cod_cliente"] = pd.to_numeric(df.get("cod_cliente"), errors="coerce").astype("Int64")
    df["cod_centro_de_custo"] = pd.to_numeric(df.get("cod_centro_de_custo"), errors="coerce").astype("Int64")

    # ── 5. Flags calculadas ───────────────────────────────────────────────────
    print("\n── 5. Flags calculadas ─────────────────────────────────────────────")

    df["flag_pago_antecipado"] = (
            df["data_do_recebimento"].notna()
            & df["data_vencimento"].notna()
            & (df["data_do_recebimento"] < df["data_vencimento"])
    )
    df["flag_pago_atraso"] = (
            df["data_do_recebimento"].notna()
            & df["data_vencimento"].notna()
            & (df["data_do_recebimento"] > df["data_vencimento"])
    )

    # ── 6. Campos de pesquisa e prazo ─────────────────────────────────────────
    df["titulo_pesquisa"] = np.where(
        df["titulo"].notna(), "t " + df["titulo"].astype(str), ""
    )

    df["documento_pesquisa"] = df["sigla_documento"].astype(str) + " - " + df["documento"].astype(str)

    df["dias_atraso_pgto"] = (df["data_do_recebimento"] - df["data_vencimento"]).dt.days
    df["dias_emissao_ate_pgto"] = (df["data_do_recebimento"] - df["data_emissao"]).dt.days

    def _faixa_emissao_ate_pgto(dias):
        bins = [-float("inf"), -1, 0, 15, 30, float("inf")]
        labels = [
            "A. Retroativo (pago antes)",
            "B. Mesmo dia",
            "C. 1-15d",
            "D. 16-30d",
            "E. Acima 30d",
        ]

        faixa = pd.cut(dias, bins=bins, labels=labels, right=True)

        return (
            faixa
            .astype("object")
            .fillna("F. Não pago")
        )

    def _faixa_atraso_pgto(dias):
        bins = [-float("inf"), -1, 0, 7, 30, float("inf")]
        labels = ["A. Antecipado", "B. No prazo", "C. Atraso leve (1-7d)", "D. Atraso médio (8-30d)",
                  "E. Atraso grave (30+d)"]
        return pd.cut(dias.fillna(0), bins=bins, labels=labels, right=True).astype(str)

    df["faixa_emissao_ate_pgto"] = _faixa_emissao_ate_pgto(df["dias_emissao_ate_pgto"])
    df["faixa_atraso_pgto"] = _faixa_atraso_pgto(df["dias_atraso_pgto"])

    # ── 7. Dimensões ──────────────────────────────────────────────────────────
    print("\n── 7. Dimensões ────────────────────────────────────────────────────")

    _dim_empresa_path = output_dir / "dim_empresa.csv"
    if _dim_empresa_path.exists():
        dim_empresa = pd.read_csv(_dim_empresa_path, sep=";")
        dim_empresa = expandir_dimensao(
            dim_existente=dim_empresa,
            df_novo=df,
            colunas_naturais=["cod_empresa", "empresa"],
            nome_id="id_empresa",
            col_pk_natural="cod_empresa",
        )
        print(f"  dim_empresa carregada e expandida: {dim_empresa.shape}")
    else:
        print("  dim_empresa.csv não encontrado — criando do zero.")
        dim_empresa = criar_dimensao(
            df[["cod_empresa", "empresa"]].drop_duplicates(subset="cod_empresa"),
            colunas=["cod_empresa", "empresa"],
            nome_id="id_empresa",
        )
        print(f"  dim_empresa criada: {dim_empresa.shape}")

    # ── 8. Surrogate keys ─────────────────────────────────────────────────────
    print("\n── 8. Surrogate keys ───────────────────────────────────────────────")

    _emp_map = dim_empresa.drop_duplicates("cod_empresa").set_index("cod_empresa")["id_empresa"].to_dict()

    df["id_empresa"] = df["cod_empresa"].map(_emp_map)

    # ── 10. Montar fato ───────────────────────────────────────────────────────
    print("\n── 10. fato_consulta_parcela ───────────────────────────────────────")
    print(df.columns)

    fato = df[[
        # Surrogate keys
        "id_empresa",
        # Chaves naturais
        "cod_empresa", "cod_obra", "titulo", "titulo_pesquisa", "parcela", "nn_parcela",
        "sigla_documento", "documento", "nn_documento", "documento_pesquisa", "cod_cliente", "cliente",
        "origem", "cod_plano_fin", "plano_fin",
        # Datas
        "data_vencimento", "data_emissao", "data_contabil",
        "data_base", "data_base_juros", "data_do_recebimento", "data_do_calculo", "data_base_juros",
        # Métricas financeiras
        "valor_bruto", "desconto", "valor_imposto_retido", "saldo_em_aberto",
        "saldo_corrigido_em_aberto", "juros_embutidos", "taxa_juros", "valor_recebido", "juros_recebidos",
        "multa_recebida",
        "desconto_recebido", "imposto_retido_recebido", "valor_liquido_recebido", "acrescimo_recebido",
        "%_apropriacao_financeira",

        # Prazo
        "dias_atraso_pgto", "dias_emissao_ate_pgto", "faixa_emissao_ate_pgto", "faixa_atraso_pgto",
        # Flags
        "flag_fonte_api", "flag_pago_antecipado", "flag_pago_atraso",

        # Atributos de workflow / auditoria
        "situacao_inadimplencia", "forma_de_pagamento", "tipo_de_operacao", "conta_corrente", "indexador",

        "cod_centro_de_custo", "centro_de_custo"
    ]].copy()

    fato["data_carga"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ── 11. Validação ─────────────────────────────────────────────────────────
    print("\n── 11. Validação ───────────────────────────────────────────────────")
    checar_integridade(fato, "id_empresa", dim_empresa, "id_empresa", "fato → dim_empresa")

    # ── 12. Exportação ────────────────────────────────────────────────────────
    print("\n── 12. Exportação ──────────────────────────────────────────────────")
    salvar_tabela(dim_empresa, "dim_empresa", output_dir)
    salvar_tabela(fato, "fato_contas_recebidas", output_dir)

    print("\n── Resumo ──────────────────────────────────────────────────────────")
    for nome, tab in {
        "dim_empresa": dim_empresa,
        "fato_contas_recebidas": fato,
    }.items():
        print(f"  {nome:<35} {str(tab.shape):>12}")
