import logging

import pandas as pd
import ast


from stage.extract.contas_recebidas_extractor import ContasRecebidasExtractionResult

logger = logging.getLogger(__name__)

# =============================================================================
# Mapeamento: coluna da API → nome do relatório
# =============================================================================
MAPPING_COLUMNS = {
    # --- Empresa / estrutura ---
    "income_companyId": "Cód. empresa",
    "income_companyName": "Empresa",
    "income_groupCompanyId": "Cód. grupo empresa",
    "income_groupCompanyName": "Grupo empresa",
    "income_holdingId": "Cód. holding",
    "income_holdingName": "Holding",
    "income_subsidiaryId": "Cód. subsidiária",
    "income_subsidiaryName": "Subsidiária",
    "income_businessAreaId": "Cód. área negócio",
    "income_businessAreaName": "Área negócio",
    "income_businessTypeId": "Cód. tipo negócio",
    "income_businessTypeName": "Tipo negócio",

    # --- Cliente ---
    "income_clientId": "Cód. cliente",
    "income_clientName": "Cliente",

    # --- Título / Parcela ---
    "income_billId": "Título",
    "income_installmentId": "Parcela",
    "income_installmentNumber": "N° parcela",

    # --- Documento ---
    "income_documentIdentificationId": "Sigla documento",
    "income_documentIdentificationName": "Documento",
    "income_documentNumber": "N° documento",
    "income_documentForecast": "Documento previsão",

    # --- Origem / status ---
    "income_originId": "Origem",
    "income_defaulterSituation": "Situação inadimplência",
    "income_subJudicie": "Sub judice",

    # --- Valores base ---
    "income_originalAmount": "Valor bruto",
    "income_discountAmount": "Desconto",
    "income_taxAmount": "Valor Imposto Retido",
    "income_balanceAmount": "Saldo em aberto",
    "income_correctedBalanceAmount": "Saldo corrigido em aberto",
    "income_embeddedInterestAmount": "Juros embutidos",

    # --- Juros / correção ---
    "income_interestType": "Tipo juros",
    "income_interestRate": "Taxa juros",
    "income_correctionType": "Tipo correção",
    "income_interestBaseDate": "Data base juros",
    "income_periodicityType": "Periodicidade",

    # --- Datas base ---
    "income_dueDate": "Data vencimento",
    "income_issueDate": "Data emissão",
    "income_billDate": "Data contábil",
    "income_installmentBaseDate": "Data base",

    # --- Obra / projeto ---
    "income_projectId": "Cód. obra",
    "income_projectName": "Obra",

    # --- Unidade / contrato ---
    "income_mainUnit": "Unidade",
    "income_paymentTermName": "Forma de pagamento",  # expandido de income_paymentTerm
    "income_bearerId": "Cód. portador",

    # --- Receipts (expandidos de income_receipts) ---
    "receipts_grossAmount": "Valor recebido",
    "receipts_netAmount": "Valor líquido recebido",
    "receipts_interestAmount": "Juros recebidos",
    "receipts_fineAmount": "Multa recebida",
    "receipts_discountAmount": "Desconto recebido",
    "receipts_taxAmount": "Imposto retido recebido",
    "receipts_additionAmount": "Acréscimo recebido",
    "receipts_paymentDate": "Data do recebimento",
    "receipts_calculationDate": "Data do cálculo",
    "receipts_operationTypeName": "Tipo de operação",
    "receipts_accountNumber": "Conta corrente",

    # --- ReceiptsCategories (expandidos de income_receiptsCategories[0]) ---
    "receiptsCategories_costCenterId": "Cód. centro de custo",
    "receiptsCategories_costCenterName": "Centro de custo",
    "receiptsCategories_financialCategoryId": "Cód. plano fin",
    "receiptsCategories_financialCategoryName": "Plano fin",
    "receiptsCategories_financialCategoryRate": "% apropriação financeira",
}

# Colunas aninhadas removidas após expansão
NESTED_COLUMNS = {
    "income_receipts",
    "income_receiptsCategories",
    "income_paymentTerm",
}

# Colunas da API sem equivalente no relatório (descartadas)
EXTRA_API_COLUMNS_TO_DROP = {
    "receipts_operationTypeId",
    "receipts_monetaryCorrectionAmount",
    "receipts_insuranceAmount",
    "receipts_dueAdmAmount",
    "receipts_accountCompanyId",
    "receipts_accountType",
    "receipts_sequencialNumber",
    "receipts_indexerId",
    "receipts_embeddedInterestAmount",
    "receipts_creditDate",
    "receipts_proRata",
    "receipts_bankMovements",
    "receiptsCategories_projectId",
    "receiptsCategories_businessTypeId",
    "receiptsCategories_businessAreaId",
    "receiptsCategories_projectName",
    "receiptsCategories_businessTypeName",
    "receiptsCategories_businessAreaName",
    "receiptsCategories_financialCategoryReducer",
    "receiptsCategories_financialCategoryType",
}


