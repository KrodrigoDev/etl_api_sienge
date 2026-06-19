"""
Extrator de Contas A Receber da API Sienge.

Responsabilidade única: buscar dados brutos de contas a receber (busca geral,
sem filtro por empresa) e retorná-los como lista de dicts, sem transformação.
"""
import logging
from dataclasses import dataclass
from typing import List

import requests

from config.settings import API_CONFIG, ContasAReceberConfig
from drivers.api_requester import ApiRequester

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Resultado
# ---------------------------------------------------------------------------

@dataclass
class ContasAReceberExtractionResult:
    """Resultado bruto de uma extração de contas a receber."""
    registros: List[dict]
    sucesso: bool
    erro: str = ""


# ---------------------------------------------------------------------------
# Extractor
# ---------------------------------------------------------------------------

class ContasAReceberExtractor:
    """
    Extrai contas a receber via busca geral (sem filtro por empresa).

    Separado do ApiRequester para respeitar SRP:
      - ApiRequester            → sabe como fazer requisições HTTP
      - ContasAReceberExtractor → sabe qual endpoint chamar e como expandir
    """

    def __init__(
            self,
            requester: ApiRequester | None = None,
            config: ContasAReceberConfig = ContasAReceberConfig(),
    ):
        self._requester = requester or ApiRequester(API_CONFIG)
        self._config = config

    # ------------------------------------------------------------------
    # Interface pública
    # ------------------------------------------------------------------

    def extract(self) -> ContasAReceberExtractionResult:
        """
        Faz uma única requisição geral e retorna o resultado bruto.

        Nunca lança exceção: erros são capturados e registrados
        no campo `erro` do resultado.
        """
        logger.info("Iniciando extração de contas a receber (busca geral)...")
        result = self._extract()
        self._log_summary(result)
        return result

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------

    @staticmethod
    def _prefix_dict(data: dict, prefix: str) -> dict:
        return {f"{prefix}_{k}": v for k, v in data.items()}

    def _expand_parcela(self, parcela: dict) -> List[dict]:
        """
        Expande as sub-listas de uma parcela em registros planos.

        Sub-listas:
          - receipts             → uma linha por recebimento (baixa)
          - bankMovements        → uma linha por movimento bancário
          - financialCategories  → uma linha por categoria financeira
          - receiptsCategories   → uma linha por categoria de recebimento

        Caso alguma sub-lista esteja vazia/ausente, usa [{}] para
        preservar o registro-pai sem perder dados.

        Nota: bankMovements e financialCategories ficam aninhados dentro
        de cada receipt — a expansão é feita em cadeia.
        """
        receipts = parcela.get("receipts") or [{}]
        receipts_categories = parcela.get("receiptsCategories") or [{}]

        parcela_base = {
            k: v
            for k, v in parcela.items()
            if k not in ("receipts", "receiptsCategories")
        }

        registros: List[dict] = []

        for receipt in receipts:
            bank_movements = receipt.get("bankMovements") or [{}]

            receipt_base = {
                k: v
                for k, v in (receipt if isinstance(receipt, dict) else {}).items()
                if k != "bankMovements"
            }

            for bank_movement in bank_movements:
                financial_categories = (
                    bank_movement.get("financialCategories") or [{}]
                    if isinstance(bank_movement, dict)
                    else [{}]
                )

                bm_base = {
                    k: v
                    for k, v in (bank_movement if isinstance(bank_movement, dict) else {}).items()
                    if k != "financialCategories"
                }

                for fc in financial_categories:
                    for rc in receipts_categories:
                        registro = {
                            **self._prefix_dict(parcela_base, "receivable"),
                            **self._prefix_dict(receipt_base, "receipts"),
                            **self._prefix_dict(bm_base, "bankMovements"),
                            **self._prefix_dict(fc if isinstance(fc, dict) else {}, "fc"),
                            **self._prefix_dict(rc if isinstance(rc, dict) else {}, "receiptsCategories"),
                        }
                        registros.append(registro)

        return registros

    def _extract(self) -> ContasAReceberExtractionResult:
        url = self._build_url()
        try:
            data = self._requester.get(url)

            registros_brutos: List[dict] = (
                data if isinstance(data, list) else data.get("data", [])
            )

            registros_expandidos: List[dict] = []
            for parcela in registros_brutos:
                registros_expandidos.extend(self._expand_parcela(parcela))

            return ContasAReceberExtractionResult(
                registros=registros_expandidos,
                sucesso=True,
            )

        except requests.HTTPError as exc:
            return ContasAReceberExtractionResult(
                registros=[],
                sucesso=False,
                erro=f"HTTPError: {exc.response.status_code if exc.response else exc}",
            )
        except Exception as exc:  # noqa: BLE001
            return ContasAReceberExtractionResult(
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
    def _log_summary(result: ContasAReceberExtractionResult) -> None:
        logger.info("=" * 50)
        logger.info("Extração de Contas A Receber finalizada:")
        if result.sucesso:
            logger.info("  Total registros : %d", len(result.registros))
        else:
            logger.error("  Falha na extração: %s", result.erro)
        logger.info("=" * 50)
