import logging
import re
import ast

import pandas as pd

from stage.extract.contas_a_receber_extractor import ContasAReceberExtractionResult

logger = logging.getLogger(__name__)

# =============================================================================
# Mapeamento: coluna interna → nome do relatório
# =============================================================================
MAPPING_COLUMNS = {
    # --- Empresa / estrutura ---
    "receivable_companyId": "Cód. empresa",
    "receivable_companyName": "Empresa",
    "receivable_groupCompanyId": "Cód. grupo empresa",
    "receivable_groupCompanyName": "Grupo empresa",
    "receivable_holdingId": "Cód. holding",
    "receivable_holdingName": "Holding",
    "receivable_subsidiaryId": "Cód. subsidiária",
    "receivable_subsidiaryName": "Subsidiária",
    "receivable_businessAreaId": "Cód. área negócio",
    "receivable_businessAreaName": "Área negócio",
    "receivable_businessTypeId": "Cód. tipo negócio",
    "receivable_businessTypeName": "Tipo negócio",

    # --- Cliente ---
    "receivable_clientId": "Cód. cliente",
    "receivable_clientName": "Cliente",

    # --- Título / Parcela ---
    "receivable_billId": "Título",
    "receivable_installmentId": "Parcela",
    "receivable_installmentNumber": "N° parcela",

    # --- Documento ---
    "receivable_documentIdentificationId": "Sigla documento",
    "receivable_documentIdentificationName": "Documento",
    "receivable_documentNumber": "N° documento",
    "receivable_documentForecast": "Documento previsão",

    # --- Origem / status ---
    "receivable_originId": "Origem",
    "receivable_defaulterSituation": "Situação inadimplência",
    "receivable_subJudicie": "Sub judice",

    # --- Valores base ---
    "receivable_originalAmount": "Valor bruto",
    "receivable_discountAmount": "Desconto",
    "receivable_taxAmount": "Valor Imposto Retido",
    "receivable_balanceAmount": "Saldo em aberto",
    "receivable_correctedBalanceAmount": "Saldo corrigido em aberto",
    "receivable_embeddedInterestAmount": "Juros embutidos",

    # --- Juros / correção ---
    "receivable_interestType": "Tipo juros",
    "receivable_interestRate": "Taxa juros",
    "receivable_correctionType": "Tipo correção",
    "receivable_interestBaseDate": "Data base juros",
    "receivable_periodicityType": "Periodicidade",

    # --- Datas base ---
    "receivable_dueDate": "Data vencimento",
    "receivable_issueDate": "Data emissão",
    "receivable_billDate": "Data contábil",
    "receivable_installmentBaseDate": "Data base",

    # --- Obra / projeto ---
    "receivable_projectId": "Cód. obra",
    "receivable_projectName": "Obra",

    # --- Unidade / contrato ---
    "receivable_mainUnit": "Unidade",
    "receivable_paymentTermName": "Forma de pagamento",
    "receivable_bearerId": "Cód. portador",

    # --- Receipts (baixas) ---
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


class ContasAReceberTransformer:
    """
    Transforma dados brutos de contas a receber em DataFrame analítico.

    Pipeline:
      1. Expandir receivable_paymentTerm  (dict → campo plano)
      2. Explode receivable_receipts      → 1 linha por receipt (baixa)
      3. Expandir campos do receipt       → colunas planas receipts_*
      4. Explode bankMovements            → 1 linha por bankMovement
      5. Expandir campos do bm            → colunas planas bankMovements_*
      6. Explode financialCategories      → 1 linha por categoria
      7. Expandir campos da FC            → colunas planas fc_*
      8. Explode receivable_receiptsCategories → 1 linha por categoria
      9. Expandir campos da RC            → colunas planas receiptsCategories_*
     10. Construir Indexador derivado
     11. Renomear conforme MAPPING_COLUMNS

    Nota: o extractor já expande bankMovements e financialCategories
    durante a coleta, portanto o transformer trata apenas o caso em que
    os dados chegam "pré-expandidos" (prefixos bankMovements_* e fc_*
    já presentes). As etapas de explode abaixo servem como fallback para
    dados vindos de CSV ou outras fontes que preservem as listas aninhadas.
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

    def transform(self, result: ContasAReceberExtractionResult) -> pd.DataFrame:
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
        receivable_paymentTerm {'id': 'PM', 'description': 'Parcelas Mensais'}
        → receivable_paymentTermName (apenas a descrição).
        """
        if "receivable_paymentTerm" not in df.columns:
            return df

        df["receivable_paymentTermName"] = df["receivable_paymentTerm"].apply(
            lambda v: (
                self._parse_dict(v).get("description")
                or self._parse_dict(v).get("descrition")  # typo histórico da API
            )
        )
        return df.drop(columns=["receivable_paymentTerm"])

    def _explode_receipts(self, df: pd.DataFrame) -> pd.DataFrame:
        """Cada receipt (baixa) vira uma linha separada."""
        col = "receivable_receipts"
        if col not in df.columns:
            return df

        df[col] = df[col].apply(self._parse_list)
        df = df.explode(col, ignore_index=True)

        receipts_df = (
            df[col]
            .apply(lambda v: v if isinstance(v, dict) else {})
            .apply(pd.Series)
            .rename(columns=lambda c: f"receipts_{c}")
        )
        return pd.concat([df.drop(columns=[col]), receipts_df], axis=1)

    def _explode_bank_movements(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Cada bankMovement vira uma linha separada.

        A chave dentro do receipt é 'bankMovements', que após o explode
        de receipts se torna a coluna 'receipts_bankMovements'.
        """
        col = "receipts_bankMovements"
        if col not in df.columns:
            logger.warning("Coluna '%s' não encontrada; etapa ignorada.", col)
            return df

        df[col] = df[col].apply(
            lambda v: v if isinstance(v, list) else self._parse_list(v)
        )
        df = df.explode(col, ignore_index=True)

        bm_df = (
            df[col]
            .apply(lambda v: v if isinstance(v, dict) else {})
            .apply(pd.Series)
            .rename(columns=lambda c: f"bankMovements_{c}")
        )
        return pd.concat([df.drop(columns=[col]), bm_df], axis=1)

    def _explode_financial_categories(self, df: pd.DataFrame) -> pd.DataFrame:
        """Cada financialCategory (dentro de bankMovement) vira uma linha."""
        col = "bankMovements_financialCategories"
        if col not in df.columns:
            return df

        df[col] = df[col].apply(
            lambda v: v if isinstance(v, list) else self._parse_list(v)
        )
        df = df.explode(col, ignore_index=True)

        fc_df = (
            df[col]
            .apply(lambda v: v if isinstance(v, dict) else {})
            .apply(pd.Series)
            .rename(columns=lambda c: f"fc_{c}")
        )
        return pd.concat([df.drop(columns=[col]), fc_df], axis=1)

    def _explode_receipts_categories(self, df: pd.DataFrame) -> pd.DataFrame:
        """Cada receiptsCategory vira uma linha separada."""
        col = "receivable_receiptsCategories"
        if col not in df.columns:
            return df

        df[col] = df[col].apply(self._parse_list)
        df = df.explode(col, ignore_index=True)

        rc_df = (
            df[col]
            .apply(lambda v: v if isinstance(v, dict) else {})
            .apply(pd.Series)
            .rename(columns=lambda c: f"receiptsCategories_{c}")
        )
        return pd.concat([df.drop(columns=[col]), rc_df], axis=1)

    @staticmethod
    def _build_indexador(df: pd.DataFrame) -> pd.DataFrame:
        """Coluna derivada: 'Cód - Nome' do indexador."""
        if "receivable_indexerId" in df.columns and "receivable_indexerName" in df.columns:
            df["Indexador"] = (
                df["receivable_indexerId"].astype(str)
                + " - "
                + df["receivable_indexerName"].astype(str)
            )
            df = df.drop(
                columns=["receivable_indexerId", "receivable_indexerName"],
                errors="ignore",
            )
        return df