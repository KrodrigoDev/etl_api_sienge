"""
Driver de Main

Orquestra o fluxo completo:
  Extração → Transformação → Entrega

Os drivers NÃO contêm lógica de negócio: apenas conectam as peças.
"""
import logging
from pathlib import Path

import pandas as pd

from stage.extract.vendas_extractor import VendasExtractor
from stage.extract.contas_pagas_extractor import ContasPagasExtractor
from stage.transform.vendas_transformer import VendasTransformer
from stage.transform.contas_pagas_transformer import ContasPagasTransformer
from stage.transform.contas_pagas_transformer_2 import executar

logger = logging.getLogger(__name__)


output_path = Path(r"C:\Users\kaua.rodrigo\PycharmProjects\etl_api_sienge\stage\transform\files\input")


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

    def run(self):
        logger.info("=== Pipeline de Contas Pagas iniciado ===")

        logger.info("[1/3] Iniciando extração...")
        result = self._extractor.extract()  # ContasPagasExtractionResult (único)

        logger.info("[2/3] Iniciando primeira transformação...")
        df = self._transformer.transform(result)

        if df.empty:
            logger.error("Pipeline finalizado sem dados.")
        else:
            df.to_csv(output_path / "contas_pagas.csv", sep=";", index=False)
            logger.info("Contas pagas salvas em: %s", output_path / "contas_pagas.csv")

        logger.info("[3/3] Iniciando última transformação...")
        executar()

        logger.info("=== Pipeline de Contas Pagas concluído: %d registros ===", len(df))


# ------------------------------------------------------------------
# Entrypoint direto (para testes rápidos / validação local)
# ------------------------------------------------------------------
if __name__ == "__main__":
    from utils.logging_config import setup_logging

    setup_logging()

    # --- Contas Pagas ---
    ContasPagasDriver().run()
