"""
stages/transform/vendas_transformer_vendas.py
-----------------------------------------------
Transformação de dados brutos de Vendas.

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

    df_vendidas = pd.read_csv(input_dir / "contrato_vendas_vendidas.csv", sep=";")
    df_distratos = pd.read_csv(input_dir / "contrato_vendas_distratos.csv", sep=";")

    df_vendidas = normalizar_colunas(df_vendidas)
    df_distratos = normalizar_colunas(df_distratos)

    # flag de origem para rastreabilidade no BI
    df_vendidas["flag_fonte_api"] = True
    df_distratos["flag_fonte_api"] = True

    # ── 2. Cast de datas ──────────────────────────────────────────────────────
    print("\n── 2. Cast de datas ────────────────────────────────────────────────")

    COLUNAS_DATA = [
        "data_criacao_venda", "data_contrato", "data_emissao",
        "data_cancelamento", "data_instituicao_financeira",
    ]
    for col in COLUNAS_DATA:
        for df in (df_vendidas, df_distratos):
            if col in df.columns:
                df[col] = _parse_date(df[col])



    # ── 3. Campos auxiliares ──────────────────────────────────────────────────
    print("\n── 3. Campos auxiliares ────────────────────────────────────────────")

    for df in (df_vendidas, df_distratos):
        df["id_titulo_receber_pesquisa"] = np.where(
            df["id_titulo_receber"].notna(),
            "t " + df["id_titulo_receber"].astype(str),
            "",
        )

    # ── 4. Unificação das fontes ──────────────────────────────────────────────
    # Mantemos separado para rastreabilidade, mas unimos para criar as dims
    df_tudo = pd.concat([df_vendidas, df_distratos], ignore_index=True)

    df_tudo['valor_venda'] = pd.to_numeric(df_tudo['valor_venda'], errors='coerce')

    # ── 5. dim_centro_custo ───────────────────────────────────────────────────
    # cod_centro_de_custo vem de sale_enterpriseId (id da empresa/empreendimento)
    print("\n── 5. dim_centro_custo ─────────────────────────────────────────────")
    dim_centro_custo = pd.read_csv((OUTPUT_DIR / "dim_centro_custo.csv"), sep=';')

    for df in (df_vendidas, df_distratos):
        df = _mapear_surrogate(df, "cod_centro_de_custo", dim_centro_custo,
                               "cod_centro_de_custo", "id_centro_de_custo")

    # ── 6. dim_cliente ────────────────────────────────────────────────────────
    # cod_cliente vem de clientes_id (expandido pelo extrator)
    print("\n── 6. dim_cliente ──────────────────────────────────────────────────")

    _path_cli = output_dir / "dim_cliente_vendas.csv"
    dim_cliente = _carregar_ou_criar_dimensao(
        path=_path_cli,
        df_fonte=df_tudo,
        colunas=[
            "cod_cliente",  # clientes_id  → chave natural
            "nome_cliente",  # clientes_name
            "clientes_cpf",
            "clientes_email",
            "clientes_civilstatus",
            "sexo_cliente",  # clientes_sex
            "profissao_cliente",  # clientes_profession
            "aniversario_cliente",  # clientes_birthDate
        ],
        nome_id="id_cliente",
        col_pk_natural="cod_cliente",
    )

    for df in (df_vendidas, df_distratos):
        df = _mapear_surrogate(df, "cod_cliente", dim_cliente,
                               "cod_cliente", "id_cliente")

    # ── 7. dim_corretor ───────────────────────────────────────────────────────
    print("\n── 7. dim_corretor ─────────────────────────────────────────────────")

    _path_cor = output_dir / "dim_corretor_vendas.csv"
    dim_corretor = _carregar_ou_criar_dimensao(
        path=_path_cor,
        df_fonte=df_tudo,
        colunas=[
            "cod_corretor",  # brokers_id  → chave natural (já é surrogate-like)
            "nome_corretor",  # brokers_name
            "corretor_principal",  # brokers_main
        ],
        nome_id="id_corretor",
        col_pk_natural="cod_corretor",
    )


    for df in (df_vendidas, df_distratos):
        df = _mapear_surrogate(df, "cod_corretor", dim_corretor,
                               "cod_corretor", "id_corretor")

    # ── 8. dim_titulo_recebimento ─────────────────────────────────────────────
    # Agrupa atributos descritivos do título/contrato; a chave natural é
    # id_titulo_receber (sale_receivableBillId da API Sienge).
    print("\n── 8. dim_titulo_recebimento ───────────────────────────────────────")

    _path_tit = output_dir / "dim_titulo_recebimento_vendas.csv"
    dim_titulo = _carregar_ou_criar_dimensao(
        path=_path_tit,
        df_fonte=df_tudo,
        colunas=[
            "id_titulo_receber",  # chave natural
            "id_titulo_receber_pesquisa",  # campo de pesquisa "t <id>"
            "numero_venda",  # sale_number
            "id_externo_venda",  # sale_externalId
            "situacao_venda",  # sale_situation
            "data_contrato",
            "data_emissao",
            "data_cancelamento",
            "motivo_cancelamento",
            "observacao_venda",
        ],
        nome_id="id_titulo",
        col_pk_natural="id_titulo_receber",
    )

    for df in (df_vendidas, df_distratos):
        df = _mapear_surrogate(df, "id_titulo_receber", dim_titulo,
                               "id_titulo_receber", "id_titulo")


    # ── 9. Montagem da fato ───────────────────────────────────────────────────
    print("\n── 9. fato_vendas ──────────────────────────────────────────────────")

    COLUNAS_FATO = [
        # ── Surrogate keys ──────────────────────────────────────────────────
        "id_empresa",  # enterpriseId renomeado
        "id_centro_de_custo",  # ← dim_centro_custo
        "id_cliente",  # ← dim_cliente
        "id_corretor",  # ← dim_corretor  (já é natural/surrogate)
        "id_titulo",  # ← dim_titulo_recebimento
        "chave_composta_unidade",
        # ── Chaves naturais de apoio ─────────────────────────────────────────
        "id_venda",  # sale_id
        "id_unidade_detalhe",  # units_id
        "id_titulo_receber",  # sale_receivableBillId (FK natural)
        "id_titulo_estorno",  # sale_refundBillId
        # ── Datas ────────────────────────────────────────────────────────────
        "data_criacao_venda",
        "data_contrato",
        "data_emissao",
        "data_cancelamento",
        "data_instituicao_financeira",
        "data_entrega",  # units_deliveryDate
        # ── Métricas financeiras ─────────────────────────────────────────────
        "valor_venda",
        "valor_total_venda",
        "percentual_desconto",
        "percentual_juros",
        "percentual_multa",
        "valor_juros_diario",
        # ── Atributos de unidade ─────────────────────────────────────────────
        "nome_unidade",
        "tipo_imovel",
        "area_privativa",
        "area_comum",
        "area_terreno",
        "percentual_participacao",
        "unidade_principal",
        "estoque_comercial",
        # ── Métricas derivadas ────────────────────────────────────────────────
        "valor_por_m2",
        "_is_main_unit",
        # ── Flags / auditoria ─────────────────────────────────────────────────
        "flag_fonte_api",
        "situacao_venda",
        "tipo_juros",
        "tipo_desconto",
        "tipo_correcao",
        "credito_associativo",
    ]

    def _montar_fato(df: pd.DataFrame) -> pd.DataFrame:
        cols_presentes = [c for c in COLUNAS_FATO if c in df.columns]
        fato = df[cols_presentes].copy()
        fato["data_carga"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return fato



    # ── Fato Vendas ──────────────────────────────────────────────────────────────


    fato_vendas = _montar_fato(df_vendidas)
    fato_vendas = fato_vendas[
        fato_vendas["situacao_venda"].eq("Emitido")
    ].copy()

    # ── Fato Distratos ───────────────────────────────────────────────────────────

    fato_distratos = _montar_fato(df_distratos)
    fato_distratos = fato_distratos[
        fato_distratos["situacao_venda"].eq("Cancelado")
    ].copy()

    # ── Deduplicação ─────────────────────────────────────────────────────────────

    subset_dedup = [
        "id_venda",
        "id_unidade_detalhe",
        "cod_corretor",
        "id_cliente",
    ]

    for nome_fato, df_fato in [
        ("fato_vendas", fato_vendas),
        ("fato_distratos", fato_distratos),
    ]:
        subset_dedup_ok = [c for c in subset_dedup if c in df_fato.columns]

        before = len(df_fato)

        df_fato.drop_duplicates(
            subset=subset_dedup_ok,
            inplace=True,
        )

        logger.info(
            "  Deduplicação %s: %d → %d linhas.",
            nome_fato,
            before,
            len(df_fato),
        )

    # ── 10. Validação de integridade referencial ──────────────────────────────
    print("\n── 10. Validação ───────────────────────────────────────────────────")

    for nome_fato, df_fato in [
        ("fato_vendas", fato_vendas),
        ("fato_distratos", fato_distratos),
    ]:
        if "id_centro_custo" in df_fato.columns:
            checar_integridade(
                df_fato,
                "id_centro_custo",
                dim_centro_custo,
                "id_centro_custo",
                f"{nome_fato} → dim_centro_custo",
            )

        if "id_cliente" in df_fato.columns:
            checar_integridade(
                df_fato,
                "id_cliente",
                dim_cliente,
                "id_cliente",
                f"{nome_fato} → dim_cliente",
            )

        if "id_corretor" in df_fato.columns:
            checar_integridade(
                df_fato,
                "id_corretor",
                dim_corretor,
                "id_corretor",
                f"{nome_fato} → dim_corretor",
            )

        if "id_titulo" in df_fato.columns:
            checar_integridade(
                df_fato,
                "id_titulo",
                dim_titulo,
                "id_titulo",
                f"{nome_fato} → dim_titulo_recebimento",
            )

    # ── 11. Exportação ────────────────────────────────────────────────────────
    print("\n── 11. Exportação ──────────────────────────────────────────────────")

    salvar_tabela(dim_centro_custo, "dim_centro_custo_vendas", output_dir)
    salvar_tabela(dim_cliente, "dim_cliente_vendas", output_dir)
    salvar_tabela(dim_corretor, "dim_corretor_vendas", output_dir)
    salvar_tabela(dim_titulo, "dim_titulo_recebimento_vendas", output_dir)

    fato_vendas["chave_composta_unidade"] = (
            fato_vendas["id_centro_de_custo"]
            .astype(str)
            .str.strip()
            .str.lower()
            + "_"
            + fato_vendas["nome_unidade"]
            .astype(str)
            .str.strip()
            .str.replace(r"\s+", "_", regex=True)
            .str.lower()
            + "_"
            + fato_vendas["tipo_imovel"]
            .astype(str)
            .str.strip()
            .str.replace(r"\s+", "_", regex=True)
            .str.lower()
    )

    salvar_tabela(fato_vendas, "fato_vendas", output_dir)
    salvar_tabela(fato_distratos, "fato_distratos", output_dir)

    # ── 12. Resumo ────────────────────────────────────────────────────────────
    print("\n── Resumo ──────────────────────────────────────────────────────────")
    for nome, tab in {
        "dim_centro_custo_vendas": dim_centro_custo,
        "dim_cliente_vendas": dim_cliente,
        "dim_corretor_vendas": dim_corretor,
        "dim_titulo_recebimento_vendas": dim_titulo,
        "fato_vendas": fato_vendas,
        "fato_distratos": fato_distratos,
    }.items():
        print(f"  {nome:<45} {str(tab.shape):>12}")


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    executar()
