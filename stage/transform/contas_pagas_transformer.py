import json
import logging
import re
import ast

import pandas as pd

from stage.extract.contas_pagas_extractor import ContasPagasExtractionResult

logger = logging.getLogger(__name__)

# =============================================================================
# Mapeamento: coluna interna → nome do relatório manual
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

    # # --- Valores base ---
    # "outcome_discountAmount": "Desconto",
    # "outcome_taxAmount": "Valor Imposto Retido",
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

    # --- Payments ---
    # "payments_correctedNetAmount": "Valor líquido",
    "outcome_originalAmount": "Valor bruto",
    "payments_grossAmount": "Valor da baixa", # por algum motivo isso é usado como bruto
    "payments_monetaryCorrectionAmount": "Correção monetária",
    "payments_interestAmount": "Juros",
    "payments_fineAmount": "Multa",
    "payments_discountAmount": "Desconto",
    "payments_taxAmount": "Taxas",
    "payments_netAmount": "Valor líquido",
    "payments_paymentDate": "Data do pagamento",
    "payments_calculationDate": "Data do cálculo",
    "payments_operationTypeName": "Tipo de Baixa",
    "payments_operationTypeId": "Tipo operação ID",
    "payments_paymentAuthentication": "Autenticação eletrônica",
    "payments_sequencialNumber": "N° sequencial pagamento",

    # --- BankMovements ---
    # "bankMovements_id": "Bank Movement ID",
    # "bankMovements_accountNumber": "Conta corrente",
    # "bankMovements_historicName": "Histórico",
    # "bankMovements_operationName": "Descrição do pagamento",
    # "bankMovements_bankMovementDate": "Data movimento bancário",
    # "bankMovements_sequencialNumber": "N° sequencial movimento",
    # "bankMovements_amount": "Valor movimento",
    # "bankMovements_historicId": "Cód. histórico bancário",
    # "bankMovements_operationId": "Cód. operação movimento",
    # "bankMovements_operationType": "Tipo operação movimento",
    # "bankMovements_reconcile": "Conciliado",
    # "bankMovements_originId": "Origem movimento",
    # "bankMovements_accountCompanyId": "Cód. empresa conta",
    # "bankMovements_accountType": "Tipo conta",

    # --- PaymentCategories (via bankMovements) ---
    "paymentCategories_costCenterId": "Cód. centro de custo",
    "paymentCategories_costCenterName": "Centro de custo",
    "paymentCategories_financialCategoryId": "Cód. plano fin",
    "paymentCategories_financialCategoryName": "Plano fin",
    "paymentCategories_financialCategoryReducer": "Redutor plano fin",
    "paymentCategories_financialCategoryType": "Tipo plano fin",

    # --- PaymentsCategories (outcome nível) ---
    "paymentsCategories_costCenterId": "Cód. centro de custo",
    "paymentsCategories_costCenterName": "Centro de custo",
    "paymentsCategories_financialCategoryId": "Cód. plano fin (PC)",
    "paymentsCategories_financialCategoryName": "Plano fin (PC)",
    "paymentsCategories_financialCategoryRate": "% apropriação financeira",
    "paymentsCategories_financialCategoryReducer": "Redutor plano fin (PC)",
    "paymentsCategories_financialCategoryType": "Tipo plano fin (PC)",
    "paymentsCategories_projectId": "Cód. obra (apropriação)",
    "paymentsCategories_projectName": "Obra (apropriação)",

    # --- BuildingsCosts ---
    "buildingscosts_buildingId": "Cód. edificio",
    "buildingscosts_buildingName": "Edificio",
    "buildingscosts_buildingUnitId": "Cód. unidade construtiva",
    "buildingscosts_buildingUnitName": "Unidade construtiva",
    "buildingscosts_costEstimationSheetId": "Cód. item orçamento",
    "buildingscosts_costEstimationSheetName": "Item orçamento",
    "buildingscosts_rate": "taxa_custo_edificio",
}

# outcome_taxAmount corrompido acima desse limite usa fallback via payments_netAmount
_LIMITE_TAX_VALIDO = 1_000_000

# Colunas que a API não fornece no endpoint bulk-data/v1/outcome
NOT_AVAILABLE_IN_API = [
    "Acréscimo",
    "Cód. unid. construtiva", "Unid. construtiva",
    "Cód. Item orçamento", "Item orçamento", "% apropriação obra",
    "Cód. departamento", "Departamento", "% apropriação departamento",
    "Vencimento original", "Diferença data vencimento", "Dias de atraso",
    "N° lote", "Status do lote", "Ciência do título", "Status da parcela",
    "Parcela agrupada", "Título/Parcela agrupada", "Tipo credor", "Cheque",
    "Usuário que deu ciência", "Usuário que autorizou",
    "Usuário que alterou", "Data de alteração",
    "Conta contábil", "Data de competência",
    "CNPJ/CPF", "Chave NFE", "Informações bancárias do Credor",
    "Pix do credor", "Forma de pagamento",
    "Observação do título", "Observação da baixa", "Ações",
]


