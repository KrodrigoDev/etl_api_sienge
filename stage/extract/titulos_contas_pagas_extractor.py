"""
Extrator de Títulos do Contas a Pagar da API Sienge.

Responsabilidade única: buscar dados paginados de títulos via endpoint
/v1/bills e retorná-los como lista de dicts, sem transformação pesada.

Colunas do relatório manual → campo da API:
  titulo            → id
  credor            → creditorId
  documento         → documentIdentificationId + documentNumber
  origem            → originId
  emissao_nf        → issueDate
  cadastro          → registeredDate
  qtd               → installmentsNumber
  valor_bruto       → totalInvoiceAmount
  descontos         → discount
  valor_liquido     → totalInvoiceAmount - discount

Colunas extras para auditoria (pt-br):
  devedor_id        → debtorId
  status            → status            (S=Completo / N=Incompleto / I=Em inclusão)
  tipo_documento    → documentIdentificationId  (limpo, para filtros)
  numero_documento  → documentNumber            (limpo, para filtros)
  observacao        → notes
  chave_nfe         → accessKeyNumber   (44 dígitos NF-e)
  cadastrado_por_id → registeredUserId
  cadastrado_por    → registeredBy
  cadastrado_em     → registeredDate
  alterado_por_id   → changedUserId
  alterado_por      → changedBy
  alterado_em       → changedDate
"""
import logging
import time
from dataclasses import dataclass
from typing import List

import requests

from config.settings import API_CONFIG, TitulosContasPagasConfig
from drivers.api_requester import ApiRequester

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Resultado
# ---------------------------------------------------------------------------

@dataclass
class TitulosExtractionResult:
    """Resultado bruto de uma extração de títulos."""
    registros: List[dict]
    sucesso: bool
    erro: str = ""


# ---------------------------------------------------------------------------
# Extractor
# ---------------------------------------------------------------------------

