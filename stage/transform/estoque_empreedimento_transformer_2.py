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

from stage.transform.utils.dim_permutante import gerar_chave_permutante
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
# HELPERS — STATUS RECONCILIADO (NOVO)
# ─────────────────────────────────────────────────────────────────────────────

# Mapeamento de normalização dos valores que vêm do CV (acentos, capitalização)
_MAPA_SITUACAO_CV = {
    "disponível": "disponivel",
    "disponivel": "disponivel",
    "vendida": "vendida",
    "bloqueada": "bloqueada",
    "reservada": "reservada",
}


def _normalizar_situacao_cv(valor) -> str | None:
    """Normaliza o texto de situação do CV para snake_case sem acentos.
    Retorna None quando o merge falhou (NaN)."""
    if pd.isna(valor):
        return None
    texto = str(valor).strip().lower()
    return _MAPA_SITUACAO_CV.get(texto, texto)


def _reconciliar_status(row) -> str:
    """
    Regras de reconciliação entre Sienge (fonte do estoque) e CV (fonte de verdade comercial):

    - status_cv é None  → unidade não encontrada em nenhuma tabela aprovada do CV → 'outro_status'
    - Sienge=disponivel mas CV discorda → 'divergente_sienge_disponivel_cv_{status_cv}'
    - demais casos       → status_cv é a fonte de verdade
    """
    sienge = str(row.get("status_sienge", "")).strip().lower()
    cv = row.get("status_cv")

    # Merge falhou: unidade não está em nenhuma tabela aprovada do CV
    # (tipicamente bloqueadas, distratos ou empreendimentos sem tabela ativa)
    if cv is None:
        return "outro_status"

    # Sienge diz disponível mas CV discorda — divergência real
    if sienge in ("disponível", "disponivel") and cv != "disponivel":
        return f"divergente_sienge_disponivel_cv_{cv}"

    # CV é a fonte de verdade para os demais casos
    return cv


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

    df_estoque_empreedimento.drop_duplicates(subset=['nome_unidade', 'cod_centro_de_custo'], inplace=True)
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
    print("\n── 5. dim_centro_custo ─────────────────────────────────────────────")
    dim_centro_custo = pd.read_csv((OUTPUT_DIR / "dim_centro_custo_vendas.csv"), sep=';')

    df_estoque_empreedimento = _mapear_surrogate(
        df_estoque_empreedimento, "cod_centro_de_custo",
        dim_centro_custo, "cod_centro_de_custo", "id_centro_de_custo"
    )

    df_estoque_empreedimento["chave_composta_unidade"] = (
            df_estoque_empreedimento["id_centro_de_custo"]
            .astype(str).str.strip().str.lower()
            + "_"
            + df_estoque_empreedimento["nome_unidade"]
            .astype(str).str.strip()
            .str.replace(r"\s+", "_", regex=True).str.lower()
            + "_"
            + df_estoque_empreedimento["tipo_imovel"]
            .astype(str).str.strip()
            .str.replace(r"\s+", "_", regex=True).str.lower()
    )

    # ── 6. Enriquecimento com mapa de disponibilidade + tabela de preço do CV ──
    print("\n── 6. Enriquecimento mapa de disponibilidade + tabela de preço CV ──")

    df_cv = pd.read_csv((INPUT_DIR / "relatorio_tabela_preco_completo.csv"), sep=';')
    df_cv = normalizar_colunas(df_cv)

    # Colunas de valor monetário presentes no novo CSV (prefixo tp_)
    # Exemplos: tp_valor_total, tp_sinal_(1x), tp_sinal_intercalado_(3x), etc.
    # Normaliza apenas as que existirem para não quebrar em variações de tabela.
    for col in ['tp_valor_total', 'tp_sinal', 'tp_desconto', 'tp_financiamento']:
        if col not in df_cv.columns:
            continue
        df_cv[col] = (
            df_cv[col]
            .astype(str)
            .str.replace('.', '', regex=False)
            .str.replace(',', '.', regex=False)
        )
        df_cv[col] = pd.to_numeric(df_cv[col], errors='coerce')

        # Merge: Sienge (cod_centro_de_custo + nome_unidade)
        #      ↔ CV  (id_empreendimento_sienge + cv_unidade)
        # O campo cv_unidade vem do mapa de disponibilidade e é a chave natural
        # que corresponde a nome_unidade do Sienge.

        # ── Normalização das chaves de join ──────────────────────────────────────
        # Problemas conhecidos tratados aqui:
        #
        # 1. TIPO int64 vs string: cod_centro_de_custo chega como int64 do Sienge,
        #    mas id_empreendimento_sienge vem como string do CV — o pandas nao faz
        #    coercao automatica -> join falha silenciosamente -> status_cv fica NaN.
        #
        # 2. ESPACOS INTERNOS inconsistentes: o mesmo bloco/unidade pode ser grafado
        #    de formas diferentes entre Sienge e CV, ex:
        #      Sienge -> "BL. A/006"   (espaco apos o ponto)
        #      CV     -> "BL.A/006"    (sem espaco)
        #    Solucao: remover todos os espacos internos antes de comparar.
        #    Isso torna "BL. A/006", "BL.A/006" e "BL .A/ 006" equivalentes.

        def _normalizar_chave_unidade(series: pd.Series) -> pd.Series:
            return (
                series
                .astype(str)
                .str.strip()  # espacos nas bordas
                .str.upper()  # capitalizacao
                .str.replace(r"\s+", "", regex=True)  # todos os espacos internos
            )

    df_estoque_empreedimento["_key_empresa"] = (
            df_estoque_empreedimento["cod_centro_de_custo"]
            .astype(str).str.strip()
        )
    df_estoque_empreedimento["_key_unidade"] = _normalizar_chave_unidade(
            df_estoque_empreedimento["nome_unidade"]
        )
    df_cv["_key_empresa"] = (
            df_cv["id_empreendimento_sienge"]
            .astype(str).str.strip()
        )
    df_cv["_key_unidade"] = _normalizar_chave_unidade(
            df_cv["cv_unidade"]
        )

    n_antes = len(df_estoque_empreedimento)
    df_estoque_empreedimento = df_estoque_empreedimento.merge(
            df_cv,
            on=["_key_empresa", "_key_unidade"],
            how="left",
        )

        # Garante que o merge left não duplicou linhas
        # (ex: mesma unidade em duas tabelas de preço aprovadas)
    duplicatas = len(df_estoque_empreedimento) - n_antes
    if duplicatas:
        logger.warning(
            "  Merge gerou %d linhas extras — possível duplicidade de unidade "
            "em mais de uma tabela de preço. Mantendo primeira ocorrência.",
            duplicatas,
        )
        df_estoque_empreedimento.drop_duplicates(
            subset=["_key_empresa", "_key_unidade"], keep="first", inplace=True
        )

    df_estoque_empreedimento.drop(columns=["_key_empresa", "_key_unidade"], inplace=True)

    # ── 7. Status reconciliado ────────────────────────────────────────────────
    print("\n── 7. Status reconciliado ──────────────────────────────────────────")

    # Status bruto do Sienge (fonte do estoque físico)
    df_estoque_empreedimento["status_sienge"] = (
        df_estoque_empreedimento["estoque_comercial_descricao"]
        .astype(str).str.strip()
    )

    # Status do CV normalizado — vem de cv_situacao (mapa de disponibilidade),
    # que é mais granular e confiável que a tabela de preço anterior.
    # None quando o merge falhou (unidade não existe no CV ou empreendimento
    # não integrado).
    df_estoque_empreedimento["status_cv"] = (
        df_estoque_empreedimento["cv_situacao"]
        .apply(_normalizar_situacao_cv)
    )

    # Campos de bloqueio expostos diretamente para o BI
    # (já existem como cv_data_bloqueio, cv_motivo_bloqueio, cv_documento_bloqueio
    #  e cv_possui_reserva_solicitacao_distrato após o merge — renomeia para
    #  clareza na fato)
    _RENAME_CV = {
        "cv_data_bloqueio": "cv_data_bloqueio",
        "cv_motivo_bloqueio": "cv_motivo_bloqueio",
        "cv_documento_bloqueio": "cv_documento_bloqueio",
        "cv_possui_reserva_solicitacao_distrato": "cv_possui_reserva_distrato",
    }
    for orig, dest in _RENAME_CV.items():
        if orig in df_estoque_empreedimento.columns and orig != dest:
            df_estoque_empreedimento.rename(columns={orig: dest}, inplace=True)

    # Status final reconciliado entre as duas fontes
    df_estoque_empreedimento["status_reconciliado"] = (
        df_estoque_empreedimento.apply(_reconciliar_status, axis=1)
    )

    # Log de divergências para auditoria
    divergentes = df_estoque_empreedimento[
        df_estoque_empreedimento["status_reconciliado"].str.startswith("divergente_", na=False)
    ]
    if not divergentes.empty:
        logger.warning(
            "  %d unidades com status divergente entre Sienge e CV.",
            len(divergentes),
        )
        print(
            divergentes[[
                "nome_unidade", "status_sienge", "status_cv",
                "cv_motivo_bloqueio", "status_reconciliado",
            ]].to_string(index=False)
        )

    outro_status = df_estoque_empreedimento[
        df_estoque_empreedimento["status_reconciliado"] == "outro_status"
        ]
    if not outro_status.empty:
        logger.info(
            "  %d unidades com 'outro_status' (não encontradas no mapa de disponibilidade do CV).",
            len(outro_status),
        )

    # Resumo de distribuição
    print("\n  Distribuição status_reconciliado:")
    print(df_estoque_empreedimento["status_reconciliado"].value_counts().to_string())

    # ── 9. Montagem da fato ───────────────────────────────────────────────────
    print("\n── 9. fato_estoque_unidades ─────────────────────────────────────")
    print(df_estoque_empreedimento.columns)
    print(df_estoque_empreedimento['status_cv'].unique())
    COLUNAS_FATO = [
        # Chaves
        "id_empresa_contexto",
        "id_centro_de_custo",
        "chave_composta_unidade",
        "cod_centro_de_custo",

        # Identificação da unidade
        "id_unidade",
        "nome_unidade",
        "tipo_imovel",

        # Situação comercial — Sienge (estoque físico)
        "estoque_comercial",
        "estoque_comercial_descricao",

        # Status reconciliado entre Sienge e CV
        "status_sienge",  # bruto do Sienge
        "status_cv",  # normalizado do CV (None = não encontrada no mapa)
        "status_reconciliado",  # fonte de verdade final para o BI

        # Detalhes de bloqueio vindos do mapa de disponibilidade do CV
        "cv_data_bloqueio",  # data em que foi bloqueada
        "cv_motivo_bloqueio",  # ex: "destinação", "análise de crédito"
        "cv_documento_bloqueio",  # CPF/CNPJ vinculado ao bloqueio
        "cv_possui_reserva_distrato",  # S/N — reserva ou solicitação de distrato

        # IDs do CV (úteis para rastreabilidade e joins futuros)
        "cv_idunidade",
        "cv_idunidade_int",
        "cv_idetapa",
        "cv_etapa",
        "cv_idbloco",
        "cv_bloco",

        # Contrato (Sienge)
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

        # Áreas (Sienge — sufixo _x após merge quando há coluna homônima no CV)
        "area_privativa_x",
        "area_comum",
        "area_terreno",
        "area_comum_nao_proporcional",
        "area_util",

        # Frações
        "fracao_ideal",
        "fracao_ideal_m2",
        "fracao_vgv",

        # Valores do Sienge
        "valor_terreno",
        "valor_iptu",
        "quantidade_indexada",
        "adimplencia_premiada",

        # Valores da tabela de preço do CV (prefixo tp_)
        "tp_valor_total",
        "tp_area_privativa",
        "tp_tabela",  # nome da tabela de preço aprovada
        "tp_situacao",  # situação dentro da tabela (pode divergir do mapa)

        # Classificações
        "pavimento",
        "tipo_localizacao",
        "tipo_enquadramento",

        # Observações
        "observacao_unidade",

        # Auditoria
        "flag_fonte_api",
    ]

    # Adiciona dinamicamente todas as séries de pagamento presentes (tp_sinal_*, tp_parcelas_*, etc.)
    series_tp = sorted(
        c for c in df_estoque_empreedimento.columns
        if c.startswith("tp_") and c not in COLUNAS_FATO
    )
    COLUNAS_FATO.extend(series_tp)
    if series_tp:
        logger.info("  Séries TP adicionadas à fato: %s", series_tp)

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

        # em fato_estoque_unidades e fato_vendas, após normalizar_colunas:
    fato["chave_permutante"] = fato.apply(
        lambda r: gerar_chave_permutante(r["cod_centro_de_custo"], r["nome_unidade"]),
        axis=1,
    )

    # ── 11. Exportação ────────────────────────────────────────────────────────
    print("\n── 11. Exportação ──────────────────────────────────────────────────")

    salvar_tabela(fato, "fato_estoque_unidades", output_dir)

    # ── 12. União com fato_vendas → fato_estoque_completa ────────────────────
    print("\n── 12. União fato_estoque_unidades + fato_vendas ───────────────────")

    _path_fato_vendas = output_dir / "fato_vendas.csv"

    if not _path_fato_vendas.exists():
        logger.warning(
            "  fato_vendas.csv não encontrado em %s — "
            "execute vendas_transformer antes deste passo. "
            "fato_estoque_completa não será gerada.",
            output_dir,
        )
    else:
        df_vendas = pd.read_csv(_path_fato_vendas, sep=";")

        # Colunas de vendas que enriquecem o estoque.
        # Excluímos campos que já existem na fato base (evita _x/_y desnecessários)
        # e mantemos apenas o que é exclusivo da fato_vendas.
        COLUNAS_VENDAS = [
            "chave_composta_unidade",   # chave do join — não entra duplicada

            # Identificação da venda
            "id_venda",
            "id_titulo_receber",
            "id_titulo_estorno",
            "numero_venda",

            # Datas da venda
            "data_criacao_venda",
            "data_contrato",
            "data_emissao",
            "data_cancelamento",
            "data_instituicao_financeira",

            # Financeiro da venda
            "valor_venda",
            "valor_total_venda",
            "percentual_desconto",
            "percentual_juros",
            "percentual_multa",
            "valor_juros_diario",
            "valor_por_m2",

            # Partes da venda
            "id_cliente",
            "id_corretor",
            "id_titulo",
            "nome_permutante",

            # Classificações da venda
            "situacao_venda",
            "tipo_juros",
            "tipo_desconto",
            "tipo_correcao",
            "credito_associativo",
            "unidade_principal",
            "_is_main_unit",
        ]

        cols_vendas_presentes = [c for c in COLUNAS_VENDAS if c in df_vendas.columns]

        # Normaliza a chave de join para garantir mesmo formato dos dois lados
        fato["chave_composta_unidade"] = fato["chave_composta_unidade"].astype(str).str.strip()
        df_vendas["chave_composta_unidade"] = df_vendas["chave_composta_unidade"].astype(str).str.strip()

        # Uma unidade pode ter mais de uma venda histórica (distrato + revenda).
        # Mantemos a mais recente por chave para não explodir a granularidade da fato.
        # Se precisar do histórico completo, use fato_vendas separada.
        if "data_contrato" in df_vendas.columns:
            df_vendas_dedup = (
                df_vendas[cols_vendas_presentes]
                .sort_values("data_contrato", ascending=False, na_position="last")
                .drop_duplicates(subset=["chave_composta_unidade"], keep="first")
            )
        else:
            df_vendas_dedup = (
                df_vendas[cols_vendas_presentes]
                .drop_duplicates(subset=["chave_composta_unidade"], keep="first")
            )

        n_estoque = len(fato)
        fato_completa = fato.merge(
            df_vendas_dedup,
            on="chave_composta_unidade",
            how="left",   # mantém TODAS as unidades do estoque, com ou sem venda
        )

        # Sanidade: left join não deve alterar a granularidade (1 linha por unidade)
        if len(fato_completa) != n_estoque:
            logger.warning(
                "  União gerou %d linhas extras — deduplicação de vendas incompleta. "
                "Verifique duplicatas em fato_vendas por chave_composta_unidade.",
                len(fato_completa) - n_estoque,
            )
            fato_completa.drop_duplicates(subset=["chave_composta_unidade"], keep="first", inplace=True)

        # Flag para filtros rápidos no BI
        fato_completa["tem_venda"] = fato_completa["id_venda"].notna()

        n_com_venda    = fato_completa["tem_venda"].sum()
        n_sem_venda    = (~fato_completa["tem_venda"]).sum()
        logger.info(
            "  fato_estoque_completa: %d unidades | %d com venda | %d sem venda",
            len(fato_completa), n_com_venda, n_sem_venda,
        )

        fato_completa["data_carga"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        salvar_tabela(fato_completa, "fato_estoque_completa", output_dir)

    # ── 13. Resumo ────────────────────────────────────────────────────────────
    print("\n── Resumo ──────────────────────────────────────────────────────────")
    tabelas_resumo = {
        "dim_centro_custo_vendas": dim_centro_custo,
        "fato_estoque_unidades":   fato,
    }
    if _path_fato_vendas.exists():
        tabelas_resumo["fato_estoque_completa"] = fato_completa

    for nome, tab in tabelas_resumo.items():
        print(f"  {nome:<45} {str(tab.shape):>12}")


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    executar()