class ContasRecebidasTransformer:
    """
    Transforma dados brutos de contas recebidas em DataFrame analítico.

    Pipeline:
      1. Montar DataFrame bruto
      2. Expandir income_paymentTerm (dict → campo plano)
      3. Expandir income_receipts (lista → colunas agregadas)
      4. Expandir income_receiptsCategories[0] (primeiro item)
      5. Construir colunas derivadas (Indexador, Grupo)
      6. Renomear conforme MAPPING_COLUMNS
      7. Descartar colunas sem uso

    Diferenças em relação ao ContasPagasTransformer:
      - Entidade principal é Cliente (não Credor)
      - Sub-lista é income_receipts (não outcome_payments)
      - income_receipts não tem bankMovements aninhado relevante —
        accountNumber já está no nível do receipt
      - Campos extras: periodicidade, juros embutidos, unidade,
        forma de pagamento, situação inadimplência, sub judice
    """

    def transform(self, result: ContasRecebidasExtractionResult) -> pd.DataFrame:
        if not result.sucesso or not result.registros:
            logger.warning("Nenhum dado disponível para transformação.")
            return pd.DataFrame()

        df = pd.DataFrame(result.registros)

        df = self._expand_payment_term(df)
        df = self._expand_receipts(df)
        df = self._expand_receipts_categories(df)

        # Coluna derivada: Indexador composto "Cód - Nome"
        df["Indexador"] = (
            df["income_indexerId"].astype(str)
            + " - "
            + df["income_indexerName"].astype(str)
        )
        df = df.drop(columns=["income_indexerId", "income_indexerName"], errors="ignore")

        df = df.rename(columns=MAPPING_COLUMNS)

        # Remove colunas aninhadas e extras sem uso
        cols_to_drop = (NESTED_COLUMNS | EXTRA_API_COLUMNS_TO_DROP) & set(df.columns)
        df = df.drop(columns=list(cols_to_drop), errors="ignore")

        logger.info("Transformação concluída: %d registros finais.", len(df))
        return df

    # ------------------------------------------------------------------
    # Expansão de sub-estruturas
    # ------------------------------------------------------------------
    @staticmethod
    def _parse(val):
        if isinstance(val, list):
            return val

        if val is None:
            return []

        if isinstance(val, float) and pd.isna(val):
            return []

        txt = str(val).strip()

        if txt in ("", "[]", "nan", "None"):
            return []

        try:
            return ast.literal_eval(txt)
        except Exception:
            return []

    @staticmethod
    def _expand_payment_term(df: pd.DataFrame) -> pd.DataFrame:
        """
        Expande income_paymentTerm {'id': 'PM', 'descrition': 'Parcelas Mensais'}
        → income_paymentTermName (mantém apenas a descrição).
        """
        if "income_paymentTerm" not in df.columns:
            return df

        def _extract_name(val):
            if pd.isna(val) or str(val).strip() in ["nan", ""]:
                return None
            try:
                import ast
                parsed = ast.literal_eval(str(val))
                if isinstance(parsed, dict):
                    return parsed.get("descrition") or parsed.get("description")
            except Exception:
                pass
            return None

        df["income_paymentTermName"] = df["income_paymentTerm"].apply(_extract_name)
        return df

    @staticmethod
    def _expand_receipts(df: pd.DataFrame) -> pd.DataFrame:
        """
        Agrega todos os registros de income_receipts em colunas planas.

        Campos monetários somados:
            grossAmount, monetaryCorrectionAmount, interestAmount,
            fineAmount, discountAmount, taxAmount, netAmount,
            additionAmount, insuranceAmount, dueAdmAmount

        Para campos não monetários (data, tipo operação, conta),
        mantém o último valor encontrado — alinhado com o comportamento
        do relatório manual que exibe o pagamento mais recente.
        """
        if "income_receipts" not in df.columns:
            return df

        def _aggregate_receipts(receipts):
            if not isinstance(receipts, list) or not receipts:
                return {}

            result = {
                "receipts_grossAmount": 0.0,
                "receipts_monetaryCorrectionAmount": 0.0,
                "receipts_interestAmount": 0.0,
                "receipts_fineAmount": 0.0,
                "receipts_discountAmount": 0.0,
                "receipts_taxAmount": 0.0,
                "receipts_netAmount": 0.0,
                "receipts_additionAmount": 0.0,
                "receipts_insuranceAmount": 0.0,
                "receipts_dueAdmAmount": 0.0,
                "receipts_paymentDate": None,
                "receipts_calculationDate": None,
                "receipts_operationTypeName": None,
                "receipts_accountNumber": None,
                "receipts_accountCompanyId": None,
                "receipts_accountType": None,
                "receipts_sequencialNumber": None,
                "receipts_indexerId": None,
                "receipts_embeddedInterestAmount": 0.0,
                "receipts_creditDate": None,
                "receipts_proRata": 0.0,
                "receipts_operationTypeId": None,
                "receipts_bankMovements": [],
            }

            for receipt in receipts:
                if not isinstance(receipt, dict):
                    continue

                result["receipts_grossAmount"] += receipt.get("grossAmount", 0) or 0
                result["receipts_monetaryCorrectionAmount"] += receipt.get("monetaryCorrectionAmount", 0) or 0
                result["receipts_interestAmount"] += receipt.get("interestAmount", 0) or 0
                result["receipts_fineAmount"] += receipt.get("fineAmount", 0) or 0
                result["receipts_discountAmount"] += receipt.get("discountAmount", 0) or 0
                result["receipts_taxAmount"] += receipt.get("taxAmount", 0) or 0
                result["receipts_netAmount"] += receipt.get("netAmount", 0) or 0
                result["receipts_additionAmount"] += receipt.get("additionAmount", 0) or 0
                result["receipts_insuranceAmount"] += receipt.get("insuranceAmount", 0) or 0
                result["receipts_dueAdmAmount"] += receipt.get("dueAdmAmount", 0) or 0
                result["receipts_embeddedInterestAmount"] += receipt.get("embeddedInterestAmount", 0) or 0
                result["receipts_proRata"] += receipt.get("proRata", 0) or 0

                # Último valor encontrado (alinhado com relatório manual)
                if receipt.get("paymentDate") is not None:
                    result["receipts_paymentDate"] = receipt.get("paymentDate")
                if receipt.get("calculationDate") is not None:
                    result["receipts_calculationDate"] = receipt.get("calculationDate")
                if receipt.get("operationTypeName") is not None:
                    result["receipts_operationTypeName"] = receipt.get("operationTypeName")
                if receipt.get("accountNumber") is not None:
                    result["receipts_accountNumber"] = receipt.get("accountNumber")
                if receipt.get("operationTypeId") is not None:
                    result["receipts_operationTypeId"] = receipt.get("operationTypeId")
                if receipt.get("accountCompanyId") is not None:
                    result["receipts_accountCompanyId"] = receipt.get("accountCompanyId")
                if receipt.get("accountType") is not None:
                    result["receipts_accountType"] = receipt.get("accountType")
                if receipt.get("sequencialNumber") is not None:
                    result["receipts_sequencialNumber"] = receipt.get("sequencialNumber")
                if receipt.get("indexerId") is not None:
                    result["receipts_indexerId"] = receipt.get("indexerId")
                if receipt.get("creditDate") is not None:
                    result["receipts_creditDate"] = receipt.get("creditDate")

                bm = receipt.get("bankMovements", [])
                if isinstance(bm, list):
                    result["receipts_bankMovements"].extend(bm)

            return result

        receipts_parsed = df["income_receipts"].apply(ContasRecebidasTransformer._parse)
        receipts_expanded = receipts_parsed.apply(_aggregate_receipts).apply(pd.Series)

        df = df.drop(columns=["income_receipts"])

        return pd.concat(
            [df.reset_index(drop=True), receipts_expanded.reset_index(drop=True)],
            axis=1,
        )

    @staticmethod
    def _expand_receipts_categories(df: pd.DataFrame) -> pd.DataFrame:
        """
        Expande income_receiptsCategories[0] → Centro de custo, Plano fin, etc.
        Usa apenas o primeiro item (mesmo padrão do ContasPagasTransformer).
        """
        if "income_receiptsCategories" not in df.columns:
            return df

        def _first(lst):
            return lst[0] if isinstance(lst, list) and lst else {}

        cats_expanded = (
            df["income_receiptsCategories"]
            .apply(ContasRecebidasTransformer._parse)
            .apply(_first)
            .apply(pd.Series)
            .rename(columns={
                "costCenterId": "receiptsCategories_costCenterId",
                "costCenterName": "receiptsCategories_costCenterName",
                "financialCategoryId": "receiptsCategories_financialCategoryId",
                "financialCategoryName": "receiptsCategories_financialCategoryName",
                "financialCategoryRate": "receiptsCategories_financialCategoryRate",
                "financialCategoryReducer": "receiptsCategories_financialCategoryReducer",
                "financialCategoryType": "receiptsCategories_financialCategoryType",
                "projectId": "receiptsCategories_projectId",
                "projectName": "receiptsCategories_projectName",
                "businessTypeId": "receiptsCategories_businessTypeId",
                "businessTypeName": "receiptsCategories_businessTypeName",
                "businessAreaId": "receiptsCategories_businessAreaId",
                "businessAreaName": "receiptsCategories_businessAreaName",
            })
        )

        df = df.drop(columns=["income_receiptsCategories"])
        return pd.concat([df, cats_expanded], axis=1)
