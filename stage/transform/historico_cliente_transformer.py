"""
Transformação de dados brutos de Histórico de Cliente.

Responsabilidade única: receber ExtratoClienteHistoricoResult
e retornar um DataFrame limpo, tipado e com colunas derivadas,
pronto para carga.
"""
import logging
from datetime import date

import pandas as pd

from stage.extract.historico_cliente_extractor import ExtratoClienteHistoricoResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Mapeamento de colunas
# ---------------------------------------------------------------------------

RENAME_COLUMNS = {
    # Identificação do snapshot
    "competencia":                              "posicao",

    # Empresa / Centro de custo
    "outcome_company_id":                       "cod_empresa",
    "outcome_company_name":                     "empresa",
    "outcome_costCenter_id":                    "cod_centro_de_custo",
    "outcome_costCenter_name":                  "centro_de_custo",

    # Cliente
    "outcome_customer_id":                      "cod_cliente",
    "outcome_customer_name":                    "cliente",
    "outcome_customer_document":                "cpf_cnpj",

    # Título
    "outcome_billReceivableId":                 "cod_titulo",
    "outcome_document":                         "documento",
    "outcome_emissionDate":                     "data_emissao",
    "outcome_correctionDate":                   "data_correcao",
    "outcome_lastRenegotiationDate":            "data_ultima_repactuacao",
    "outcome_revokedBillReceivableDate":        "data_distrato",
    "outcome_privateArea":                      "area_privativa",
    "outcome_units_ids":                        "cod_unidades",
    "outcome_units_names":                      "unidades",

    # Parcela
    "installments_id":                          "cod_parcela",
    "installments_installmentNumber":           "numero_parcela",
    "installments_dueDate":                     "data_vencimento",
    "installments_baseDate":                    "data_base_indexador",
    "installments_originalValue":               "valor_original",
    "installments_currentBalance":              "saldo_atual",
    "installments_currentBalanceWithAddition":  "saldo_atual_com_acrescimos",
    "installments_installmentSituation":        "situacao_parcela",
    "installments_indexerId":                   "cod_indexador",
    "installments_annualCorrection":            "correcao_anual",
    "installments_generatedBillet":             "boleto_gerado",
    "installments_sentToScripturalCharge":      "enviado_cobranca_escritural",
    "installments_paymentTerms_id":             "cod_condicao_pagamento",
    "installments_paymentTerms_description":    "condicao_pagamento",

    # Baixas
    "receipts_date":                            "data_recebimento",
    "receipts_value":                           "valor_recebido",
    "receipts_extra":                           "acrescimos",
    "receipts_discount":                        "descontos",
    "receipts_netReceipt":                      "recebimento_liquido",
    "receipts_days":                            "dias_atraso_baixa",
    "receipts_type":                            "tipo_baixa",
}

# Colunas que definem unicidade de uma linha de parcela
# (elimina duplicidades geradas pela expansão de receipts vazios)
DEDUP_SUBSET = [
    "cod_parcela",
    "numero_parcela",
    "saldo_atual",
    "cod_cliente",
    "cod_centro_de_custo",
    "posicao",
]

# Faixas de dias em aberto
FAIXAS = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90]
LABELS = [
    "00-10", "11-20", "21-30", "31-40",
    "41-50", "51-60", "61-70", "71-80", "81-90", "90+",
]


# ---------------------------------------------------------------------------
# Transformer
# ---------------------------------------------------------------------------

class ExtratoClienteHistoricoTransformer:

    def transform(self, result: ExtratoClienteHistoricoResult) -> pd.DataFrame:
        if not result.sucesso or not result.registros:
            logger.warning("Nenhum dado disponível para transformação.")
            return pd.DataFrame()

        df = pd.DataFrame(result.registros)
        df = self._rename_columns(df)
        df = self._cast_types(df)
        df = self._deduplicate(df)
        df = self._add_dias_aberto(df)
        df = self._add_faixa(df)

        logger.info("Transformação concluída: %d registros finais.", len(df))
        return df

    # ------------------------------------------------------------------
    # Etapas
    # ------------------------------------------------------------------

    @staticmethod
    def _rename_columns(df: pd.DataFrame) -> pd.DataFrame:
        return df.rename(columns=RENAME_COLUMNS)

    @staticmethod
    def _cast_types(df: pd.DataFrame) -> pd.DataFrame:
        """Tipagem das colunas mais relevantes."""
        date_cols = [
            "data_emissao", "data_vencimento", "data_base_indexador",
            "data_correcao", "data_recebimento", "data_ultima_repactuacao",
            "data_distrato",
        ]
        for col in date_cols:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce").dt.date

        numeric_cols = [
            "valor_original", "saldo_atual", "saldo_atual_com_acrescimos",
            "valor_recebido", "acrescimos", "descontos", "recebimento_liquido",
            "area_privativa",
        ]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        return df

    @staticmethod
    def _deduplicate(df: pd.DataFrame) -> pd.DataFrame:
        """
        Remove duplicatas geradas pela expansão de receipts vazios.
        Mantém a primeira ocorrência de cada parcela por posição.
        """
        subset = [c for c in DEDUP_SUBSET if c in df.columns]
        antes = len(df)
        df = df.drop_duplicates(subset=subset, keep="first").reset_index(drop=True)
        logger.info("Deduplicação: %d → %d registros.", antes, len(df))
        return df

    @staticmethod
    def _add_dias_aberto(df: pd.DataFrame) -> pd.DataFrame:
        """
        Calcula dias em aberto = hoje − data_vencimento.
        Negativo significa parcela ainda não vencida; positivo, vencida.
        """
        if "data_vencimento" not in df.columns:
            return df

        hoje = date.today()
        df["dias_aberto"] = df["data_vencimento"].apply(
            lambda d: (hoje - d).days if pd.notna(d) and isinstance(d, date) else None
        )
        return df

    @staticmethod
    def _add_faixa(df: pd.DataFrame) -> pd.DataFrame:
        """
        Classifica dias_aberto em faixas de inadimplência:
          00-10, 11-20, ..., 81-90, 90+

        Parcelas com dias_aberto ≤ 0 (não vencidas) recebem "A vencer".
        """
        if "dias_aberto" not in df.columns:
            return df

        def classificar(dias):
            if pd.isna(dias):
                return None
            if dias <= 0:
                return "A vencer"
            for i, limite in enumerate(FAIXAS):
                if dias <= limite + 10:
                    return LABELS[i]
            return "90+"

        df["faixa_inadimplencia"] = df["dias_aberto"].apply(classificar)
        return df