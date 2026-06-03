import logging

import pandas as pd

from stage.extract.contas_pagas_extractor import ContasPagasExtractionResult

logger = logging.getLogger(__name__)

# =============================================================================
# Mapeamento: coluna da API → nome do relatório manual
# =============================================================================
MAPPING_COLUMNS = {
    # --- Empresa / estrutura ---
    "outcome_companyId":                  "Cód. empresa",
    "outcome_companyName":                "Empresa",
    "outcome_groupCompanyId":             "Cód. grupo empresa",
    "outcome_groupCompanyName":           "Grupo empresa",
    "outcome_holdingId":                  "Cód. holding",
    "outcome_holdingName":                "Holding",
    "outcome_subsidiaryId":               "Cód. subsidiária",
    "outcome_subsidiaryName":             "Subsidiária",
    "outcome_businessAreaId":             "Cód. área negócio",
    "outcome_businessAreaName":           "Área negócio",
    "outcome_businessTypeId":             "Cód. tipo negócio",
    "outcome_businessTypeName":           "Tipo negócio",

    # --- Credor ---
    "outcome_creditorId":                 "Cód. credor",
    "outcome_creditorName":               "Credor",

    # --- Título / Parcela ---
    "outcome_billId":                     "Título",
    "outcome_installmentId":              "Parcela",

    # --- Documento ---
    "outcome_documentIdentificationId":   "Sigla documento",
    "outcome_documentIdentificationName": "Documento",
    "outcome_documentNumber":             "N° documento",
    "outcome_forecastDocument":           "Documento previsão",

    # --- Origem / status ---
    "outcome_originId":                   "Origem",
    "outcome_consistencyStatus":          "Status consistência",
    "outcome_authorizationStatus":        "Parcela autorizada",

    # --- Valores base ---
    "outcome_originalAmount":             "Valor bruto",
    "outcome_discountAmount":             "Desconto",
    "outcome_taxAmount":                  "Acréscimo",
    "outcome_balanceAmount":              "Saldo em aberto",
    "outcome_correctedBalanceAmount":     "Saldo corrigido em aberto",

    # --- Datas base ---
    "outcome_dueDate":                    "Data vencimento",
    "outcome_issueDate":                  "Data emissão",
    "outcome_installmentBaseDate":        "Data base",
    "outcome_billDate":                   "Data contábil",

    # --- Auditoria ---
    "outcome_registeredUserId":           "Cód. usuário que cadastrou",
    "outcome_registeredBy":               "Usuário que cadastrou",
    "outcome_registeredDate":             "Data de cadastro",

    # --- Obra / projeto ---
    "outcome_projectId":                  "Cód. obra",
    "outcome_projectName":                "Obra",

    # --- Payments (expandidos de outcome_payments[0]) ---
    "payments_grossAmount":               "Valor no vencimento",
    "payments_taxAmount":                 "Valor Imposto Retido",
    "payments_netAmount":                 "Valor líquido",
    "payments_correctedNetAmount":        "Valor da baixa",
    "payments_paymentDate":               "Data do pagamento",
    "payments_calculationDate":           "Data do cálculo",
    "payments_operationTypeName":         "Tipo de operação",
    "payments_paymentAuthentication":     "Autenticação eletrônica",

    # --- BankMovements (expandidos de payments[0].bankMovements[0]) ---
    "bankMovements_accountNumber":        "Conta corrente",
    "bankMovements_historicName":         "Histórico",
    "bankMovements_operationName":        "Descrição do pagamento",
}

# Colunas que a API não fornece no endpoint bulk-data/v1/outcome
# Listadas aqui apenas como documentação
NOT_AVAILABLE_IN_API = [
    "Cód. unid. construtiva", "Unid. construtiva",
    "Cód. Item orçamento", "Item orçamento", "% apropriação obra",
    "Cód. departamento", "Departamento", "% apropriação departamento",
    "Vencimento original", "Diferença data vencimento", "Dias de atraso",
    "N° lote", "Status do lote", "Ciência do título", "Status da parcela",
    "Parcela agrupada", "Título/Parcela agrupada", "Tipo credor", "Cheque",
    "Usuário que deu ciência", "Usuário que autorizou",
    "Usuário que alterou", "Data de alteração",
    "Conta contábil", "Data de competência", "Tipo de baixa",
    "CNPJ/CPF", "Chave NFE", "Informações bancárias do Credor",
    "Pix do credor", "Forma de pagamento",
    "Observação do título", "Observação da baixa", "Ações",
]

# Colunas aninhadas removidas após expansão
NESTED_COLUMNS = {
    "outcome_paymentsCategories",
    "outcome_departamentsCosts",
    "outcome_buildingsCosts",
    "outcome_payments",
}