class ContasPagasTransformer:
    """
    Transforma dados brutos de contas pagas em DataFrame analítico.

    Hierarquia de aninhamento da API:
        outcome (título/parcela)
        ├── payments[ ]                     → 1 linha por payment
        │   └── bankMovements[ ]            → 1 linha por bankMovement
        │       └── paymentCategories[ ]    → 1 linha por categoria financeira do bm
        ├── paymentsCategories[ ]           → produto cartesiano com bankMovements
        └── buildingsCosts[ ]              → produto cartesiano com paymentsCategories

    O resultado final é o produto:
        payments × bankMovements × paymentCategories(bm) × paymentsCategories × buildingsCosts

    Isso é intencional: cada linha representa a alocação de custo na intersecção
    (movimento bancário × plano financeiro do outcome × unidade construtiva),
    permitindo ao Power BI agregar por qualquer combinação dessas dimensões.

    CHAVE DE DEDUPLICAÇÃO CORRETA no transformer_2:
        ['outcome_billId', 'outcome_installmentId', 'outcome_companyId',
         'bankMovements_id', 'paymentsCategories_financialCategoryId',
         'buildingscosts_costEstimationSheetId']

    Pipeline:
      1. Explode outcome_payments           → 1 linha por payment
      2. Expandir campos do payment         → colunas planas payments_*
      3. Explode bankMovements              → 1 linha por bankMovement
      4. Expandir campos do bm             → colunas planas bankMovements_*
      5. Explode paymentCategories(bm)      → 1 linha por categoria do bm
      6. Expandir campos da PC(bm)         → colunas planas paymentCategories_*
      7. Explode paymentsCategories(outcome)→ produto ×  bankMovements
      8. Expandir campos da PC(outcome)    → colunas planas paymentsCategories_*
      9. Explode buildingsCosts            → produto × paymentsCategories
     10. Expandir campos do bc             → colunas planas buildingscosts_*
     11. Construir colunas derivadas (Indexador, Grupo, Valor líquido)
     12. Renomear conforme MAPPING_COLUMNS

    Notas sobre Valor líquido:
      - Regra normal:   originalAmount - taxAmount
      - Fallback:       payments_netAmount quando taxAmount > 1_000_000 (dado corrompido na API)
      - Sem pagamento:  NA
    """

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_list(val) -> list:
        """
        Converte string/None/NaN para list.

        Tenta json.loads primeiro (16× mais rápido que ast.literal_eval).
        Usa ast.literal_eval como fallback para strings com sintaxe Python
        (aspas simples, None, True/False).
        Remove sufixos espúrios do CSV (ex: "]outcome_payments").
        """
        if isinstance(val, list):
            return val
        s = str(val).strip()
        if s in ("", "[]", "nan", "None"):
            return []

        # Remove sufixo espúrio que aparece quando o CSV é gravado sem quoting correto
        s = re.sub(r"\]([a-zA-Z_]+)$", "]", s)

        # Tenta JSON primeiro (mais rápido): normaliza sintaxe Python → JSON
        s_json = (
            s
            .replace("'", '"')
            .replace(": None", ": null")
            .replace(":None", ": null")
            .replace("True", "true")
            .replace("False", "false")
        )
        try:
            return json.loads(s_json)
        except (json.JSONDecodeError, ValueError):
            pass

        # Fallback para ast.literal_eval (lida com casos que json.loads não consegue)
        try:
            return ast.literal_eval(s)
        except Exception:
            return []

    @staticmethod
    def _expand_records(series: pd.Series, prefix: str) -> pd.DataFrame:
        """
        Expande uma Series de dicts em colunas planas com prefixo.

        Usa pd.json_normalize ao invés de apply(pd.Series):
        ~11× mais rápido e preserva o índice original.
        """
        records = [v if isinstance(v, dict) else {} for v in series]
        result = pd.json_normalize(records)
        result.columns = [f"{prefix}{c}" for c in result.columns]
        result.index = series.index
        return result

    # ------------------------------------------------------------------
    # Pipeline principal
    # ------------------------------------------------------------------

    def transform(self, result: ContasPagasExtractionResult) -> pd.DataFrame:
        if not result.sucesso or not result.registros:
            logger.warning("Nenhum dado disponível para transformação.")
            return pd.DataFrame()

        df = pd.DataFrame(result.registros)

        df = self._explode_payments(df)
        # df = self._explode_bank_movements(df)
        df = self._explode_payment_categories(df)
        df = self._explode_payments_categories(df)
        df = self._explode_buildingscosts(df)
        df = self._build_derived_columns(df)

        df = df.rename(columns=MAPPING_COLUMNS)

        cols_to_drop = {"outcome_departamentsCosts"} & set(df.columns)
        df = df.drop(columns=list(cols_to_drop), errors="ignore")

        logger.info("Transformação concluída: %d registros finais.", len(df))
        return df

    # ------------------------------------------------------------------
    # Etapas individuais
    # ------------------------------------------------------------------

    def _explode_payments(self, df: pd.DataFrame) -> pd.DataFrame:
        """Explode outcome_payments → 1 linha por payment."""
        if "outcome_payments" not in df.columns:
            return df

        df["outcome_payments"] = df["outcome_payments"].apply(self._parse_list)
        df = df.explode("outcome_payments", ignore_index=True)

        pay_df = self._expand_records(df["outcome_payments"], "payments_")
        return pd.concat([df.drop(columns=["outcome_payments"]), pay_df], axis=1)

    def _explode_bank_movements(self, df: pd.DataFrame) -> pd.DataFrame:
        """Explode payments_bankMovements → 1 linha por bankMovement."""
        bm_col = "payments_bankMovements"
        if bm_col not in df.columns:
            logger.warning("Coluna %s não encontrada; etapa ignorada.", bm_col)
            return df

        df[bm_col] = df[bm_col].apply(lambda v: v if isinstance(v, list) else [])
        df = df.explode(bm_col, ignore_index=True)

        bm_df = self._expand_records(df[bm_col], "bankMovements_")
        return pd.concat([df.drop(columns=[bm_col]), bm_df], axis=1)

    def _explode_payment_categories(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Explode bankMovements_paymentCategories → 1 linha por categoria do bankMovement.

        Esta é a categoria financeira associada ao movimento bancário (paymentCategories),
        diferente de paymentsCategories que é a categoria do título (outcome).
        """
        pc_col = "bankMovements_paymentCategories"
        if pc_col not in df.columns:
            return df

        df[pc_col] = df[pc_col].apply(lambda v: v if isinstance(v, list) else [])
        df = df.explode(pc_col, ignore_index=True)

        pc_df = self._expand_records(df[pc_col], "paymentCategories_")
        return pd.concat([df.drop(columns=[pc_col]), pc_df], axis=1)

    def _explode_payments_categories(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Explode outcome_paymentsCategories → produto cartesiano com as linhas de bankMovements.

        paymentsCategories é a decomposição do título por plano financeiro (nível outcome),
        independente dos bankMovements. Cada linha já existente é replicada para cada
        categoria financeira — isso é intencional para permitir alocação de custo.

        A explosão de buildingsCosts em seguida completa o produto:
            bankMovements × paymentsCategories × buildingsCosts
        """
        if "outcome_paymentsCategories" not in df.columns:
            return df

        df["outcome_paymentsCategories"] = df["outcome_paymentsCategories"].apply(self._parse_list)
        df = df.explode("outcome_paymentsCategories", ignore_index=True)

        cats_df = self._expand_records(df["outcome_paymentsCategories"], "paymentsCategories_")
        return pd.concat([df.drop(columns=["outcome_paymentsCategories"]), cats_df], axis=1)

    def _explode_buildingscosts(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Explode outcome_buildingsCosts → produto cartesiano com paymentsCategories.

        buildingsCosts é a decomposição do título por unidade construtiva (nível outcome),
        independente de paymentsCategories. Cada linha já existente é replicada para cada
        unidade construtiva — completando o produto cartesiano intencional.

        RESULTADO ESPERADO por título com N paymentsCategories e M buildingsCosts:
            linhas_bm × N × M
        onde linhas_bm = número de bankMovements (1 quando sem pagamento registrado).

        CHAVE DE DEDUP CORRETA no transformer_2 para evitar duplicatas reais:
            ['outcome_billId', 'outcome_installmentId', 'outcome_companyId',
             'bankMovements_id',
             'paymentsCategories_financialCategoryId',
             'buildingscosts_costEstimationSheetId']
        """
        if "outcome_buildingsCosts" not in df.columns:
            return df

        df["outcome_buildingsCosts"] = df["outcome_buildingsCosts"].apply(self._parse_list)
        df = df.explode("outcome_buildingsCosts", ignore_index=True)

        bc_df = self._expand_records(df["outcome_buildingsCosts"], "buildingscosts_")
        return pd.concat([df.drop(columns=["outcome_buildingsCosts"]), bc_df], axis=1)

    def _build_derived_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Constrói Indexador, Grupo e Valor líquido calculado."""

        # Indexador composto "Cód - Nome"
        if "outcome_indexerId" in df.columns and "outcome_indexerName" in df.columns:
            df["Indexador"] = (
                df["outcome_indexerId"].astype(str)
                + " - "
                + df["outcome_indexerName"].astype(str)
            )
            df = df.drop(columns=["outcome_indexerId", "outcome_indexerName"], errors="ignore")

        # Grupo "Título/Parcela"
        if "outcome_billId" in df.columns and "outcome_installmentId" in df.columns:
            df["Grupo"] = (
                df["outcome_billId"].astype(str)
                + "/"
                + df["outcome_installmentId"].astype(str)
            )

        return df