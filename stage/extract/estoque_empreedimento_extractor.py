"""
Extrator de Vendas da API Sienge.

Responsabilidade única: buscar dados brutos de vendas por empresa
e retorná-los como lista de dicts, sem transformação alguma.
"""
import logging
from dataclasses import dataclass
from typing import List

import requests

from config.settings import EstoqueEmpreedimentoConfig, API_CONFIG
from drivers.api_requester import ApiRequester

logger = logging.getLogger(__name__)


@dataclass
class EstoqueExtractionResult:
    """Resultado bruto de uma extração de estoque."""
    empresa_id: int
    registros: List[dict]
    sucesso: bool
    erro: str = ""


class EstoqueEmpreedimentosExtractor:
    """
    Extrai estoque de empreedimentos de todas as empresas configuradas.

    Separado do ApiRequester para respeitar SRP:
      - ApiRequester  → sabe como fazer requisições HTTP
      - VendasExtractor → sabe quais endpoints chamar e como iterar empresas
    """

    def __init__(
            self,
            requester: ApiRequester | None = None,
            config: EstoqueEmpreedimentoConfig = EstoqueEmpreedimentoConfig(),
    ):
        self._requester = requester or ApiRequester(API_CONFIG)
        self._config = config

    # ------------------------------------------------------------------
    # Interface pública
    # ------------------------------------------------------------------

    def extract(self) -> List[EstoqueExtractionResult]:
        """
        Itera todas as empresas e retorna lista de resultados brutos.

        Nunca lança exceção: erros por empresa são capturados e
        registrados no campo `erro` do resultado.
        """
        results: List[EstoqueExtractionResult] = []

        total = len(self._config.empresas)
        for idx, empresa_id in enumerate(self._config.empresas, start=1):
            logger.info("[%d/%d] Extraindo empresa %d...", idx, total, empresa_id)
            result = self._extract_empresa(empresa_id)
            results.append(result)

            if result.sucesso:
                logger.info(
                    "  ✓ Empresa %d → %d registros",
                    empresa_id, len(result.registros),
                )
            else:
                logger.error(
                    "  ✗ Empresa %d → %s",
                    empresa_id, result.erro,
                )

            # Rate limiting: pausa entre empresas (20 req/min = 3s/req)
            # Exceto na última iteração
            if idx < total:
                self._requester.rate_limit_sleep()

        self._log_summary(results)
        return results

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------

    @staticmethod
    def _prefix_dict(data: dict, prefix: str) -> dict:
        return {
            f"{prefix}_{k}": v
            for k, v in data.items()
        }


    def _extract_empresa(self, empresa_id: int) -> EstoqueExtractionResult:
        url = self._build_url(empresa_id)
        try:
            data = self._requester.get(url)

            registros = data if isinstance(data, list) else data.get("results", [])


            return EstoqueExtractionResult(
                empresa_id=empresa_id,
                registros=registros,
                sucesso=True,
            )
        except requests.HTTPError as exc:
            return EstoqueExtractionResult(
                empresa_id=empresa_id,
                registros=[],
                sucesso=False,
                erro=f"HTTPError: {exc.response.status_code if exc.response else exc}",
            )
        except Exception as exc:  # noqa: BLE001
            return EstoqueExtractionResult(
                empresa_id=empresa_id,
                registros=[],
                sucesso=False,
                erro=str(exc),
            )

    def _build_url(self, empresa_id: int) -> str:
        cfg = self._config
        return (
            f"{API_CONFIG.base_url}v1/units"
            f"?limit={cfg.limit}"
            f"&offset={cfg.offset}"
            f"&enterpriseId={empresa_id}"
        )

    @staticmethod
    def _log_summary(results: List[EstoqueExtractionResult]) -> None:
        total_ok = sum(1 for r in results if r.sucesso)
        total_registros = sum(len(r.registros) for r in results)
        falhas = [r.empresa_id for r in results if not r.sucesso]

        logger.info("=" * 50)
        logger.info("Extração finalizada:")
        logger.info("  Empresas OK     : %d / %d", total_ok, len(results))
        logger.info("  Total registros : %d", total_registros)
        if falhas:
            logger.warning("  Empresas com falha: %s", falhas)
        logger.info("=" * 50)
