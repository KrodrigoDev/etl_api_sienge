"""
stages/transform/contas_a_receber_transformer_2.py
-----------------------------------------------
"""

from __future__ import annotations

from datetime import datetime
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
            errors="coerce",
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
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # ── 1. Leitura ────────────────────────────────────────────────────────────
    print("\n── 1. Leitura ──────────────────────────────────────────────────────")

    df = pd.read_csv(input_dir / "contas_a_receber.csv", sep=";")
    df = normalizar_colunas(df)

    df["cod_centro_de_custo"] = (
        df["cod_centro_de_custo"]
        .replace("", np.nan)
        .fillna(df["cod_centro_de_custo_(rc)"])
    )

    df["centro_de_custo"] = (
        df["centro_de_custo"]
        .replace("", np.nan)
        .fillna(df["centro_de_custo_(rc)"])
    )

    df["sigla_documento"] = df["sigla_documento"].apply(lambda x: str(x).strip())

    print(f"Total de linhas: {len(df):,}  |  colunas: {len(df.columns)}")

    # Marca origem para rastreabilidade no BI
    df["flag_fonte_api"] = True

    # ── 2. Datas ──────────────────────────────────────────────────────────────
    COLUNAS_DATA = [
        "data_vencimento", "data_emissao", "data_contabil", "data_base",
        "data_do_recebimento", "data_do_calculo",
    ]

    for col in COLUNAS_DATA:
        if col in df.columns:
            df[col] = _parse_date(df[col])

    # ── 3. Tipos numéricos ────────────────────────────────────────────────────
    df["titulo"] = pd.to_numeric(df.get("titulo"), errors="coerce").astype("Int64")
    df["cod_empresa"] = pd.to_numeric(df.get("cod_empresa"), errors="coerce").astype("Int64")
    df["cod_cliente"] = pd.to_numeric(df.get("cod_cliente"), errors="coerce").astype("Int64")
    df["cod_centro_de_custo"] = pd.to_numeric(df.get("cod_centro_de_custo"), errors="coerce").astype("Int64")


    # ── 5. Campos de pesquisa e prazo ─────────────────────────────────────────
    print("\n── 5. Campos de pesquisa e prazo ───────────────────────────────────")

    df["titulo_pesquisa"] = np.where(
        df["titulo"].notna(), "t " + df["titulo"].astype(str), ""
    )

    df["documento_pesquisa"] = (
        df["sigla_documento"].astype(str) + " - " + df["documento"].astype(str)
    )

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

    _dim_documento_path = output_dir / "dim_documento.csv"
    if _dim_documento_path.exists():
        dim_documento = pd.read_csv(_dim_documento_path, sep=";")
        dim_documento = expandir_dimensao(
            dim_existente=dim_documento,
            df_novo=df,
            colunas_naturais=["sigla_documento", "documento", 'documento_pesquisa'],
            nome_id="id_documento",
            col_pk_natural="documento",
        )
        print(f"  dim_empresa carregada e expandida: {dim_documento.shape}")
    else:
        print("  dim_empresa.csv não encontrado — criando do zero.")
        dim_documento = criar_dimensao(
            df,
            colunas=["sigla_documento", "documento", 'documento_pesquisa'],
            nome_id="id_documento",
        )
        print(f"  dim_empresa criada: {dim_empresa.shape}")

    # ── Mapeamento Forma de Pagamento ───────────────────────────────────────────

    MAPEAMENTO_FORMA_PAGAMENTO = {
        "Permuta": ("PE", "Outros"),
        "Atualização Financiamento": ("AF", "Carteira Direta"),
        "Entrega das chaves": ("CH", "Carteira Direta"),
        "Parcelas Mensais": ("PM", "Carteira Direta"),
        "Juros Obra": ("JO", "Carteira Direta"),
        "Taxas de ITBI e Cartório": ("IC", "Outros"),
        "Sinal": ("SI", "Carteira Direta"),
        "Parcelas Semestrais": ("PS", "Carteira Direta"),
        "Parcela Mensal Cheque": ("CQ", "Carteira Direta"),
        "Parcelas Anuais": ("PA", "Carteira Direta"),
        "Juros Obra Cartão Crédito": ("JC", "Carteira Direta"),
        "Parcela Mensal Cartão Cred.": ("CC", "Carteira Direta"),
        "Sinal Intercalado": ("IT", "Carteira Direta"),
        "FGTS": ("FG", "CEF"),
        "Financiamento": ("FI", "CEF"),
        "Subsidio Governo": ("SG", "CEF"),
        "IPTU": ("IP", "Outros"),
        "Adesão Parcelas Mensais": ("AM", "Carteira Direta"),
        "Assistencia Tecnica": ("ST", "Outros"),
        "Parcelas Trimestrais": ("PT", "Carteira Direta"),
        "Sinal Cartão de Credito": ("SC", "Carteira Direta"),
        "Parcela Unica": ("PU", "Carteira Direta"),
        "Ato": ("AT", "Carteira Direta"),
        "Atualização Financiamento C. C": ("AC", "Carteira Direta"),
        "Parcelas Bimestrais": ("PB", "Carteira Direta"),
        "REMUNERAÇÃO PJ": ("PJ", "Outros"),
        "RECEBIMENTO INDEVIDO": ("RI", "Outros"),
        "Taxa a vista Caixa": ("TC", "Outros"),
        "APORTE DE SÓCIOS": ("AP", "Outros"),
        "ALTERAÇÃO DE PROJETO/REFORMA": ("AR", "Outros"),
        "Adesão Sinal de entrada": ("AS", "Carteira Direta"),
        "PRODUTO DE VENDA": ("PV", "Outros"),
        "Sinal de Arras": ("SA", "Carteira Direta"),
        "Resíduo": ("RS", "Carteira Direta"),
        "Parcelas Mensais Pró Soluto": ("PMPS", "Carteira Direta"),
        "Parcelas Mensais Iniciais": ("PMI", "Carteira Direta"),
        "Desconto Promocional": ("DCP", "Carteira Direta")
    }

    # Cria as colunas no dataframe origem
    df["abreviacao_forma_pagamento"] = (
        df["forma_de_pagamento"]
        .map(lambda x: MAPEAMENTO_FORMA_PAGAMENTO.get(x, (None, None))[0])
    )

    df["tipo_receita"] = (
        df["forma_de_pagamento"]
        .map(lambda x: MAPEAMENTO_FORMA_PAGAMENTO.get(x, (None, None))[1])
    )

    # Opcional: identificar valores sem mapeamento
    nao_mapeados = sorted(
        df.loc[df["abreviacao_forma_pagamento"].isna(), "forma_de_pagamento"]
        .dropna()
        .unique()
    )

    if nao_mapeados:
        print("\nFormas de pagamento sem mapeamento:")
        for item in nao_mapeados:
            print(f"  - {item}")

    _dim_forma_pagamento = output_dir / "dim_forma_pagamento.csv"

    if _dim_forma_pagamento.exists():
        forma_pagamento = pd.read_csv(_dim_forma_pagamento, sep=";")
        forma_pagamento = expandir_dimensao(
            dim_existente=forma_pagamento,
            df_novo=df,
            colunas_naturais=["forma_de_pagamento","abreviacao_forma_pagamento","tipo_receita"],
            nome_id="id_forma_de_pagamento",
            col_pk_natural="forma_de_pagamento",
        )

        print(f"  dim_empresa carregada e expandida: {forma_pagamento.shape}")
    else:
        print("  dim_empresa.csv não encontrado — criando do zero.")
        forma_pagamento = criar_dimensao(
            df,
            colunas=["forma_de_pagamento","abreviacao_forma_pagamento","tipo_receita"],
            nome_id="id_forma_de_pagamento",
        )
        print(f"  dim_empresa criada: {forma_pagamento.shape}")

    _dim_cliente = output_dir / "dim_cliente.csv"
    if _dim_cliente.exists():
        dim_cliente = pd.read_csv(_dim_cliente, sep=";")
        dim_cliente = expandir_dimensao(
            dim_existente=dim_cliente,
            df_novo=df,
            colunas_naturais=["cod_cliente", "cliente"],
            nome_id="id_cliente",
            col_pk_natural="cod_cliente",
        )
        print(f"  dim_empresa carregada e expandida: {dim_cliente.shape}")
    else:
        print("  dim_empresa.csv não encontrado — criando do zero.")
        dim_cliente = criar_dimensao(
            df,
            colunas=["cod_cliente", "cliente"],
            nome_id="id_cliente",
        )
        print(f"  dim_empresa criada: {dim_cliente.shape}")

    df_auxiliar_centro = pd.read_csv((REFERENCE_DIR / 'auxiliar_gabriel.csv'), sep=',')
    df = df.merge(
        df_auxiliar_centro, left_on='cod_centro_de_custo', right_on='Cod. Centro de Custo', how='left'
    )

    _dim_centro_custo = output_dir / "dim_centro_custo.csv"

    if _dim_centro_custo.exists():
        dim_centro_custo = pd.read_csv(_dim_centro_custo, sep=";")

        dim_centro_custo = expandir_dimensao(
            dim_existente=dim_centro_custo,
            df_novo=df,
            colunas_naturais=["cod_centro_de_custo", "centro_de_custo", "Centro de Custo 2", "Tipo de Obra",
                              "Tipo de Obra 2 "],
            nome_id="id_centro_de_custo",
            col_pk_natural="cod_centro_de_custo",
        )
        print(f"  dim_empresa carregada e expandida: {dim_centro_custo.shape}")
    else:
        print("  dim_empresa.csv não encontrado — criando do zero.")
        dim_centro_custo = criar_dimensao(
            df,
            colunas=["cod_centro_de_custo", "centro_de_custo"],
            nome_id="id_centro_de_custo",
        )
        print(f"  dim_empresa criada: {dim_centro_custo.shape}")

    dim_centro_custo = dim_centro_custo[['id_centro_de_custo', "cod_centro_de_custo",
                                         "centro_de_custo", 'Centro de Custo 2',
                                         'Tipo de Obra', 'Tipo de Obra 2 ']]

    # ── 8. Surrogate keys ─────────────────────────────────────────────────────

    print("\n── 8. Surrogate keys ───────────────────────────────────────────────")

    _emp_map = (
        dim_empresa
        .drop_duplicates("cod_empresa")
        .set_index("cod_empresa")["id_empresa"]
        .to_dict()
    )

    _doc_map = (
        dim_documento
        .drop_duplicates("documento")
        .set_index("documento")["id_documento"]
        .to_dict()
    )

    _forma_pgto_map = (
        forma_pagamento
        .drop_duplicates("forma_de_pagamento")
        .set_index("forma_de_pagamento")["id_forma_de_pagamento"]
        .to_dict()
    )

    _cliente_map = (
        dim_cliente
        .drop_duplicates("cod_cliente")
        .set_index("cod_cliente")["id_cliente"]
        .to_dict()
    )

    _centro_de_custo_map = (
        dim_centro_custo
        .drop_duplicates("cod_centro_de_custo")
        .set_index("cod_centro_de_custo")["id_centro_de_custo"]
        .to_dict()
    )

    df["id_empresa"] = df["cod_empresa"].map(_emp_map)
    df["id_documento"] = df["documento"].map(_doc_map)
    df["id_forma_de_pagamento"] = df["forma_de_pagamento"].map(_forma_pgto_map)
    df["id_cliente"] = df["cod_cliente"].map(_cliente_map)
    df["id_centro_de_custo"] = df["cod_centro_de_custo"].map(_centro_de_custo_map)

    # ── 8. Montar fato ────────────────────────────────────────────────────────
    print("\n── 8. fato_contas_a_receber ────────────────────────────────────────")

    fato = df[[
        # Surrogate keys
         "id_empresa",
        "id_documento",
        "id_forma_de_pagamento",
        "id_cliente",
        "id_centro_de_custo",
        # Chaves naturais
        "titulo", "titulo_pesquisa", "parcela", "nn_parcela",
        "nn_documento", "origem", "cod_plano_fin", "plano_fin",
        # Datas
        "data_vencimento", "data_emissao", "data_contabil",
        "data_base", "data_base_juros", "data_do_recebimento", "data_do_calculo",
        # Métricas financeiras
        "valor_bruto", "desconto", "valor_imposto_retido", "saldo_em_aberto",
        "saldo_corrigido_em_aberto", "juros_embutidos", "taxa_juros", "valor_recebido",
        "juros_recebidos", "multa_recebida", "desconto_recebido", "imposto_retido_recebido",
        "valor_liquido_recebido", "acrescimo_recebido", "%_apropriacao_financeira",
        # Flags
        "flag_fonte_api",
        # Atributos de workflow / auditoria
        "situacao_inadimplencia", "tipo_de_operacao",
        "conta_corrente", "indexador", "historico_bancario", "bank_movement_id",
        "cod_centro_de_custo", "centro_de_custo",
    ]].copy()

    fato["data_carga"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ── 9. Validação ──────────────────────────────────────────────────────────
    print("\n── 11. Validação ───────────────────────────────────────────────────")
    checar_integridade(
        fato, "id_empresa",
        dim_empresa, "id_empresa",
        "fato → dim_empresa"
    )

    checar_integridade(
        fato, "id_documento",
        dim_documento, "id_documento",
        "fato → dim_documento"
    )

    checar_integridade(
        fato, "id_forma_de_pagamento",
        forma_pagamento, "id_forma_de_pagamento",
        "fato → dim_forma_pagamento"
    )

    checar_integridade(
        fato, "id_cliente",
        dim_cliente, "id_cliente",
        "fato → dim_cliente"
    )

    checar_integridade(
        fato, "id_centro_de_custo",
        dim_centro_custo, "id_centro_de_custo",
        "fato → dim_centro_de_custo"
    )

    # ── 10. Exportação ────────────────────────────────────────────────────────
    print("\n── 10. Exportação ──────────────────────────────────────────────────")
    salvar_tabela(dim_empresa, "dim_empresa", output_dir)
    salvar_tabela(dim_documento, "dim_documento", output_dir)
    salvar_tabela(forma_pagamento, "dim_forma_pagamento", output_dir)
    salvar_tabela(dim_cliente, "dim_cliente", output_dir)
    salvar_tabela(dim_centro_custo, "dim_centro_custo", output_dir)

    fato.drop_duplicates(subset=['titulo', 'parcela', 'id_centro_de_custo',
                                 'id_forma_de_pagamento', 'id_empresa', 'id_documento',
                                 'saldo_corrigido_em_aberto'], inplace=True)

    salvar_tabela(fato, "fato_contas_a_receber", output_dir)

    print("\n── Resumo ──────────────────────────────────────────────────────────")
    for nome, tab in {
        "dim_empresa": dim_empresa,
        "dim_documento": dim_documento,
        "dim_forma_pagamento": forma_pagamento,
        "dim_cliente": dim_cliente,
        "dim_centro_custo": dim_centro_custo,
        "fato_contas_a_receber": fato,
    }.items():
        print(f"  {nome:<35} {str(tab.shape):>12}")
