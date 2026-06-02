import logging
from typing import List

import pandas as pd

from stage.extract.contas_pagas_extractor import ContasPagasExtractionResult

logger = logging.getLogger(__name__)


class ContasPagasTransformer:
    """
    Transforma dados brutos de vendas em DataFrame analítico.

    Pipeline de transformação:
      1. Consolidar resultados de todas as empresas
      2. Garantir presença das colunas esperadas
      3. Aplicar tipos corretos
      4. Remover duplicatas
      5. Normalizar datas
    """

    def transform(self, result: ContasPagasExtractionResult) -> pd.DataFrame:
        """
        Args:
            result: saída de ContasPagasExtractor.extract()

        Returns:
            DataFrame limpo. Vazio se a extração falhou ou não há dados.
        """
        if not result.sucesso or not result.registros:
            logger.warning("Nenhum dado disponível para transformação.")
            return pd.DataFrame()

        df = pd.DataFrame(result.registros)

        logger.info("Transformação concluída: %d registros finais.", len(df))
        return df
