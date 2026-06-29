"""
Extrator de Extrato Cliente Histórico da API Sienge.

Responsabilidade única: buscar dados brutos do extrato de cliente histórico
por posição (positionDate = primeiro dia do mês seguinte ao mês de competência),
iterando mês a mês para montar uma série histórica, e retorná-los como lista
de dicts planos com coluna `competencia` identificando cada mês.

Lógica de competência (idêntica ao programa VDQT):
  Para obter a posição de JANEIRO → positionDate = 2025-02-01 (início de fevereiro)
  Ou seja: positionDate = primeiro dia do mês M+1.

Controle da série histórica (em settings.py → ExtratoClienteHistoricoConfig):
  COMPETENCIA_INICIO = "2023-01"   # mês de competência inicial (inclusive)
  COMPETENCIA_FIM    = "2025-05"   # mês de competência final   (inclusive)
"""
import logging
from dataclasses import dataclass
from datetime import date
from typing import List, Optional

import requests

from config.settings import API_CONFIG, ExtratoClienteHistoricoConfig
from drivers.api_requester import ApiRequester

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Resultado
# ---------------------------------------------------------------------------

@dataclass
class ExtratoClienteHistoricoResult:
    """Resultado de uma série histórica de extrato de cliente."""
    registros: List[dict]
    sucesso: bool
    meses_processados: int = 0
    meses_com_erro: int = 0
    erro: str = ""


# ---------------------------------------------------------------------------
# Extractor
# ---------------------------------------------------------------------------



