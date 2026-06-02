"""
Driver de Main

Orquestra o fluxo completo:
  Extração → Transformação → Entrega

Os drivers NÃO contêm lógica de negócio: apenas conectam as peças.
"""
import logging
import sys
from pathlib import Path

import pandas as pd

from stage.extract.vendas_extractor import VendasExtractor
from stage.extract.contas_pagas_extractor import ContasPagasExtractor
from transform.vendas_transformer import VendasTransformer
from transform.contas_pagas_transformer import ContasPagasTransformer

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# VendasDriver
# ------------------------------------------------------------------

class VendasDriver:
    """
    Driver para o pipeline de Vendas.

    Uso típico:
        df = VendasDriver().run()

    Para customizar componentes (ex: testes):
        driver = VendasDriver(extractor=mock_extractor)
        df = driver.run()
    """

    def __init__(
            self,
            extractor: VendasExtractor | None = None,
            transformer: VendasTransformer | None = None,
    ):
        self._extractor = extractor or VendasExtractor()
        self._transformer = transformer or VendasTransformer()

    def run(self) -> pd.DataFrame:
        logger.info("=== Pipeline de Vendas iniciado ===")

        logger.info("[1/2] Iniciando extração...")
        results = self._extractor.extract()  # List[VendasExtractionResult]

        logger.info("[2/2] Iniciando transformação...")
        df = self._transformer.transform(results)

        if df.empty:
            logger.error("Pipeline finalizado sem dados.")
            return df

        logger.info("=== Pipeline de Vendas concluído: %d registros ===", len(df))
        return df


# ------------------------------------------------------------------
# ContasPagasDriver
# ------------------------------------------------------------------

class ContasPagasDriver:
    """
    Driver para o pipeline de Contas Pagas.

    Uso típico:
        df = ContasPagasDriver().run()

    Para customizar componentes (ex: testes):
        driver = ContasPagasDriver(extractor=mock_extractor)
        df = driver.run()
    """

    def __init__(
            self,
            extractor: ContasPagasExtractor | None = None,
            transformer: ContasPagasTransformer | None = None,
    ):
        self._extractor = extractor or ContasPagasExtractor()
        self._transformer = transformer or ContasPagasTransformer()

    def run(self) -> pd.DataFrame:
        logger.info("=== Pipeline de Contas Pagas iniciado ===")

        logger.info("[1/2] Iniciando extração...")
        result = self._extractor.extract()  # ContasPagasExtractionResult (único)

        logger.info("[2/2] Iniciando transformação...")
        df = self._transformer.transform(result)

        if df.empty:
            logger.error("Pipeline finalizado sem dados.")
            return df

        logger.info("=== Pipeline de Contas Pagas concluído: %d registros ===", len(df))
        return df


# ------------------------------------------------------------------
# Entrypoint direto (para testes rápidos / validação local)
# ------------------------------------------------------------------
if __name__ == "__main__":
    from utils.logging_config import setup_logging

    setup_logging()

    output_path = Path(r"C:\Users\kaua.rodrigo\PycharmProjects\etl_api_sienge\stage\transform\files\input")

    # --- Vendas ---
    # df_vendas = VendasDriver().run()
    # if df_vendas.empty:
    #     logger.error("Nenhum dado de vendas para exportar.")
    # else:
    #     df_vendas.to_csv(output_path / "validacao_vendas.csv", sep=";", index=False)
    #     logger.info("Vendas salvas em: %s", output_path / "validacao_vendas.csv")

    # --- Contas Pagas ---
    df_contas = ContasPagasDriver().run()
    if df_contas.empty:
        logger.error("Nenhum dado de contas pagas para exportar.")
    else:
        df_contas.to_csv(output_path / "validacao_contas_pagas.csv", sep=";", index=False)
        logger.info("Contas pagas salvas em: %s", output_path / "validacao_contas_pagas.csv")

    # if df_vendas.empty and df_contas.empty:
    #     sys.exit(1)
