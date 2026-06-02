"""
Extrator de Contas Pagas da API Sienge.

Responsabilidade única: buscar dados brutos de contas pagas (busca geral,
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
class ContasPagasConfig:
    start_date: str = "2024-01-01"
    end_date: str = "2050-12-31"
    selection_type: str = "P"
    correction_indexer_id: int = 0
    correction_date: str = "2025-01-01"
    with_authorizations: bool = False
    with_bank_movements: bool = True


# ---------------------------------------------------------------------------
# Resultado
# ---------------------------------------------------------------------------

@dataclass
class ContasPagasExtractionResult:
    """Resultado bruto de uma extração de contas pagas."""
    registros: List[dict]
    sucesso: bool
    erro: str = ""


# ---------------------------------------------------------------------------
# Extractor
# ---------------------------------------------------------------------------

class ContasPagasExtractor:
    """
    Extrai contas pagas via busca geral (sem filtro por empresa).

    Separado do ApiRequester para respeitar SRP:
      - ApiRequester          → sabe como fazer requisições HTTP
      - ContasPagasExtractor  → sabe qual endpoint chamar e como expandir
    """

    def __init__(
        self,
        requester: ApiRequester | None = None,
        config: ContasPagasConfig = ContasPagasConfig(),
    ):
        self._requester = requester or ApiRequester(API_CONFIG)
        self._config = config

    # ------------------------------------------------------------------
    # Interface pública
    # ------------------------------------------------------------------

    def extract(self) -> ContasPagasExtractionResult:
        """
        Faz uma única requisição geral e retorna o resultado bruto.

        Nunca lança exceção: erros são capturados e registrados
        no campo `erro` do resultado.
        """


        logger.info("Iniciando extração de contas pagas (busca geral)...")
        result = self._extract()
        self._log_summary(result)
        return result

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------

    @staticmethod
    def _prefix_dict(data: dict, prefix: str) -> dict:
        return {f"{prefix}_{k}": v for k, v in data.items()}

    def _expand_conta(self, conta: dict) -> List[dict]:
        """
        Expande as sub-listas de uma conta paga em registros planos.

        Sub-listas:
          - authorizations  → uma linha por autorização
          - bankMovements   → uma linha por movimento bancário
          - installments    → uma linha por parcela

        Caso alguma sub-lista esteja vazia/ausente, usa [{}] para
        preservar o registro-pai sem perder dados.
        """
        authorizations = conta.get("authorizations") or [{}]
        bank_movements = conta.get("bankMovements")  or [{}]
        installments   = conta.get("installments")   or [{}]

        conta_base = {
            k: v
            for k, v in conta.items()
            if k not in ("authorizations", "bankMovements", "installments")
        }

        registros: List[dict] = []

        for authorization in authorizations:
            for bank_movement in bank_movements:
                for installment in installments:
                    registro = {
                        **self._prefix_dict(conta_base,    "outcome"),
                        **self._prefix_dict(authorization, "authorizations"),
                        **self._prefix_dict(bank_movement, "bankMovements"),
                        **self._prefix_dict(installment,   "installments"),
                    }
                    registros.append(registro)

        return registros

    def _extract(self) -> ContasPagasExtractionResult:
        url = self._build_url()
        try:
            data = self._requester.get(url)

            registros_brutos: List[dict] = (
                data if isinstance(data, list) else data.get("data", [])
            )

            registros_expandidos: List[dict] = []
            for conta in registros_brutos:
                registros_expandidos.extend(self._expand_conta(conta))

            return ContasPagasExtractionResult(
                registros=registros_expandidos,
                sucesso=True,
            )

        except requests.HTTPError as exc:
            return ContasPagasExtractionResult(
                registros=[],
                sucesso=False,
                erro=f"HTTPError: {exc.response.status_code if exc.response else exc}",
            )
        except Exception as exc:  # noqa: BLE001
            return ContasPagasExtractionResult(
                registros=[],
                sucesso=False,
                erro=str(exc),
            )

    def _build_url(self) -> str:
        cfg = self._config
        return (
            f"{API_CONFIG.base_url}bulk-data/v1/outcome"
            f"?startDate={cfg.start_date}"
            f"&endDate={cfg.end_date}"
            f"&selectionType={cfg.selection_type}"
            f"&correctionIndexerId={cfg.correction_indexer_id}"
            f"&correctionDate={cfg.correction_date}"
            f"&companyId="
            f"&withAuthorizations={str(cfg.with_authorizations).lower()}"
            f"&withBankMovements={str(cfg.with_bank_movements).lower()}"
        )

    @staticmethod
    def _log_summary(result: ContasPagasExtractionResult) -> None:
        logger.info("=" * 50)
        logger.info("Extração de Contas Pagas finalizada:")
        if result.sucesso:
            logger.info("  Total registros : %d", len(result.registros))
        else:
            logger.error("  Falha na extração: %s", result.erro)
        logger.info("=" * 50)