# Colunas da API sem equivalente no relatório manual (mantidas com nome original)
EXTRA_API_COLUMNS_TO_DROP = {
    "payments_operationTypeId",
    "payments_monetaryCorrectionAmount",
    "payments_interestAmount",
    "payments_fineAmount",
    "payments_discountAmount",
    "payments_sequencialNumber",
    "bankMovements_accountCompanyId",
    "bankMovements_accountType",
    "bankMovements_bankMovementDate",
    "bankMovements_sequencialNumber",
    "bankMovements_id",
    "bankMovements_amount",
    "bankMovements_historicId",
    "bankMovements_operationId",
    "bankMovements_operationType",
    "bankMovements_reconcile",
    "bankMovements_originId",
    "bankMovements_paymentCategories",
    "financialCategoryReducer",
    "financialCategoryType",
    "Cód. obra (apropriação)",
    "Obra (apropriação)",
}


class ContasPagasTransformer:
    """
    Transforma dados brutos de contas pagas em DataFrame analítico.

    Pipeline:
      1. Montar DataFrame bruto
      2. Expandir sub-listas (payments, bankMovements, paymentsCategories)
      3. Construir colunas derivadas (Indexador, Grupo)
      4. Renomear conforme MAPPING_COLUMNS
      5. Descartar colunas sem uso
    """

    def transform(self, result: ContasPagasExtractionResult) -> pd.DataFrame:
        if not result.sucesso or not result.registros:
            logger.warning("Nenhum dado disponível para transformação.")
            return pd.DataFrame()

        df = pd.DataFrame(result.registros)

        df = self._expand_payments(df)
        df = self._expand_payments_categories(df)

        # Coluna derivada: Indexador composto "Cód - Nome"
        df["Indexador"] = (
            df["outcome_indexerId"].astype(str)
            + " - "
            + df["outcome_indexerName"].astype(str)
        )
        df = df.drop(columns=["outcome_indexerId", "outcome_indexerName"], errors="ignore")

        # Coluna derivada: Grupo "Título/Parcela"
        df["Grupo"] = (
            df["outcome_billId"].astype(str)
            + "/"
            + df["outcome_installmentId"].astype(str)
        )

        df = df.rename(columns=MAPPING_COLUMNS)

        # Remove colunas aninhadas não expandidas e extras sem uso
        cols_to_drop = (NESTED_COLUMNS | EXTRA_API_COLUMNS_TO_DROP) & set(df.columns)
        df = df.drop(columns=list(cols_to_drop), errors="ignore")

        logger.info("Transformação concluída: %d registros finais.", len(df))
        return df

    # ------------------------------------------------------------------
    # Expansão de sub-listas
    # ------------------------------------------------------------------

    @staticmethod
    def _expand_payments(df: pd.DataFrame) -> pd.DataFrame:
        """
        Expande outcome_payments[0] em colunas planas prefixadas com 'payments_'.
        Expande payments[0].bankMovements[0] em colunas 'bankMovements_'.
        """
        if "outcome_payments" not in df.columns:
            return df

        def _first(lst):
            return lst[0] if isinstance(lst, list) and lst else {}

        payments_expanded = (
            df["outcome_payments"]
            .apply(_first)
            .apply(pd.Series)
            .rename(columns=lambda c: f"payments_{c}")
        )

        if "payments_bankMovements" in payments_expanded.columns:
            bm_expanded = (
                payments_expanded["payments_bankMovements"]
                .apply(_first)
                .apply(pd.Series)
                .rename(columns=lambda c: f"bankMovements_{c}")
            )
            payments_expanded = payments_expanded.drop(columns=["payments_bankMovements"])
            payments_expanded = pd.concat([payments_expanded, bm_expanded], axis=1)

        df = df.drop(columns=["outcome_payments"])
        return pd.concat([df, payments_expanded], axis=1)

    @staticmethod
    def _expand_payments_categories(df: pd.DataFrame) -> pd.DataFrame:
        """
        Expande outcome_paymentsCategories[0] → Centro de custo, Plano fin, etc.
        """
        if "outcome_paymentsCategories" not in df.columns:
            return df

        def _first(lst):
            return lst[0] if isinstance(lst, list) and lst else {}

        cats_expanded = (
            df["outcome_paymentsCategories"]
            .apply(_first)
            .apply(pd.Series)
            .rename(columns={
                "costCenterId":           "Cód. centro de custo",
                "costCenterName":         "Centro de custo",
                "financialCategoryId":    "Cód. plano fin",
                "financialCategoryName":  "Plano fin",
                "financialCategoryRate":  "% apropriação financeira",
                "projectId":              "Cód. obra (apropriação)",
                "projectName":            "Obra (apropriação)",
            })
        )

        df = df.drop(columns=["outcome_paymentsCategories"])
        return pd.concat([df, cats_expanded], axis=1)