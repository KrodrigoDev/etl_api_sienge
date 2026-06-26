"""
stages/transform/estoque_empreedimentos_transformer_vendas.py
-----------------------------------------------
Transformação de dados Estoque de Empreedimentos .

Responsabilidade única: receber os CSVs de vendas (vendidas e distratos),
construir dimensões e montar a tabela fato, pronta para carga no DW.
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
OUTPUT_DIR = pasta_origem / "stage" / "transform" / "files" / "output"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _parse_date(series: pd.Series) -> pd.Series:
    """Tenta ISO 8601 (API) e depois DD/MM/YYYY (CSV manual)."""
    parsed = pd.to_datetime(series, format="%Y-%m-%d", errors="coerce")
    mask = parsed.isna()
    if mask.any():
        parsed.loc[mask] = pd.to_datetime(
            series.loc[mask], format="%d/%m/%Y", errors="coerce"
        )
    return parsed


def _carregar_ou_criar_dimensao(
        path: Path,
        df_fonte: pd.DataFrame,
        colunas: list[str],
        nome_id: str,
        col_pk_natural: str,
) -> pd.DataFrame:
    """
    Carrega a dimensão do disco (se existir) e expande com novos registros,
    ou cria do zero a partir de df_fonte.
    """
    colunas_existentes = [c for c in colunas if c in df_fonte.columns]

    if path.exists():
        dim = pd.read_csv(path, sep=";")

        dim = expandir_dimensao(
            dim_existente=dim,
            df_novo=df_fonte,
            colunas_naturais=colunas_existentes,
            nome_id=nome_id,
            col_pk_natural=col_pk_natural,
        )
        logger.info("  %s carregada e expandida: %s", path.name, dim.shape)
    else:
        logger.info("  %s não encontrado — criando do zero.", path.name)
        dim = criar_dimensao(
            df_fonte,
            colunas=colunas_existentes,
            nome_id=nome_id,
        )
        logger.info("  %s criada: %s", path.name, dim.shape)

    return dim


def _mapear_surrogate(
        df: pd.DataFrame,
        col_natural: str,
        dim: pd.DataFrame,
        col_pk_natural: str,
        col_surrogate: str,
) -> pd.DataFrame:
    """Faz o join natural→surrogate key e preenche a coluna no df."""
    mapa = (
        dim.drop_duplicates(col_pk_natural)
        .set_index(col_pk_natural)[col_surrogate]
        .to_dict()
    )
    df[col_surrogate] = df[col_natural].map(mapa)
    nulos = df[col_surrogate].isna().sum()
    if nulos:
        logger.warning(
            "  %d linhas sem %s após mapeamento de '%s'.",
            nulos, col_surrogate, col_natural,
        )
    return df


# ─────────────────────────────────────────────────────────────────────────────
# FUNÇÃO PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

def executar(input_dir: Path = INPUT_DIR, output_dir: Path = OUTPUT_DIR) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # ── 1. Leitura ────────────────────────────────────────────────────────────
    print("\n── 1. Leitura ──────────────────────────────────────────────────────")

    df_estoque_empreedimento = pd.read_csv(input_dir / "estoqueempreedimento.csv", sep=";")
    df_estoque_empreedimento = normalizar_colunas(df_estoque_empreedimento)

    # flag de origem para rastreabilidade no BI
    df_estoque_empreedimento["flag_fonte_api"] = True

    # ── 2. Cast de datas ──────────────────────────────────────────────────────
    print("\n── 2. Cast de datas ────────────────────────────────────────────────")

    COLUNAS_DATA = [
        "data_entrega", "data_programada_entrega"
    ]
    for col in COLUNAS_DATA:
        df_estoque_empreedimento[col] = _parse_date(df_estoque_empreedimento[col])

    # ── 5. dim_centro_custo ───────────────────────────────────────────────────
    # cod_centro_de_custo vem de sale_enterpriseId (id da empresa/empreendimento)
    print("\n── 5. dim_centro_custo ─────────────────────────────────────────────")
    dim_centro_custo = pd.read_csv((OUTPUT_DIR / "dim_centro_custo.csv"), sep=';')

    df_estoque_empreedimento = _mapear_surrogate(df_estoque_empreedimento, "cod_centro_de_custo", dim_centro_custo,
                                                 "cod_centro_de_custo", "id_centro_de_custo")

    df_estoque_empreedimento["chave_composta_unidade"] = (
            df_estoque_empreedimento["id_centro_de_custo"]
            .astype(str)
            .str.strip()
            .str.lower()
            + "_"
            + df_estoque_empreedimento["nome_unidade"]
            .astype(str)
            .str.strip()
            .str.replace(r"\s+", "_", regex=True)
            .str.lower()
            + "_"
            + df_estoque_empreedimento["tipo_imovel"]
            .astype(str)
            .str.strip()
            .str.replace(r"\s+", "_", regex=True)
            .str.lower()
    )

    # ── 9. Montagem da fato ───────────────────────────────────────────────────
    print("\n── 9. fato_estoque_unidades ─────────────────────────────────────")

    COLUNAS_FATO = [
        # Chaves
        "id_empresa_contexto",
        "id_centro_de_custo",
        "chave_composta_unidade",

        # Identificação da unidade
        "id_unidade",
        "nome_unidade",
        "tipo_imovel",

        # Situação comercial
        "estoque_comercial",
        "estoque_comercial_descricao",

        # Contrato
        "id_contrato",
        "numero_contrato",

        # Localização
        "latitude",
        "longitude",

        # Registros legais
        "matricula",
        "inscricao_imobiliaria",
        "codigo_cib",
        "codigo_incra",

        # Datas
        "data_entrega",
        "data_programada_entrega",

        # Áreas
        "area_privativa",
        "area_comum",
        "area_terreno",
        "area_comum_nao_proporcional",
        "area_util",

        # Frações
        "fracao_ideal",
        "fracao_ideal_m2",
        "fracao_vgv",

        # Valores
        "valor_terreno",
        "valor_iptu",
        "quantidade_indexada",
        "adimplencia_premiada",

        # Classificações
        "pavimento",
        "tipo_localizacao",
        "tipo_enquadramento",

        # Observações
        "observacao_unidade",

        # Auditoria
        "flag_fonte_api",
    ]

    def _montar_fato(df: pd.DataFrame) -> pd.DataFrame:
        cols_presentes = [c for c in COLUNAS_FATO if c in df.columns]
        fato = df[cols_presentes].copy()
        fato["data_carga"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return fato

    fato = _montar_fato(df_estoque_empreedimento)

    # ── 10. Validação de integridade referencial ──────────────────────────────
    print("\n── 10. Validação ───────────────────────────────────────────────────")

    if "id_centro_custo" in fato.columns:
        checar_integridade(
            fato,
            "id_centro_custo",
            dim_centro_custo,
            "id_centro_custo",
            "fato_estoque_unidades → dim_centro_custo",
        )

    # ── 11. Exportação ────────────────────────────────────────────────────────
    print("\n── 11. Exportação ──────────────────────────────────────────────────")


    salvar_tabela(fato, "fato_estoque_unidades", output_dir)

    # ── 12. Resumo ────────────────────────────────────────────────────────────
    print("\n── Resumo ──────────────────────────────────────────────────────────")
    for nome, tab in {
        "dim_centro_custo_vendas": dim_centro_custo,
        "fato": fato,
    }.items():
        print(f"  {nome:<45} {str(tab.shape):>12}")


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    executar()
