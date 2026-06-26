"""
Transformação de dados brutos de Vendas.

Responsabilidade única: receber lista de VendasExtractionResult
e retornar um DataFrame limpo e tipado, pronto para carga.
"""
import logging
from typing import List

import pandas as pd

from stage.extract.vendas_extractor import VendasExtractionResult

logger = logging.getLogger(__name__)

# Colunas esperadas na resposta da API (adapte conforme o schema real)
EXPECTED_COLUMNS = [
    "id",
    "enterpriseId",
    "situation",
    "createdAt",
    "buyerName",
    "totalValue",
    "unitId",
    "blockId",
]

RENAME_COLUMNS_VENDAS = {
    # -------------------------
    # Base
    # -------------------------
    "enterpriseId": "id_empresa",
    "empresa_id": "id_empresa_contexto",
    # -------------------------
    # CLIENTES
    # -------------------------
    "clientes_id":"cod_cliente",
    "clientes_name":"nome_cliente",
    "clientes_sex": "sexo_cliente",
    "clientes_profession": "profissao_cliente",
    "clientes_birthDate": "aniversario_cliente",


    # -------------------------
    # SALE
    # -------------------------
    "sale_id": "id_venda",
    "sale_enterpriseId": "cod_centro_de_custo",
    "sale_receivableBillId": "id_titulo_receber",
    "sale_refundBillId": "id_titulo_estorno",
    "sale_proRataIndexer": "indexador_pro_rata",
    "sale_number": "numero_venda",
    "sale_situation": "situacao_venda",
    "sale_externalId": "id_externo_venda",
    "sale_note": "observacao_venda",
    "sale_cancellationReason": "motivo_cancelamento",
    "sale_interestType": "tipo_juros",
    "sale_lateInterestCalculationType": "tipo_calculo_juros_atraso",
    "sale_financialInstitutionNumber": "numero_instituicao_financeira",
    "sale_discountType": "tipo_desconto",
    "sale_correctionType": "tipo_correcao",
    "sale_anualCorrectionType": "tipo_correcao_anual",
    "sale_associativeCredit": "credito_associativo",
    "sale_discountPercentage": "percentual_desconto",
    "sale_value": "valor_venda",
    "sale_totalSellingValue": "valor_total_venda",
    "sale_interestPercentage": "percentual_juros",
    "sale_fineRate": "percentual_multa",
    "sale_dailyLateInterestValue": "valor_juros_diario",
    "sale_creationDate": "data_criacao_venda",
    "sale_contractDate": "data_contrato",
    "sale_issueDate": "data_emissao",
    "sale_cancellationDate": "data_cancelamento",
    "sale_financialInstitutionDate": "data_instituicao_financeira",
    "sale_customers": "clientes",

    # -------------------------
    # UNITS
    # -------------------------
    "units_id": "id_unidade_detalhe",
    "units_main": "unidade_principal",
    "units_name": "nome_unidade",
    "units_participationPercentage": "percentual_participacao",
    "units_propertyType": "tipo_imovel",
    "units_note": "observacao_unidade",
    "units_commercialStock": "estoque_comercial",
    "units_legalRegistrationNumber": "numero_matricula",
    "units_deliveryDate": "data_entrega",
    "units_privateArea": "area_privativa",
    "units_commonArea": "area_comum",
    "units_terrainArea": "area_terreno",
    "units_idealFraction": "fracao_ideal",
    "units_idealFractionSquareMeter": "fracao_ideal_m2",
    "units_indexedQuantity": "quantidade_indexada",
    "units_childUnits": "unidades_filhas",
    "units_groupings": "agrupamentos",

    # -------------------------
    # PAYMENT CONDITIONS
    # -------------------------
    # "paymentConditions_conditionTypeId": "id_tipo_condicao_pagamento",
    # "paymentConditions_conditionTypeName": "nome_tipo_condicao_pagamento",
    # "paymentConditions_bearerId": "id_portador",
    # "paymentConditions_bearerName": "nome_portador",
    # "paymentConditions_installmentsNumber": "numero_parcelas",
    # "paymentConditions_totalValue": "valor_total_condicao_pagamento",
    # "paymentConditions_firstPayment": "data_primeiro_pagamento",

    # -------------------------
    # BROKERS
    # -------------------------
    "brokers_id": "cod_corretor",
    "brokers_name": "nome_corretor",
    "brokers_main": "corretor_principal",
}


class VendasTransformer:

    def transform(self, results: List[VendasExtractionResult]) -> pd.DataFrame:
        sucessos = [r for r in results if r.sucesso and r.registros]
        if not sucessos:
            logger.warning("Nenhum dado disponível para transformação.")
            return pd.DataFrame()

        df = self._consolidate(sucessos)

        print(df.columns)
        df = self._rename_columns(df)

        df = self._cast_dates(df)
        df = self._cast_numerics(df)
        df = self._deduplicate(df)
        df = self._add_derived_metrics(df)

        logger.info("Transformação concluída: %d registros finais.", len(df))
        return df

    @staticmethod
    def _consolidate(results):
        frames = []
        for r in results:
            frame = pd.DataFrame(r.registros)
            frame["enterpriseId"] = r.empresa_id
            frames.append(frame)
        return pd.concat(frames, ignore_index=True)

    @staticmethod
    def _rename_columns(df):
        return df.rename(columns=RENAME_COLUMNS_VENDAS)

    @staticmethod
    def _cast_dates(df):
        date_cols = ["data_criacao_venda", "data_contrato", "data_emissao",
                     "data_cancelamento", "data_entrega", "data_primeiro_pagamento"]
        for col in date_cols:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce")
        return df

    @staticmethod
    def _cast_numerics(df):
        numeric_cols = ["valor_venda", "valor_total_venda", "area_privativa",
                        "area_comum", "area_terreno", "percentual_participacao",
                        "valor_total_condicao_pagamento", "numero_parcelas"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df

    @staticmethod
    def _deduplicate(df):
        subset = ["id_venda", "id_unidade_detalhe",
                  "id_tipo_condicao_pagamento", "id_corretor"]
        subset_existing = [c for c in subset if c in df.columns]
        before = len(df)
        df = df.drop_duplicates(subset=subset_existing)
        logger.debug("Deduplicação: %d → %d linhas.", before, len(df))
        return df

    @staticmethod
    def _add_derived_metrics(df):
        """Métricas calculadas equivalentes às medidas do painel Power BI."""
        if "valor_venda" in df.columns and "area_privativa" in df.columns:
            df["valor_por_m2"] = (
                df["valor_venda"] / df["area_privativa"].replace(0, pd.NA)
            )
        if "valor_venda" in df.columns:
            # flag para facilitar agrupamento de unidades únicas
            df["_is_main_unit"] = df.get("unidade_principal", True)
        return df

