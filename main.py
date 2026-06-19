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
from stage.transform.vendas_transformer import VendasTransformer

from stage.extract.contas_pagas_extractor import ContasPagasExtractor
from stage.transform.contas_pagas_transformer import ContasPagasTransformer
from stage.transform.contas_pagas_transformer_2 import executar as executar_contas_pagas

from stage.extract.contas_recebidas_extractor import ContasRecebidasExtractor
from stage.transform.contas_recebidas_transformer import ContasRecebidasTransformer
from stage.transform.contas_recebidas_transformer_2 import executar as executar_recebidas

from stage.extract.titulos_contas_pagas_extractor import TitulosExtractor, TitulosExtractionResult
from stage.extract.credores_extractor import CredoresExtractor, CredoresExtractionResult

from stage.extract.contas_a_receber_extractor import ContasAReceberExtractor
from stage.transform.contas_a_receber_transformer import ContasAReceberTransformer
from stage.transform.contas_a_receber_transformer_2 import executar as executar_a_receber

logger = logging.getLogger(__name__)

pasta_origem = Path(__file__).resolve().parents[0]
INPUT_DIR = pasta_origem / "stage" / "transform" / "files" / "input"


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
            df.to_csv((INPUT_DIR / "contas_pagas.csv"), sep=";", index=False)
            logger.info("Contas pagas salvas em: %s", (INPUT_DIR / "contas_pagas.csv"))

        logger.info("[3/3] Iniciando última transformação...")
        executar_contas_pagas()

        logger.info("=== Pipeline de Contas Pagas concluído: %d registros ===", len(df))


class ContasRecebidasDriver:
    """
        Driver para o pipeline de Contas recebidas.

        Uso típico:
            df = ContasRecebidasDriver().run()

        Para customizar componentes (ex: testes):
            driver = ContasPagasDriver(extractor=mock_extractor)
            df = driver.run()
        """

    def __init__(
            self,
            extractor: ContasRecebidasExtractor | None = None,
            transformer: ContasRecebidasTransformer | None = None,
    ):
        self._extractor = extractor or ContasRecebidasExtractor()
        self._transformer = transformer or ContasRecebidasTransformer()

    def run(self):
        logger.info("=== Pipeline de Contas Recebidas iniciado ===")

        logger.info("[1/2] Iniciando extração...")
        result = self._extractor.extract()

        logger.info("[2/3] Iniciando primeira transformação...")
        df = self._transformer.transform(result)

        if df.empty:
            logger.error("Pipeline finalizado sem dados.")
        else:
            df.to_csv((INPUT_DIR / "contas_recebidas.csv"), sep=";", index=False)
            logger.info("Contas pagas salvas em: %s", (INPUT_DIR / "contas_recebidas_tratada.csv"))

        logger.info("[3/3] Iniciando última transformação...")
        executar_recebidas()

        logger.info("=== Pipeline de Contas Recebidas concluído: %d registros ===", len(df))


class ContasAReceberDriver:
    """
        Driver para o pipeline de Contas a recebber.

        Uso típico:
            df = ContasRecebidasDriver().run()

        Para customizar componentes (ex: testes):
            driver = ContasPagasDriver(extractor=mock_extractor)
            df = driver.run()
        """

    def __init__(
            self,
            extractor: ContasAReceberExtractor | None = None,
            transformer: ContasAReceberTransformer | None = None,
    ):
        self._extractor = extractor or ContasAReceberExtractor()
        self._transformer = transformer or ContasAReceberTransformer()

    def run(self):
        logger.info("=== Pipeline de Contas a Receber iniciado ===")

        logger.info("[1/2] Iniciando extração...")
        result = self._extractor.extract()

        logger.info("[2/3] Iniciando primeira transformação...")
        df = self._transformer.transform(result)

        if df.empty:
            logger.error("Pipeline finalizado sem dados.")
        else:
            df.to_csv((INPUT_DIR / "contas_a_receber.csv"), sep=";", index=False)
            logger.info("Contas a receber salvas em: %s", (INPUT_DIR / "contas_a_receber.csv"))

        logger.info("[3/3] Iniciando última transformação...")
        executar_a_receber()

        logger.info("=== Pipeline de Contas a receber concluído: %d registros ===", len(df))


class CredoresDriver:
    """
    Driver para o pipeline de Credores.

    Resultado salvo em credores.csv — usado como tabela de dimensão
    para enriquecer títulos via join em creditorId / cod_credor.

    Uso típico:
        df = CredoresDriver().run()
    """

    def __init__(
            self,
            extractor: CredoresExtractor | None = None,
    ):
        self._extractor = extractor or CredoresExtractor()

    def run(self) -> pd.DataFrame:
        logger.info("=== Pipeline de Credores iniciado ===")

        logger.info("[1/2] Iniciando extração...")
        result = self._extractor.extract()

        if not result.sucesso:
            logger.error("Extração falhou: %s", result.erro)
            return pd.DataFrame()

        logger.info("[2/2] Convertendo para DataFrame...")
        df = pd.DataFrame(result.registros)

        if df.empty:
            logger.error("Pipeline finalizado sem dados.")
            return df

        df.to_csv((INPUT_DIR / "credores.csv"), sep=";", index=False)
        logger.info("Credores salvos em: %s", (INPUT_DIR / "credores.csv"))

        logger.info("=== Pipeline de Credores concluído: %d registros ===", len(df))
        return df


class TitulosDriver:
    """
    Driver para o pipeline de Títulos do Contas a Pagar.

    Uso típico:
        df = TitulosDriver().run()

    Para customizar componentes (ex: testes):
        driver = TitulosDriver(extractor=mock_extractor)
        df = driver.run()
    """

    def __init__(
            self,
            extractor: TitulosExtractor | None = None,
    ):
        self._extractor = extractor or TitulosExtractor()

    def run(self) -> pd.DataFrame:
        logger.info("=== Pipeline de Títulos iniciado ===")

        logger.info("[1/2] Iniciando extração...")
        result = self._extractor.extract()

        if not result.sucesso:
            logger.error("Extração falhou: %s", result.erro)
            return pd.DataFrame()

        logger.info("[2/2] Convertendo para DataFrame...")
        df = pd.DataFrame(result.registros)

        if df.empty:
            logger.error("Pipeline finalizado sem dados.")
            return df

        df.to_csv((INPUT_DIR / "titulos.csv"), sep=";", index=False)
        logger.info("Títulos salvos em: %s", (INPUT_DIR / "titulos.csv"))

        logger.info("=== Pipeline de Títulos concluído: %d registros ===", len(df))
        return df


if __name__ == "__main__":
    from utils.logging_config import setup_logging

    setup_logging()

    # ContasPagasDriver().run()
    #
    # ContasRecebidasDriver().run()
    # ContasAReceberDriver().run()

    TitulosDriver().run()
    CredoresDriver().run()
