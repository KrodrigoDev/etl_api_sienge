import logging

import pandas as pd

from stage.extract.contas_pagas_extractor import ContasPagasExtractionResult

logger = logging.getLogger(__name__)

# =============================================================================
# Mapeamento: coluna da API → nome do relatório manual
# =============================================================================
MAPPING_COLUMNS = {
    # --- Empresa / estrutura ---
    "outcome_companyId": "Cód. empresa",
    "outcome_companyName": "Empresa",
    "outcome_groupCompanyId": "Cód. grupo empresa",
    "outcome_groupCompanyName": "Grupo empresa",
    "outcome_holdingId": "Cód. holding",
    "outcome_holdingName": "Holding",
    "outcome_subsidiaryId": "Cód. subsidiária",
    "outcome_subsidiaryName": "Subsidiária",
    "outcome_businessAreaId": "Cód. área negócio",
    "outcome_businessAreaName": "Área negócio",
    "outcome_businessTypeId": "Cód. tipo negócio",
    "outcome_businessTypeName": "Tipo negócio",

    # --- Credor ---
    "outcome_creditorId": "Cód. credor",
    "outcome_creditorName": "Credor",

    # --- Título / Parcela ---
    "outcome_billId": "Título",
    "outcome_installmentId": "Parcela",

    # --- Documento ---
    "outcome_documentIdentificationId": "Sigla documento",
    "outcome_documentIdentificationName": "Documento",
    "outcome_documentNumber": "N° documento",
    "outcome_forecastDocument": "Documento previsão",

    # --- Origem / status ---
    "outcome_originId": "Origem",
    "outcome_consistencyStatus": "Status consistência",
    "outcome_authorizationStatus": "Parcela autorizada",

    # --- Valores base ---
    "outcome_originalAmount": "Valor bruto",
    "outcome_discountAmount": "Desconto",
    "outcome_taxAmount": "Valor Imposto Retido",
    "outcome_balanceAmount": "Saldo em aberto",
    "outcome_correctedBalanceAmount": "Saldo corrigido em aberto",

    # --- Datas base ---
    "outcome_dueDate": "Data vencimento",
    "outcome_issueDate": "Data emissão",
    "outcome_installmentBaseDate": "Data base",
    "outcome_billDate": "Data contábil",

    # --- Auditoria ---
    "outcome_registeredUserId": "Cód. usuário que cadastrou",
    "outcome_registeredBy": "Usuário que cadastrou",
    "outcome_registeredDate": "Data de cadastro",

    # --- Obra / projeto ---
    "outcome_projectId": "Cód. obra",
    "outcome_projectName": "Obra",

    # --- Payments (expandidos de outcome_payments[0]) ---
    "payments_correctedNetAmount": "Valor líquido",
    "payments_grossAmount": "Valor da baixa",
    "payments_paymentDate": "Data do pagamento",
    "payments_calculationDate": "Data do cálculo",
    "payments_operationTypeName": "Tipo de operação",
    "payments_paymentAuthentication": "Autenticação eletrônica",

    # --- BankMovements (expandidos de payments[].bankMovements[0]) ---
    "bankMovements_accountNumber": "Conta corrente",
    "bankMovements_historicName": "Histórico",
    "bankMovements_operationName": "Descrição do pagamento",
}