class ExtratoClienteHistoricoExtractor:
    """
    Extrai série histórica mensal do extrato de cliente histórico (bulk) via API Sienge.

    Lógica de posição (igual ao programa VDQT):
      - Para saber a posição de um mês de competência M, a extração deve
        ser feita com positionDate = primeiro dia de M+1.
      - Exemplo: competência janeiro/2025 → positionDate = 2025-02-01.

    Série histórica:
      - Itera de COMPETENCIA_INICIO até COMPETENCIA_FIM (ambos inclusive),
        fazendo uma requisição por mês de competência.
      - Cada registro recebe a coluna `competencia` no formato "YYYY-MM".
      - Erros em meses individuais são logados mas não interrompem a série.

    Separado do ApiRequester para respeitar SRP:
      - ApiRequester                        → sabe como fazer requisições HTTP
      - ExtratoClienteHistoricoExtractor    → sabe qual endpoint chamar e como expandir
    """

    ENDPOINT = "bulk-data/v1/customer-extract-history"

    def __init__(
            self,
            requester: ApiRequester | None = None,
            config: "ExtratoClienteHistoricoConfig" = None,
    ):
        if config is None:
            config = ExtratoClienteHistoricoConfig()
        self._requester = requester or ApiRequester(API_CONFIG)
        self._config = config

    # ------------------------------------------------------------------
    # Interface pública
    # ------------------------------------------------------------------

    def extract(self) -> ExtratoClienteHistoricoResult:
        """
        Itera mês a mês de COMPETENCIA_INICIO até COMPETENCIA_FIM,
        consolida todos os registros e retorna o resultado agregado.

        Nunca lança exceção: erros por mês são capturados e contabilizados
        em `meses_com_erro`.
        """
        cfg = self._config
        meses = self._gerar_meses(cfg.competencia_inicio, cfg.competencia_fim)

        logger.info(
            "Iniciando série histórica: %s → %s (%d meses)",
            cfg.competencia_inicio, cfg.competencia_fim, len(meses),
        )

        todos_registros: List[dict] = []
        meses_com_erro = 0

        for competencia in meses:
            position_date = self._competencia_para_position_date(competencia)
            logger.info(
                "  Extraindo competência %s (positionDate=correctionDate=%s)...",
                competencia, position_date,
            )

            registros, erro = self._extract_mes(competencia, position_date)

            if erro:
                logger.error("    Falha em %s: %s", competencia, erro)
                meses_com_erro += 1
            else:
                logger.info("    %d registros obtidos.", len(registros))
                todos_registros.extend(registros)

        result = ExtratoClienteHistoricoResult(
            registros=todos_registros,
            sucesso=meses_com_erro < len(meses),  # sucesso parcial já é sucesso
            meses_processados=len(meses) - meses_com_erro,
            meses_com_erro=meses_com_erro,
        )
        self._log_summary(result, len(meses))
        return result

    # ------------------------------------------------------------------
    # Internos — série histórica
    # ------------------------------------------------------------------

    @staticmethod
    def _gerar_meses(inicio: str, fim: str) -> List[str]:
        """
        Gera lista de competências no formato "YYYY-MM" entre inicio e fim (inclusive).

        Parâmetros aceitos: "YYYY-MM" ou "YYYY-MM-DD" (dia é ignorado).
        """

        def parse(s: str) -> date:
            partes = s.split("-")
            return date(int(partes[0]), int(partes[1]), 1)

        atual = parse(inicio)
        fim_d = parse(fim)
        meses: List[str] = []

        while atual <= fim_d:
            meses.append(atual.strftime("%Y-%m"))
            # avança um mês
            if atual.month == 12:
                atual = date(atual.year + 1, 1, 1)
            else:
                atual = date(atual.year, atual.month + 1, 1)

        return meses

    @staticmethod
    def _competencia_para_position_date(competencia: str) -> str:
        """
        Converte competência "YYYY-MM" em positionDate = 1º dia do mês seguinte.

        Exemplo: "2025-01" → "2025-02-01"
        """
        ano, mes = int(competencia[:4]), int(competencia[5:7])
        if mes == 12:
            return date(ano + 1, 1, 1).isoformat()
        return date(ano, mes + 1, 1).isoformat()

    def _extract_mes(
            self, competencia: str, position_date: str
    ) -> tuple[List[dict], str]:
        """
        Extrai o snapshot de um único mês de competência.

        startDueDate/endDueDate são fixos na config (toda a carteira).
        positionDate e correctionDate = 1º dia do mês seguinte (dinâmico).

        Retorna (registros, erro): se erro for vazio, a extração teve sucesso.
        """
        url = self._build_url(position_date)
        try:
            data = self._requester.get(url)
            registros_brutos: List[dict] = (
                data if isinstance(data, list) else data.get("data", [])
            )
            registros: List[dict] = []
            for titulo in registros_brutos:
                registros.extend(self._expand_titulo(titulo, competencia))
            return registros, ""

        except requests.HTTPError as exc:
            erro = f"HTTPError: {exc.response.status_code if exc.response else exc}"
            return [], erro
        except Exception as exc:  # noqa: BLE001
            return [], str(exc)

    # ------------------------------------------------------------------
    # Internos — expansão de registros
    # ------------------------------------------------------------------

    @staticmethod
    def _prefix_dict(data: dict, prefix: str) -> dict:
        return {f"{prefix}_{k}": v for k, v in data.items()}

    def _expand_titulo(self, titulo: dict, competencia: str) -> List[dict]:
        """
        Expande as sub-listas de um título em registros planos,
        adicionando a coluna `competencia` em cada registro.

        Hierarquia:
          titulo
          └── installments (parcelas)
                └── receipts (baixas por parcela)

        Filtro de documento:
          Mantém apenas document iniciado em "CT." (somente contratos).
        """
        document: str = titulo.get("document", "") or ""
        if not document.startswith("CT."):
            return []

        installments = titulo.get("installments") or [{}]

        _SKIP = {"installments", "company", "costCenter", "customer", "units"}
        titulo_base = {k: v for k, v in titulo.items() if k not in _SKIP}

        company = titulo.get("company") or {}
        cost_center = titulo.get("costCenter") or {}
        customer = titulo.get("customer") or {}

        units: list = titulo.get("units") or []
        units_names = ", ".join(u.get("name", "") for u in units if u.get("name"))
        units_ids = ", ".join(str(u.get("id", "")) for u in units if u.get("id") is not None)

        titulo_flat = {
            **titulo_base,
            "company_id": company.get("id"),
            "company_name": company.get("name"),
            "costCenter_id": cost_center.get("id"),
            "costCenter_name": cost_center.get("name"),
            "customer_id": customer.get("id"),
            "customer_name": customer.get("name"),
            "customer_document": customer.get("document"),
            "units_ids": units_ids,
            "units_names": units_names,
        }

        registros: List[dict] = []

        for installment in installments:
            receipts = installment.get("receipts") or [{}]
            payment_terms = installment.get("paymentTerms") or {}

            _SKIP_INST = {"receipts", "paymentTerms"}
            installment_base = {k: v for k, v in installment.items() if k not in _SKIP_INST}

            installment_flat = {
                **self._prefix_dict(installment_base, "installments"),
                "installments_paymentTerms_id": payment_terms.get("id"),
                "installments_paymentTerms_description": payment_terms.get("descrition"),
            }

            for receipt in receipts:
                registro = {
                    "competencia": competencia,  # ← coluna de competência
                    **self._prefix_dict(titulo_flat, "outcome"),
                    **installment_flat,
                    **self._prefix_dict(receipt, "receipts"),
                }
                registros.append(registro)

        return registros

    # ------------------------------------------------------------------
    # Internos — URL
    # ------------------------------------------------------------------

    def _build_url(self, position_date: str) -> str:
        """
        Monta a URL da requisição.

        startDueDate e endDueDate são FIXOS — cobrem toda a carteira.
        O que muda a cada snapshot mensal é:
          - positionDate   = 1º dia do mês seguinte ao mês de competência
          - correctionDate = mesmo valor que positionDate

        Exemplos:
          jan/2026 → positionDate=2026-02-01 | correctionDate=2026-02-01
          fev/2026 → positionDate=2026-03-01 | correctionDate=2026-03-01
        """
        cfg = self._config

        params = [
            f"startDueDate={cfg.start_due_date}",
            f"endDueDate={cfg.end_due_date}",
            f"positionDate={position_date}",
            # f"correctionDate={position_date}",
            "documentsId=CT",
            f"includeRemadeInstallments={str(cfg.include_remade_installments).lower()}",
            f"includeCanceledInstallments={str(cfg.include_canceled_installments).lower()}",
            f"includeRevokedInstallments={str(cfg.include_revoked_installments).lower()}",
            f"includeRenegotiatedDischarge={str(cfg.include_renegotiated_discharge).lower()}",
        ]

        if cfg.company_id is not None:
            params.append(f"companyId={cfg.company_id}")
        if cfg.customer_id is not None:
            params.append(f"customerId={cfg.customer_id}")
        if cfg.cost_center_id is not None:
            params.append(f"costCenterId={cfg.cost_center_id}")

        return f"{API_CONFIG.base_url}{self.ENDPOINT}?{'&'.join(params)}"

    # ------------------------------------------------------------------
    # Log
    # ------------------------------------------------------------------

    @staticmethod
    def _log_summary(result: ExtratoClienteHistoricoResult, total_meses: int) -> None:
        logger.info("=" * 50)
        logger.info("Série histórica de Extrato Cliente finalizada:")
        logger.info("  Meses processados : %d / %d", result.meses_processados, total_meses)
        logger.info("  Meses com erro    : %d", result.meses_com_erro)
        logger.info("  Total registros   : %d", len(result.registros))
        if not result.sucesso:
            logger.error("  Todos os meses falharam.")
        logger.info("=" * 50)