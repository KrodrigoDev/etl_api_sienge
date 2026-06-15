import logging
import re
import ast

import pandas as pd

from stage.extract.contas_recebidas_extractor import ContasRecebidasExtractionResult

logger = logging.getLogger(__name__)

# =============================================================================
# Mapeamento: coluna interna → nome do relatório
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
    "income_paymentTermName": "Forma de pagamento",
    "income_bearerId": "Cód. portador",

    # --- Receipts ---
    "receipts_operationTypeId": "Tipo operação ID",
    "receipts_operationTypeName": "Tipo de operação",
    "receipts_grossAmount": "Valor recebido",
    "receipts_monetaryCorrectionAmount": "Correção monetária recebida",
    "receipts_interestAmount": "Juros recebidos",
    "receipts_fineAmount": "Multa recebida",
    "receipts_discountAmount": "Desconto recebido",
    "receipts_taxAmount": "Imposto retido recebido",
    "receipts_netAmount": "Valor líquido recebido",
    "receipts_additionAmount": "Acréscimo recebido",
    "receipts_insuranceAmount": "Seguro recebido",
    "receipts_dueAdmAmount": "Taxa adm. recebida",
    "receipts_calculationDate": "Data do cálculo",
    "receipts_paymentDate": "Data do recebimento",
    "receipts_accountCompanyId": "Cód. empresa conta",
    "receipts_accountNumber": "Conta corrente",
    "receipts_accountType": "Tipo conta",
    "receipts_sequencialNumber": "N° sequencial recebimento",
    "receipts_indexerId": "Cód. indexador recebimento",
    "receipts_embeddedInterestAmount": "Juros embutidos recebimento",
    "receipts_creditDate": "Data crédito",
    "receipts_proRata": "Pro rata",

    # --- BankMovements ---
    "bankMovements_id": "Bank Movement ID",
    "bankMovements_bankMovementDate": "Data movimento bancário",
    "bankMovements_sequencialNumber": "N° sequencial movimento",
    "bankMovements_amount": "Valor movimento",
    "bankMovements_historicId": "Cód. histórico bancário",
    "bankMovements_historicName": "Histórico Bancário",
    "bankMovements_operationId": "Cód. operação movimento",
    "bankMovements_operationName": "Operação movimento",
    "bankMovements_operationType": "Tipo operação movimento",
    "bankMovements_reconcile": "Conciliado",
    "bankMovements_correctedAmount": "Valor corrigido movimento",
    "bankMovements_originId": "Origem movimento",

    # --- FinancialCategories (via bankMovements) ---
    "fc_bankMovementId": "Bank Movement ID (FC)",
    "fc_costCenterId": "Cód. centro de custo",
    "fc_costCenterName": "Centro de custo",
    "fc_financialCategoryId": "Cód. plano fin",
    "fc_financialCategoryName": "Plano fin",
    "fc_financialCategoryRate": "% apropriação financeira",
    "fc_financialCategoryReducer": "Redutor plano fin",
    "fc_financialCategoryType": "Tipo plano fin",

    # --- ReceiptsCategories ---
    "receiptsCategories_costCenterId": "Cód. centro de custo (RC)",
    "receiptsCategories_costCenterName": "Centro de custo (RC)",
    "receiptsCategories_financialCategoryId": "Cód. plano fin (RC)",
    "receiptsCategories_financialCategoryName": "Plano fin (RC)",
    "receiptsCategories_financialCategoryRate": "% apropriação financeira (RC)",
    "receiptsCategories_financialCategoryReducer": "Redutor plano fin (RC)",
    "receiptsCategories_financialCategoryType": "Tipo plano fin (RC)",
}


