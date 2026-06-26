"""
Transformação de dados brutos de Estoque de Empreedimentos

Responsabilidade única: receber lista de VendasExtractionResult
e retornar um DataFrame limpo e tipado, pronto para carga.
"""
import logging
from typing import List

import pandas as pd

from stage.extract.estoque_empreedimento_extractor import EstoqueExtractionResult

logger = logging.getLogger(__name__)

RENAME_COLUMNS_ESTOQUE = {

    # -------------------------
    # CONTEXTO
    # -------------------------
    "empresa_id": "id_empresa_contexto",
    "enterpriseId": "cod_centro_de_custo",

    # -------------------------
    # IDENTIFICAÇÃO DA UNIDADE
    # -------------------------
    "id": "id_unidade",
    "name": "nome_unidade",
    "propertyType": "tipo_imovel",
    "commercialStock": "estoque_comercial",
    "contractId": "id_contrato",
    "contractNumber": "numero_contrato",
    "indexerId": "id_indexador",

    # -------------------------
    # OBSERVAÇÕES
    # -------------------------
    "note": "observacao_unidade",

    # -------------------------
    # LOCALIZAÇÃO
    # -------------------------
    "latitude": "latitude",
    "longitude": "longitude",

    # -------------------------
    # REGISTROS
    # -------------------------
    "legalRegistrationNumber": "matricula",
    "realEstateRegistration": "inscricao_imobiliaria",
    "cibCode": "codigo_cib",
    "incraCode": "codigo_incra",

    # -------------------------
    # DATAS
    # -------------------------
    "deliveryDate": "data_entrega",
    "scheduledDeliveryDate": "data_programada_entrega",

    # -------------------------
    # ÁREAS
    # -------------------------
    "privateArea": "area_privativa",
    "commonArea": "area_comum",
    "terrainArea": "area_terreno",
    "nonProportionalCommonArea": "area_comum_nao_proporcional",
    "usableArea": "area_util",

    # -------------------------
    # FRAÇÕES
    # -------------------------
    "idealFraction": "fracao_ideal",
    "idealFractionSquareMeter": "fracao_ideal_m2",
    "generalSaleValueFraction": "fracao_vgv",

    # -------------------------
    # VALORES
    # -------------------------
    "terrainValue": "valor_terreno",
    "iptuValue": "valor_iptu",
    "indexedQuantity": "quantidade_indexada",
    "prizedCompliance": "adimplencia_premiada",

    # -------------------------
    # CLASSIFICAÇÕES
    # -------------------------
    "floor": "pavimento",
    "locationType": "tipo_localizacao",
    "frameworkType": "tipo_enquadramento",
}


class EstoqueEmpreedimentoTransformer:

    def transform(self, results: List[EstoqueExtractionResult]) -> pd.DataFrame:
        sucessos = [r for r in results if r.sucesso and r.registros]
        if not sucessos:
            logger.warning("Nenhum dado disponível para transformação.")
            return pd.DataFrame()

        df = self._consolidate(sucessos)
        df = self._rename_columns(df)

        mapping_estoque_comercial = {
            "D": "Disponível",
            "V": "Vendida",
            "L": "Locada",
            "C": "Reservada",
            "R": "Reserva Técnica",
            "E": "Permuta",
            "M": "Mútuo",
            "P": "Proposta",
            "T": "Transferido",
            "G": "Vendido/Terceiros",
            "O": "Vendida em Pré-Contrato"
        }

        df["estoque_comercial_descricao"] = (
            df["estoque_comercial"]
            .map(mapping_estoque_comercial)
            .fillna("Não Informado")
        )

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
        return df.rename(columns=RENAME_COLUMNS_ESTOQUE)





