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
from transform.vendas_transformer import VendasTransformer

logger = logging.getLogger(__name__)


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
        """
        Executa o pipeline completo e retorna o DataFrame final.

        Returns:
            DataFrame com vendas consolidadas e transformadas.
            Retorna DataFrame vazio em caso de falha total.
        """
        logger.info("=== Pipeline de Vendas iniciado ===")

        # 1. Extração
        logger.info("[1/2] Iniciando extração...")
        results = self._extractor.extract()

        # 2. Transformação
        logger.info("[2/2] Iniciando transformação...")
        df = self._transformer.transform(results)

        if df.empty:
            logger.error("Pipeline finalizado sem dados.")
            return df

        logger.info("=== Pipeline de Vendas concluído: %d registros ===", len(df))
        return df


# ------------------------------------------------------------------
# Entrypoint direto (para testes rápidos / validação local)
# ------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    from utils.logging_config import setup_logging

    setup_logging()


    output_path = Path(r"C:\Users\kaua.rodrigo\PycharmProjects\etl_api_sienge\stage\transform\files\input")
    df = VendasDriver().run()

    if df.empty:
        logger.error("Nenhum dado para exportar.")
        sys.exit(1)

    df.to_csv(output_path / "validacao_vendas.csv", sep=";", index=False)
    logger.info("Arquivo salvo em: %s", output_path)