class TitulosExtractor:
    """
    Extrai títulos do contas a pagar via endpoint paginado /v1/bills.

    Itera automaticamente por todas as páginas usando limit/offset até
    esgotar os registros indicados por resultSetMetadata.count.

    Separado do ApiRequester para respeitar SRP:
      - ApiRequester     → sabe como fazer requisições HTTP
      - TitulosExtractor → sabe qual endpoint chamar e como paginar
    """

    def __init__(
        self,
        requester: ApiRequester | None = None,
        config: TitulosContasPagasConfig = TitulosContasPagasConfig(),
    ):
        self._requester = requester or ApiRequester(API_CONFIG)
        self._config = config

    # ------------------------------------------------------------------
    # Interface pública
    # ------------------------------------------------------------------

    def extract(self) -> TitulosExtractionResult:
        """
        Percorre todas as páginas da API e retorna o resultado consolidado.

        Nunca lança exceção: erros são capturados e registrados
        no campo `erro` do resultado.
        """
        logger.info("Iniciando extração de títulos (contas a pagar)...")
        result = self._extract_all_pages()
        self._log_summary(result)
        return result

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------

    def _extract_all_pages(self) -> TitulosExtractionResult:
        """Itera pelas páginas até consumir todos os registros."""
        todos: List[dict] = []
        offset = 0
        total = 0
        inicio = time.monotonic()

        try:
            while True:
                pagina = (offset // self._config.limit) + 1
                logger.info("Buscando página %d (offset=%d)...", pagina, offset)

                url = self._build_url(offset=offset)
                data = self._requester.get(url)

                metadata = data.get("resultSetMetadata", {})
                total    = metadata.get("count", 0)
                results: List[dict] = data.get("results", [])

                # Na primeira página, anuncia o total esperado
                if offset == 0:
                    paginas_total = -(-total // self._config.limit)  # ceiling division
                    logger.info(
                        "Total de registros a extrair: %d (~%d páginas de %d por página)",
                        total, paginas_total, self._config.limit,
                    )

                if not results:
                    logger.info("Nenhum resultado na página %d — encerrando.", pagina)
                    break

                todos.extend(self._normalizar(results))
                offset += len(results)

                elapsed = time.monotonic() - inicio
                pct = (offset / total * 100) if total else 0
                logger.info(
                    "  Página %d OK: +%d registros | acumulado %d/%d (%.1f%%) | tempo decorrido %.1fs",
                    pagina, len(results), offset, total, pct, elapsed,
                )

                if offset >= total:
                    break

            elapsed_total = time.monotonic() - inicio
            logger.info(
                "Paginação concluída em %.1fs — %d registros em %d páginas.",
                elapsed_total, len(todos), (offset // self._config.limit) or 1,
            )
            return TitulosExtractionResult(registros=todos, sucesso=True)

        except requests.HTTPError as exc:
            return TitulosExtractionResult(
                registros=[],
                sucesso=False,
                erro=f"HTTPError: {exc.response.status_code if exc.response else exc}",
            )
        except Exception as exc:  # noqa: BLE001
            return TitulosExtractionResult(
                registros=[],
                sucesso=False,
                erro=str(exc),
            )

    def _normalizar(self, results: List[dict]) -> List[dict]:
        """
        Mapeia cada título bruto para o formato do relatório manual
        com colunas em PT-BR, incluindo campos de auditoria.
        """
        normalizados = []
        for item in results:
            bruto    = item.get("totalInvoiceAmount") or 0.0
            desconto = item.get("discount") or 0.0
            tipo_doc = item.get("documentIdentificationId") or ""
            num_doc  = item.get("documentNumber") or ""

            normalizados.append({
                # --- Colunas do relatório manual ---
                "titulo":            item.get("id"),
                "credor":            item.get("creditorId"),
                "documento":         f"{tipo_doc}/{num_doc}".strip("/"),
                "origem":            item.get("originId"),
                "emissao_nf":        item.get("issueDate"),
                "cadastro":          item.get("registeredDate"),
                "qtd":               item.get("installmentsNumber"),
                "valor_bruto":       bruto,
                "descontos":         desconto,
                "valor_liquido":     round(bruto - desconto, 2),

                # --- Auditoria e rastreabilidade ---
                "devedor_id":        item.get("debtorId"),
                "status":            item.get("status"),
                "tipo_documento":    tipo_doc,
                "numero_documento":  num_doc,
                "observacao":        item.get("notes"),
                "chave_nfe":         item.get("accessKeyNumber"),
                "cadastrado_por_id": item.get("registeredUserId"),
                "cadastrado_por":    item.get("registeredBy"),
                "cadastrado_em":     item.get("registeredDate"),
                "alterado_por_id":   item.get("changedUserId"),
                "alterado_por":      item.get("changedBy"),
                "alterado_em":       item.get("changedDate"),
            })
        return normalizados

    def _build_url(self, offset: int = 0) -> str:
        cfg = self._config
        params = [
            f"startDate={cfg.start_date}",
            f"endDate={cfg.end_date}",
            f"limit={cfg.limit}",
            f"offset={offset}",
        ]

        # Filtros opcionais — só adicionados se definidos na config
        if cfg.debtor_id is not None:
            params.append(f"debtorId={cfg.debtor_id}")
        if cfg.creditor_id is not None:
            params.append(f"creditorId={cfg.creditor_id}")
        if cfg.cost_center_id is not None:
            params.append(f"costCenterId={cfg.cost_center_id}")
        if cfg.documents_identification_id:
            params.append(f"documentsIdentificationId={cfg.documents_identification_id}")
        if cfg.document_number:
            params.append(f"documentNumber={cfg.document_number}")
        if cfg.status:
            params.append(f"status={cfg.status}")
        if cfg.origin_id:
            params.append(f"originId={cfg.origin_id}")

        query = "&".join(params)
        return f"{API_CONFIG.base_url}v1/bills?{query}"

    @staticmethod
    def _log_summary(result: TitulosExtractionResult) -> None:
        logger.info("=" * 50)
        logger.info("Extração de Títulos finalizada:")
        if result.sucesso:
            logger.info("  Total registros : %d", len(result.registros))
        else:
            logger.error("  Falha na extração: %s", result.erro)
        logger.info("=" * 50)