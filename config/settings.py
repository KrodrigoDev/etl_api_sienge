"""
Configurações centralizadas do pipeline Sienge.
"""
from dataclasses import dataclass, field
from typing import Tuple


@dataclass(frozen=True)
class ApiConfig:
    base_url: str = "https://api.sienge.com.br/telesil/public/api/"
    timeout: int = 240
    # Documentação oficial: 20 req/min → 1 req a cada 3s com margem de segurança
    rate_limit_seconds: float = 3.5
    max_retries: int = 3
    retry_backoff_factor: float = 2.0  # Exponential backoff: 3.5s, 7s, 14s


@dataclass(frozen=True)
class VendasConfig:
    """
    Documentação:
    """
    situacao: str = "SOLD"
    periodo: Tuple[str, str] = ("2019-01-01", "2030-10-05")
    empresas: Tuple[int, ...] = field(default_factory=lambda: (
        6, 97, 100, 102, 103, 104, 105, 106, 112, 113, 120, 125, 127, 130, 131,
        137, 138, 139, 140, 158, 166, 190, 20, 333, 45, 64, 67, 72, 73, 83, 84,
        90, 92, 94
    ))


@dataclass(frozen=True)
class ContasPagasConfig:
    """
     Documentação: https://api.sienge.com.br/v1/docs/#tag/bulk-data-parcelas-a-pagar/get/bulk-data/v1/outcome
    """
    start_date: str = "2024-01-01"
    end_date: str = "2050-12-31"
    selection_type: str = "D"
    correction_indexer_id: int = 0
    correction_date: str = "2025-01-01"
    with_authorizations: bool = False
    with_bank_movements: bool = True


@dataclass(frozen=True)
class ContasRecebidasConfig:
    """
    Documentação: https://api.sienge.com.br/v1/docs/#tag/bulk-data-parcelas-do-contas-a-receber/get/bulk-data/v1/income
    """
    start_date: str = "2025-01-01"
    end_date: str = "2050-01-01"
    selection_type: str = "P"


API_CONFIG = ApiConfig()
VENDAS_CONFIG = VendasConfig()