class ContasRecebidasTransformer:
    """
    Transforma dados brutos de contas recebidas em DataFrame analítico.

    Pipeline (equivalente ao Power Query):
      1. Expandir income_paymentTerm  (dict → campo plano)
      2. Explode income_receipts      → 1 linha por receipt
      3. Expandir campos do receipt   → colunas planas receipts_*
      4. Explode bankMovements        → 1 linha por bankMovement
      5. Expandir campos do bm        → colunas planas bankMovements_*
      6. Explode financialCategories  → 1 linha por categoria
      7. Expandir campos da FC        → colunas planas fc_*
      8. Explode income_receiptsCategories → 1 linha por categoria
      9. Expandir campos da RC        → colunas planas receiptsCategories_*
     10. Construir Indexador derivado
     11. Renomear conforme MAPPING_COLUMNS
    """

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_list(val) -> list:
        """
        Converte um valor (string, list, None, NaN) para list.
        Remove sufixos espúrios como ']bankMovements' gerados pelo CSV.
        """
        if isinstance(val, list):
            return val
        s = str(val).strip()
        if s in ("", "[]", "nan", "None"):
            return []
        # Remove lixo textual após o fechamento da lista principal
        s = re.sub(r"\]([a-zA-Z_]+)$", "]", s)
        try:
            return ast.literal_eval(s)
        except Exception:
            return []

    @staticmethod
    def _parse_dict(val) -> dict:
        """Converte um valor para dict."""
        if isinstance(val, dict):
            return val
        s = str(val).strip()
        if s in ("", "nan", "None"):
            return {}
        try:
            return ast.literal_eval(s)
        except Exception:
            return {}

    # ------------------------------------------------------------------
    # Pipeline principal
    # ------------------------------------------------------------------

    def transform(self, result: ContasRecebidasExtractionResult) -> pd.DataFrame:
        if not result.sucesso or not result.registros:
            logger.warning("Nenhum dado disponível para transformação.")
            return pd.DataFrame()

        df = pd.DataFrame(result.registros)

        df = self._expand_payment_term(df)
        df = self._explode_receipts(df)
        df = self._explode_bank_movements(df)
        df = self._explode_financial_categories(df)
        df = self._explode_receipts_categories(df)
        df = self._build_indexador(df)

        df = df.rename(columns=MAPPING_COLUMNS)

        logger.info("Transformação concluída: %d registros finais.", len(df))
        return df

    # ------------------------------------------------------------------
    # Etapas individuais
    # ------------------------------------------------------------------

    def _expand_payment_term(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        income_paymentTerm {'id': 'PM', 'descrition': 'Parcelas Mensais'}
        → income_paymentTermName (apenas a descrição).
        """
        if "income_paymentTerm" not in df.columns:
            return df

        df["income_paymentTermName"] = df["income_paymentTerm"].apply(
            lambda v: (
                self._parse_dict(v).get("descrition")
                or self._parse_dict(v).get("description")
            )
        )
        return df.drop(columns=["income_paymentTerm"])

    def _explode_receipts(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Equivalente a:
          Table.ExpandListColumn(..., "receipts")
          Table.ExpandRecordColumn(..., "receipts", [...campos...])

        Cada receipt vira uma linha separada.
        """
        if "income_receipts" not in df.columns:
            return df

        df["income_receipts"] = df["income_receipts"].apply(self._parse_list)
        df = df.explode("income_receipts", ignore_index=True)

        receipts_df = (
            df["income_receipts"]
            .apply(lambda v: v if isinstance(v, dict) else {})
            .apply(pd.Series)
            .rename(columns=lambda c: f"receipts_{c}")
        )
        return pd.concat(
            [df.drop(columns=["income_receipts"]), receipts_df], axis=1
        )

    def _explode_bank_movements(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Equivalente a:
          Table.ExpandListColumn(..., "bankMovements")
          Table.ExpandRecordColumn(..., "bankMovements", [...campos...])

        Nota: no dado bruto a chave do bankMovements é uma string vazia ''.
        Após o expand de receipts ela vira a coluna 'receipts_'.
        """
        # A chave vazia do receipt vira a coluna 'receipts_' após o expand
        bm_col = "receipts_"
        if bm_col not in df.columns:
            # Fallback: pode vir como 'receipts_bankMovements' se a API corrigir a chave
            bm_col = "receipts_bankMovements"
            if bm_col not in df.columns:
                logger.warning("Coluna de bankMovements não encontrada; etapa ignorada.")
                return df

        df[bm_col] = df[bm_col].apply(
            lambda v: v if isinstance(v, list) else []
        )
        df = df.explode(bm_col, ignore_index=True)

        bm_df = (
            df[bm_col]
            .apply(lambda v: v if isinstance(v, dict) else {})
            .apply(pd.Series)
            .rename(columns=lambda c: f"bankMovements_{c}")
        )
        return pd.concat([df.drop(columns=[bm_col]), bm_df], axis=1)

    def _explode_financial_categories(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Equivalente a:
          Table.ExpandListColumn(..., "financialCategories")
          Table.ExpandRecordColumn(..., "financialCategories", [...campos...])
        """
        fc_col = "bankMovements_financialCategories"
        if fc_col not in df.columns:
            return df

        df[fc_col] = df[fc_col].apply(
            lambda v: v if isinstance(v, list) else []
        )
        df = df.explode(fc_col, ignore_index=True)

        fc_df = (
            df[fc_col]
            .apply(lambda v: v if isinstance(v, dict) else {})
            .apply(pd.Series)
            .rename(columns=lambda c: f"fc_{c}")
        )
        return pd.concat([df.drop(columns=[fc_col]), fc_df], axis=1)

    def _explode_receipts_categories(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Equivalente a:
          Table.ExpandListColumn(..., "receiptsCategories")
          Table.ExpandRecordColumn(..., "receiptsCategories", [...campos...])
        """
        if "income_receiptsCategories" not in df.columns:
            return df

        df["income_receiptsCategories"] = df["income_receiptsCategories"].apply(
            self._parse_list
        )
        df = df.explode("income_receiptsCategories", ignore_index=True)

        rc_df = (
            df["income_receiptsCategories"]
            .apply(lambda v: v if isinstance(v, dict) else {})
            .apply(pd.Series)
            .rename(columns=lambda c: f"receiptsCategories_{c}")
        )
        return pd.concat(
            [df.drop(columns=["income_receiptsCategories"]), rc_df], axis=1
        )

    @staticmethod
    def _build_indexador(df: pd.DataFrame) -> pd.DataFrame:
        """Coluna derivada: 'Cód - Nome' do indexador."""
        if "income_indexerId" in df.columns and "income_indexerName" in df.columns:
            df["Indexador"] = (
                df["income_indexerId"].astype(str)
                + " - "
                + df["income_indexerName"].astype(str)
            )
            df = df.drop(columns=["income_indexerId", "income_indexerName"], errors="ignore")
        return df