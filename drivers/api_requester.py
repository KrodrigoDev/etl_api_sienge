"""
ApiRequester — coração da extração.

Responsabilidades:
  - Gerenciar sessão autenticada com a API Sienge.
  - Aplicar rate limiting conforme documentação oficial (20 req/min).
  - Aplicar retry com exponential backoff em falhas transitórias.
  - Retornar dados brutos (JSON) sem qualquer transformação.
"""
import logging
import os
import time
from typing import Any

import requests
from dotenv import load_dotenv

from config.settings import ApiConfig

load_dotenv(r"D:\GitHub\etl_api_sienge\.env")

logger = logging.getLogger(__name__)

# HTTP status que justificam retry (erros transitórios)
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class AuthenticationError(Exception):
    """Credenciais ausentes ou inválidas."""


class RateLimitError(Exception):
    """Limite de requisições da API atingido após todos os retries."""


class ApiRequester:
    """
    Cliente HTTP para a API Sienge.

    Thread-safety: uma instância por thread/worker.
    """

    def __init__(self, config: ApiConfig = ApiConfig()):
        self._config = config
        self._session = self._build_session()
        logger.info("ApiRequester inicializado.")

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _build_session(self) -> requests.Session:
        usuario = os.getenv("USUARIO_SIENGE")
        senha = os.getenv("SENHA")

        if not usuario or not senha:
            raise AuthenticationError(
                "Variáveis USUARIO_SIENGE e SENHA não encontradas no ambiente."
            )

        session = requests.Session()
        session.auth = (usuario, senha)
        session.headers.update({"Content-Type": "application/json"})
        return session

    # ------------------------------------------------------------------
    # Requisição com retry + rate limiting
    # ------------------------------------------------------------------

    def get(self, url: str) -> Any:
        """
        Executa GET com retry exponencial e respeita o rate limit.

        Returns:
            Objeto Python deserializado do JSON da resposta.

        Raises:
            RateLimitError: quando 429 persiste após todos os retries.
            requests.HTTPError: para erros HTTP não recuperáveis.
        """
        attempt = 0
        delay = self._config.rate_limit_seconds

        while attempt <= self._config.max_retries:
            try:
                response = self._session.get(url, timeout=self._config.timeout)

                if response.status_code == 429:
                    wait = self._retry_after(response, delay)
                    logger.warning(
                        "Rate limit atingido. Aguardando %.1fs antes do retry %d/%d.",
                        wait, attempt + 1, self._config.max_retries,
                    )
                    time.sleep(wait)
                    attempt += 1
                    delay *= self._config.retry_backoff_factor
                    continue

                if response.status_code in RETRYABLE_STATUS:
                    logger.warning(
                        "Status %d recebido. Retry %d/%d em %.1fs.",
                        response.status_code, attempt + 1,
                        self._config.max_retries, delay,
                    )
                    time.sleep(delay)
                    attempt += 1
                    delay *= self._config.retry_backoff_factor
                    continue

                response.raise_for_status()
                return response.json()

            except requests.Timeout:
                logger.warning(
                    "Timeout na requisição. Retry %d/%d em %.1fs.",
                    attempt + 1, self._config.max_retries, delay,
                )
                time.sleep(delay)
                attempt += 1
                delay *= self._config.retry_backoff_factor

        raise RateLimitError(
            f"Máximo de retries ({self._config.max_retries}) atingido para: {url}"
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _retry_after(response: requests.Response, fallback: float) -> float:
        """Lê o header Retry-After da resposta 429, ou usa fallback."""
        header = response.headers.get("Retry-After")
        try:
            return float(header) if header else fallback
        except ValueError:
            return fallback

    def rate_limit_sleep(self) -> None:
        """Pausa respeitando o limite de 20 req/min da API."""
        time.sleep(self._config.rate_limit_seconds)
