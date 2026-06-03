"""
Extrator de Contas Recebidas da API Sienge.

Responsabilidade única: buscar dados brutos de contas recebidas (busca geral,
sem filtro por empresa) e retorná-los como lista de dicts, sem transformação.
"""
import logging
from dataclasses import dataclass
from typing import List

import requests

from config.settings import API_CONFIG
from drivers.api_requester import ApiRequester

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ContasRecebidasConfig:
    start_date: str = "2025-01-01"
    end_date: str = "2050-01-01"
    selection_type: str = "P"


# ---------------------------------------------------------------------------
# Resultado
# ---------------------------------------------------------------------------

@dataclass
class ContasRecebidasExtractionResult:
    """Resultado bruto de uma extração de contas recebidas."""
    registros: List[dict]
    sucesso: bool
    erro: str = ""


# ---------------------------------------------------------------------------
# Extractor
# ---------------------------------------------------------------------------

class ContasRecebidasExtractor:
    """
    Extrai contas recebidas via busca geral (sem filtro por empresa).

    Separado do ApiRequester para respeitar SRP:
      - ApiRequester              → sabe como fazer requisições HTTP
      - ContasRecebidasExtractor  → sabe qual endpoint chamar e como expandir
    """

    def __init__(
        self,
        requester: ApiRequester | None = None,
        config: ContasRecebidasConfig = ContasRecebidasConfig(),
    ):
        self._requester = requester or ApiRequester(API_CONFIG)
        self._config = config

    # ------------------------------------------------------------------
    # Interface pública
    # ------------------------------------------------------------------

    def extract(self) -> ContasRecebidasExtractionResult:
        """
        Faz uma única requisição geral e retorna o resultado bruto.

        Nunca lança exceção: erros são capturados e registrados
        no campo `erro` do resultado.
        """
        logger.info("Iniciando extração de contas recebidas (busca geral)...")
        result = self._extract()
        self._log_summary(result)
        return result

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------

    @staticmethod
    def _prefix_dict(data: dict, prefix: str) -> dict:
        return {f"{prefix}_{k}": v for k, v in data.items()}

    def _expand_recebimento(self, recebimento: dict) -> List[dict]:
        """
        Expande as sub-listas de um recebimento em registros planos.

        Sub-listas esperadas (mesma estrutura do /outcome):
          - authorizations  → uma linha por autorização
          - bankMovements   → uma linha por movimento bancário
          - installments    → uma linha por parcela

        Caso alguma sub-lista esteja vazia/ausente, usa [{}] para
        preservar o registro-pai sem perder dados.
        """
        authorizations = recebimento.get("authorizations") or [{}]
        bank_movements = recebimento.get("bankMovements")  or [{}]
        installments   = recebimento.get("installments")   or [{}]

        recebimento_base = {
            k: v
            for k, v in recebimento.items()
            if k not in ("authorizations", "bankMovements", "installments")
        }

        registros: List[dict] = []

        for authorization in authorizations:
            for bank_movement in bank_movements:
                for installment in installments:
                    registro = {
                        **self._prefix_dict(recebimento_base, "income"),
                        **self._prefix_dict(authorization,    "authorizations"),
                        **self._prefix_dict(bank_movement,    "bankMovements"),
                        **self._prefix_dict(installment,      "installments"),
                    }
                    registros.append(registro)

        return registros

    def _extract(self) -> ContasRecebidasExtractionResult:
        url = self._build_url()
        try:
            data = self._requester.get(url)

            registros_brutos: List[dict] = (
                data if isinstance(data, list) else data.get("data", [])
            )

            registros_expandidos: List[dict] = []
            for recebimento in registros_brutos:
                registros_expandidos.extend(self._expand_recebimento(recebimento))

            return ContasRecebidasExtractionResult(
                registros=registros_expandidos,
                sucesso=True,
            )

        except requests.HTTPError as exc:
            return ContasRecebidasExtractionResult(
                registros=[],
                sucesso=False,
                erro=f"HTTPError: {exc.response.status_code if exc.response else exc}",
            )
        except Exception as exc:  # noqa: BLE001
            return ContasRecebidasExtractionResult(
                registros=[],
                sucesso=False,
                erro=str(exc),
            )

    def _build_url(self) -> str:
        cfg = self._config
        return (
            f"{API_CONFIG.base_url}bulk-data/v1/income"
            f"?startDate={cfg.start_date}"
            f"&endDate={cfg.end_date}"
            f"&selectionType={cfg.selection_type}"
        )

    @staticmethod
    def _log_summary(result: ContasRecebidasExtractionResult) -> None:
        logger.info("=" * 50)
        logger.info("Extração de Contas Recebidas finalizada:")
        if result.sucesso:
            logger.info("  Total registros : %d", len(result.registros))
        else:
            logger.error("  Falha na extração: %s", result.erro)
        logger.info("=" * 50)