# Colunas que a API não fornece no endpoint bulk-data/v1/outcome
# Listadas aqui apenas como documentação
NOT_AVAILABLE_IN_API = [
    "Acréscimo",  # outcome_taxAmount é imposto retido, não acréscimo
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

# Colunas da API sem equivalente no relatório manual (descartadas)
EXTRA_API_COLUMNS_TO_DROP = {
    "payments_operationTypeId",
    "payments_monetaryCorrectionAmount",
    "payments_interestAmount",
    "payments_fineAmount",
    "payments_discountAmount",
    "payments_sequencialNumber",
    "payments_taxAmount",
    "payments_netAmount",
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

# outcome_taxAmount corrompido acima desse limite usa fallback via payments_netAmount
_LIMITE_TAX_VALIDO = 1_000_000

class ContasPagasTransformer:
    """
    Transforma dados brutos de contas pagas em DataFrame analítico.

    Pipeline:
      1. Montar DataFrame bruto
      2. Expandir sub-listas (payments, bankMovements, paymentsCategories)
      3. Construir colunas derivadas (Indexador, Grupo, Valor líquido)
      4. Renomear conforme MAPPING_COLUMNS
      5. Descartar colunas sem uso

    Notas sobre Valor líquido:
      - Regra normal:   originalAmount - taxAmount
      - Fallback:       soma dos payments[].netAmount
        Ativado quando outcome_taxAmount > 1_000_000 (dado corrompido na API,
        observado em ~148 registros na amostra de 15k).
      - Sem pagamento:  NA (parcela ainda não baixada)
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

        # Coluna derivada: Valor líquido
        # outcome_taxAmount pode vir corrompido (valores absurdos > 1e6);
        # nesses casos usa a soma de payments[].netAmount como fallback.
        df["Valor líquido Calculado"] = df.apply(self._calcular_valor_liquido, axis=1)

        df = df.rename(columns=MAPPING_COLUMNS)

        # Remove colunas aninhadas não expandidas e extras sem uso
        cols_to_drop = (NESTED_COLUMNS | EXTRA_API_COLUMNS_TO_DROP) & set(df.columns)
        df = df.drop(columns=list(cols_to_drop), errors="ignore")

        logger.info("Transformação concluída: %d registros finais.", len(df))
        return df

    # ------------------------------------------------------------------
    # Colunas derivadas
    # ------------------------------------------------------------------

    @staticmethod
    def _calcular_valor_liquido(row: pd.Series):
        """
        Valor líquido = originalAmount - taxAmount.
        Fallback para payments_netAmount quando taxAmount está corrompido (> 1 milhão).
        Retorna NA para parcelas sem pagamento registrado.
        """
        tax = row.get("outcome_taxAmount")
        if pd.isna(tax) or tax > _LIMITE_TAX_VALIDO:
            net = row.get("payments_netAmount")
            return net if (pd.notna(net) and net > 0) else pd.NA
        return row["outcome_originalAmount"] - tax

    # ------------------------------------------------------------------
    # Expansão de sub-listas
    # ------------------------------------------------------------------

    @staticmethod
    def _expand_payments(df: pd.DataFrame) -> pd.DataFrame:
        """
        Agrega todos os registros de outcome_payments em colunas planas.

        Campos monetários somados:
            grossAmount, monetaryCorrectionAmount, interestAmount,
            fineAmount, discountAmount, taxAmount, netAmount, correctedNetAmount

        correctedNetAmount usa netAmount como fallback quando None
        (ex.: operação do tipo "Abatimento de Adiantamento").

        Para bankMovements, mantém apenas o primeiro movimento encontrado.
        """
        if "outcome_payments" not in df.columns:
            return df

        def _aggregate_payments(payments):
            if not isinstance(payments, list) or not payments:
                return {}

            result = {
                "payments_grossAmount": 0.0,
                "payments_monetaryCorrectionAmount": 0.0,
                "payments_interestAmount": 0.0,
                "payments_fineAmount": 0.0,
                "payments_discountAmount": 0.0,
                "payments_taxAmount": 0.0,
                "payments_netAmount": 0.0,
                "payments_correctedNetAmount": 0.0,
                "payments_paymentDate": None,
                "payments_calculationDate": None,
                "payments_operationTypeName": None,
                "payments_paymentAuthentication": None,
                "payments_bankMovements": [],
            }

            for payment in payments:
                if not isinstance(payment, dict):
                    continue

                result["payments_grossAmount"] += payment.get("grossAmount", 0) or 0
                result["payments_monetaryCorrectionAmount"] += payment.get("monetaryCorrectionAmount", 0) or 0
                result["payments_interestAmount"] += payment.get("interestAmount", 0) or 0
                result["payments_fineAmount"] += payment.get("fineAmount", 0) or 0
                result["payments_discountAmount"] += payment.get("discountAmount", 0) or 0
                result["payments_taxAmount"] += payment.get("taxAmount", 0) or 0
                result["payments_netAmount"] += payment.get("netAmount", 0) or 0

                corrected = payment.get("correctedNetAmount")
                net = payment.get("netAmount", 0) or 0
                result["payments_correctedNetAmount"] += corrected if corrected is not None else net

                if payment.get("paymentDate") is not None:
                    result["payments_paymentDate"] = payment.get("paymentDate")
                if result["payments_calculationDate"] is None:
                    result["payments_calculationDate"] = payment.get("calculationDate")
                if result["payments_operationTypeName"] is None:
                    result["payments_operationTypeName"] = payment.get("operationTypeName")
                if result["payments_paymentAuthentication"] is None:
                    result["payments_paymentAuthentication"] = payment.get("paymentAuthentication")

                bank_movements = payment.get("bankMovements", [])
                if isinstance(bank_movements, list):
                    result["payments_bankMovements"].extend(bank_movements)

            return result

        payments_expanded = (
            df["outcome_payments"]
            .apply(_aggregate_payments)
            .apply(pd.Series)
        )

        if "payments_bankMovements" in payments_expanded.columns:
            def _first(lst):
                return lst[0] if isinstance(lst, list) and lst else {}

            bm_expanded = (
                payments_expanded["payments_bankMovements"]
                .apply(_first)
                .apply(pd.Series)
                .rename(columns=lambda c: f"bankMovements_{c}")
            )

            payments_expanded = payments_expanded.drop(columns=["payments_bankMovements"])
            payments_expanded = pd.concat([payments_expanded, bm_expanded], axis=1)

        df = df.drop(columns=["outcome_payments"])

        return pd.concat(
            [df.reset_index(drop=True), payments_expanded.reset_index(drop=True)],
            axis=1,
        )

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
                "costCenterId": "Cód. centro de custo",
                "costCenterName": "Centro de custo",
                "financialCategoryId": "Cód. plano fin",
                "financialCategoryName": "Plano fin",
                "financialCategoryRate": "% apropriação financeira",
                "projectId": "Cód. obra (apropriação)",
                "projectName": "Obra (apropriação)",
            })
        )

        df = df.drop(columns=["outcome_paymentsCategories"])
        return pd.concat([df, cats_expanded], axis=1)
