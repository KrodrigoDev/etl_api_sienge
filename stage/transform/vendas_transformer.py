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
    # SALE
    # -------------------------
    "sale_id": "id_venda",
    "sale_enterpriseId": "id_empresa_venda",
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
    "paymentConditions_conditionTypeId": "id_tipo_condicao_pagamento",
    "paymentConditions_conditionTypeName": "nome_tipo_condicao_pagamento",
    "paymentConditions_bearerId": "id_portador",
    "paymentConditions_bearerName": "nome_portador",
    "paymentConditions_installmentsNumber": "numero_parcelas",
    "paymentConditions_totalValue": "valor_total_condicao_pagamento",
    "paymentConditions_firstPayment": "data_primeiro_pagamento",

    # -------------------------
    # BROKERS
    # -------------------------
    "brokers_id": "id_corretor",
    "brokers_name": "nome_corretor",
    "brokers_main": "corretor_principal",
}


class VendasTransformer:
    """
    Transforma dados brutos de vendas em DataFrame analítico.

    Pipeline de transformação:
      1. Consolidar resultados de todas as empresas
      2. Garantir presença das colunas esperadas
      3. Aplicar tipos corretos
      4. Remover duplicatas
      5. Normalizar datas
    """

    def transform(self, results: List[VendasExtractionResult]) -> pd.DataFrame:
        """
        Args:
            results: saída de VendasExtractor.extract()

        Returns:
            DataFrame limpo e tipado. Vazio se nenhum dado foi extraído.
        """
        sucessos = [r for r in results if r.sucesso and r.registros]

        if not sucessos:
            logger.warning("Nenhum dado disponível para transformação.")
            return pd.DataFrame()

        df = self._consolidate(sucessos)


        df = df.rename(columns=RENAME_COLUMNS_VENDAS)

        logger.info("Transformação concluída: %d registros finais.", len(df))
        return df

    # ------------------------------------------------------------------
    # Etapas do pipeline
    # ------------------------------------------------------------------


    # verificar o motivo de não estar entrando aqui
    @staticmethod
    def _consolidate(results: List[VendasExtractionResult]) -> pd.DataFrame:
        frames = []
        for result in results:
            frame = pd.DataFrame(result.registros)
            # Garante que enterpriseId veio da iteração (pode não vir na payload)
            frame["enterpriseId"] = result.empresa_id
            frames.append(frame)
        df = pd.concat(frames, ignore_index=True)
        logger.debug("Consolidado: %d linhas de %d empresas.", len(df), len(results))
        return df

