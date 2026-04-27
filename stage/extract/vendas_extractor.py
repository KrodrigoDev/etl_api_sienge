"""
Extrator de Vendas da API Sienge.

Responsabilidade única: buscar dados brutos de vendas por empresa
e retorná-los como lista de dicts, sem transformação alguma.
"""
import logging
from dataclasses import dataclass
from typing import List

import requests

from config.settings import VendasConfig, API_CONFIG
from drivers.api_requester import ApiRequester

logger = logging.getLogger(__name__)


@dataclass
class VendasExtractionResult:
    """Resultado bruto de uma extração de vendas."""
    empresa_id: int
    registros: List[dict]
    sucesso: bool
    erro: str = ""


class VendasExtractor:
    """
    Extrai vendas de todas as empresas configuradas.

    Separado do ApiRequester para respeitar SRP:
      - ApiRequester  → sabe como fazer requisições HTTP
      - VendasExtractor → sabe quais endpoints chamar e como iterar empresas
    """

    def __init__(
        self,
        requester: ApiRequester | None = None,
        config: VendasConfig = VendasConfig(),
    ):
        self._requester = requester or ApiRequester(API_CONFIG)
        self._config = config

    # ------------------------------------------------------------------
    # Interface pública
    # ------------------------------------------------------------------

    def extract(self) -> List[VendasExtractionResult]:
        """
        Itera todas as empresas e retorna lista de resultados brutos.

        Nunca lança exceção: erros por empresa são capturados e
        registrados no campo `erro` do resultado.
        """
        results: List[VendasExtractionResult] = []

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

    def _expand_venda(
            self,
            venda: dict,
            empresa_id: int,
    ) -> List[dict]:

        units = venda.get("units", []) or [{}]
        payments = venda.get("paymentConditions", []) or [{}]
        brokers = venda.get("brokers", []) or [{}]

        # Remove listas internas da venda
        venda_base = {
            k: v
            for k, v in venda.items()
            if k not in (
                "units",
                "paymentConditions",
                "brokers",
            )
        }

        registros: List[dict] = []

        for unit in units:
            for payment in payments:
                for broker in brokers:
                    registro = {
                        "empresa_id": empresa_id,

                        **self._prefix_dict(venda_base, "sale"),
                        **self._prefix_dict(unit, "units"),
                        **self._prefix_dict(payment, "paymentConditions"),
                        **self._prefix_dict(broker, "brokers"),
                    }

                    registros.append(registro)

        return registros


    def _extract_empresa(self, empresa_id: int) -> VendasExtractionResult:
        url = self._build_url(empresa_id)
        try:
            data = self._requester.get(url)

            registros = data if isinstance(data, list) else data.get("data", [])


            registros_expandidos = []

            for registro in registros:
                registros_expandidos.extend(
                    self._expand_venda(registro, empresa_id)
                )


            return VendasExtractionResult(
                empresa_id=empresa_id,
                registros=registros_expandidos,
                sucesso=True,
            )
        except requests.HTTPError as exc:
            return VendasExtractionResult(
                empresa_id=empresa_id,
                registros=[],
                sucesso=False,
                erro=f"HTTPError: {exc.response.status_code if exc.response else exc}",
            )
        except Exception as exc:  # noqa: BLE001
            return VendasExtractionResult(
                empresa_id=empresa_id,
                registros=[],
                sucesso=False,
                erro=str(exc),
            )

    def _build_url(self, empresa_id: int) -> str:
        cfg = self._config
        return (
            f"{API_CONFIG.base_url}bulk-data/v1/sales"
            f"?enterpriseId={empresa_id}"
            f"&createdAfter={cfg.periodo[0]}"
            f"&createdBefore={cfg.periodo[1]}"
            f"&situation={cfg.situacao}"
        )

    @staticmethod
    def _log_summary(results: List[VendasExtractionResult]) -> None:
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
