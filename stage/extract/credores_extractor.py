"""
Extrator de Credores da API Sienge.

Responsabilidade única: buscar dados paginados de credores via endpoint
/v1/creditors e retorná-los como lista de dicts, sem transformação pesada.

Colunas extraídas (pt-br):
  cod_credor      → id
  nome_credor     → name
  nome_fantasia   → tradeName
  cpf             → cpf
  cnpj            → cnpj
  ativo           → active

Relacionamento com Títulos:
  titulos.credor (creditorId) == credores.cod_credor (id)
"""
import logging
import time
from dataclasses import dataclass
from typing import List

import requests

from config.settings import API_CONFIG, CredoresConfig
from drivers.api_requester import ApiRequester

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Resultado
# ---------------------------------------------------------------------------

@dataclass
class CredoresExtractionResult:
    """Resultado bruto de uma extração de credores."""
    registros: List[dict]
    sucesso: bool
    erro: str = ""


# ---------------------------------------------------------------------------
# Extractor
# ---------------------------------------------------------------------------

class CredoresExtractor:
    """
    Extrai credores via endpoint paginado /v1/creditors.

    Sem filtros obrigatórios — traz todos os credores cadastrados.
    Filtros opcionais (cpf, cnpj, creditor) disponíveis via CredoresConfig.

    Separado do ApiRequester para respeitar SRP:
      - ApiRequester      → sabe como fazer requisições HTTP
      - CredoresExtractor → sabe qual endpoint chamar e como paginar
    """

    def __init__(
        self,
        requester: ApiRequester | None = None,
        config: CredoresConfig = CredoresConfig(),
    ):
        self._requester = requester or ApiRequester(API_CONFIG)
        self._config = config

    # ------------------------------------------------------------------
    # Interface pública
    # ------------------------------------------------------------------

    def extract(self) -> CredoresExtractionResult:
        """
        Percorre todas as páginas da API e retorna o resultado consolidado.

        Nunca lança exceção: erros são capturados e registrados
        no campo `erro` do resultado.
        """
        logger.info("Iniciando extração de credores...")
        result = self._extract_all_pages()
        self._log_summary(result)
        return result

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------

    def _extract_all_pages(self) -> CredoresExtractionResult:
        """Itera pelas páginas até consumir todos os registros."""
        todos: List[dict] = []
        offset = 0
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

                if offset == 0:
                    paginas_total = -(-total // self._config.limit)
                    logger.info(
                        "Total de credores a extrair: %d (~%d páginas de %d por página)",
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
                "Paginação concluída em %.1fs — %d credores em %d páginas.",
                elapsed_total, len(todos), (offset // self._config.limit) or 1,
            )
            return CredoresExtractionResult(registros=todos, sucesso=True)

        except requests.HTTPError as exc:
            return CredoresExtractionResult(
                registros=[],
                sucesso=False,
                erro=f"HTTPError: {exc.response.status_code if exc.response else exc}",
            )
        except Exception as exc:  # noqa: BLE001
            return CredoresExtractionResult(
                registros=[],
                sucesso=False,
                erro=str(exc),
            )

    def _normalizar(self, results: List[dict]) -> List[dict]:
        """
        Mapeia cada credor bruto para colunas em PT-BR.

        A chave de relacionamento com títulos é:
          credores.cod_credor == titulos.credor
        """
        normalizados = []
        for item in results:
            normalizados.append({
                "cod_credor":    item.get("id"),       # ← chave de join com titulos.credor
                "nome_credor":   item.get("name"),
                "nome_fantasia": item.get("tradeName"),
                "cpf":           item.get("cpf"),
                "cnpj":          item.get("cnpj"),
                "ativo":         item.get("active"),
            })
        return normalizados

    def _build_url(self, offset: int = 0) -> str:
        cfg = self._config
        params = [
            f"limit={cfg.limit}",
            f"offset={offset}",
        ]

        # Filtros opcionais — só adicionados se definidos na config
        if cfg.cpf:
            params.append(f"cpf={cfg.cpf}")
        if cfg.cnpj:
            # cnpj aceita múltiplos valores: cnpj=X&cnpj=Y
            for cnpj in cfg.cnpj:
                params.append(f"cnpj={cnpj}")
        if cfg.creditor:
            params.append(f"creditor={cfg.creditor}")

        query = "&".join(params)
        return f"{API_CONFIG.base_url}v1/creditors?{query}"

    @staticmethod
    def _log_summary(result: CredoresExtractionResult) -> None:
        logger.info("=" * 50)
        logger.info("Extração de Credores finalizada:")
        if result.sucesso:
            logger.info("  Total registros : %d", len(result.registros))
        else:
            logger.error("  Falha na extração: %s", result.erro)
        logger.info("=" * 50)