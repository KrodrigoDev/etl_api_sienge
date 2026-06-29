"""
Configurações centralizadas do pipeline Sienge.
"""
from dataclasses import dataclass, field
from typing import Tuple, Optional

EMPRESAS: Tuple[int, ...] = field(default_factory=lambda: (
    6, 97, 100, 102, 103, 104, 105, 106, 112, 113, 120, 125, 127, 130, 131,
    137, 138, 139, 140, 158, 166, 190, 20, 333, 45, 64, 67, 72, 73, 83, 84,
    90, 92, 94, 167, 204
))


@dataclass(frozen=True)
class ExtratoClienteHistoricoConfig:
    """
    Configuração para extração da série histórica mensal do extrato de cliente.

    Documentação:
      https://api.sienge.com.br/v1/docs/#tag/bulk-data-extrato-cliente-hist%C3%B3rico/get/bulk-data/v1/customer-extract-history

    ┌─────────────────────────────────────────────────────────────────┐
    │  VARIÁVEIS PRINCIPAIS — ajuste aqui para controlar a série      │
    ├──────────────────────┬──────────────────────────────────────────┤
    │  competencia_inicio  │  Primeiro mês de competência (inclusive) │
    │  competencia_fim     │  Último mês de competência  (inclusive)  │
    └──────────────────────┴──────────────────────────────────────────┘

    Formato: "YYYY-MM"
    Exemplos:
      competencia_inicio = "2023-01"   # janeiro de 2023
      competencia_fim    = "2025-05"   # maio de 2025  → 29 requisições

    Lógica interna (automática, não precisa alterar):
      Para cada mês M em [inicio, fim]:
        positionDate = 1º dia de M+1
        → jan/2023 usa positionDate = "2023-02-01"
        → mai/2025 usa positionDate = "2025-06-01"

    documentsId = "CT" é fixado diretamente na URL pelo extrator
    (somente contratos, conforme requisito negocial).
    """

    # ------------------------------------------------------------------ #
    #  VARIÁVEIS PRINCIPAIS                                                #
    # ------------------------------------------------------------------ #

    competencia_inicio: str = "2026-01"   # <- altere aqui
    competencia_fim: str = "2026-05"      # <- altere aqui

    # ------------------------------------------------------------------ #
    #  Janela de vencimento das parcelas (normalmente não precisa mudar)   #
    # ------------------------------------------------------------------ #
    start_due_date: str = "2001-01-01"
    end_due_date: str = "2050-12-31"

    # Data de correção do indexador (None = data atual da API)
    correction_date: Optional[str] = None

    # Filtros opcionais
    company_id: Optional[int] = None
    customer_id: Optional[int] = None
    cost_center_id: Optional[int] = None

    # Flags de inclusão
    include_remade_installments: bool = True        # parcelas reparceladas
    include_canceled_installments: bool = True      # parcelas canceladas
    include_revoked_installments: bool = True       # parcelas distratadas
    include_renegotiated_discharge: bool = True     # baixas por repactuação

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
    Documentação: https://api.sienge.com.br/v1/docs/#tag/bulk-data-contratos-de-vendas/get/bulk-data/v1/sales
    
    A situação pode ser SOLD ou CANCELED
    """
    situacao: str = "SOLD"
    periodo: Tuple[str, str] = ("2001-01-01", "2030-10-05")
    empresas: Tuple[int, ...] = EMPRESAS

@dataclass(frozen=True)
class EstoqueEmpreedimentoConfig:
    """

    Documentação: https://api.sienge.com.br/v1/docs/#tag/unidades-de-im%C3%B3veis/patch/v1/units/{unitId}
    """
    limit: int = 200
    offset: int = 0
    empresas: Tuple[int, ...] = EMPRESAS




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


@dataclass(frozen=True)
class ContasAReceberConfig:
    """
    Documentação: https://api.sienge.com.br/v1/docs/#tag/bulk-data-parcelas-do-contas-a-receber
    """
    start_date: str = "2025-01-01"
    end_date: str = "2050-01-01"
    selection_type: str = "D"


@dataclass(frozen=True)
class TitulosContasPagasConfig:
    """
    Configuração para extração de títulos do contas a pagar.

    Documentação: https://api.sienge.com.br/v1/docs/#/bills

    Filtros opcionais deixados como None não são enviados na query string.
    """
    start_date: str = "2022-01-01"
    end_date: str = "2050-12-31"
    limit: int = 200  # máximo permitido pela API

    # Filtros opcionais
    debtor_id: int | None = None  # Código da empresa (debtorId)
    creditor_id: int | None = None  # Código do credor
    cost_center_id: int | None = None  # Código do centro de custo
    documents_identification_id: str | None = None  # Ex.: "NF,REC"
    document_number: str | None = None  # Número do documento (max 20 chars)
    status: str | None = None  # "S" | "N" | "I"
    origin_id: str | None = None  # "AC" | "CP" | "FP" | etc.


@dataclass(frozen=True)
class CredoresConfig:
    """
    Configuração para extração de credores.

    Documentação: https://api.sienge.com.br/v1/docs/#/creditors

    Sem filtros obrigatórios — sem informar nada, traz todos os credores.
    cnpj aceita múltipla valores: cnpj=("79164911000104", "77288031000114")
    """
    limit: int = 200

    # Filtros opcionais
    cpf: str | None = None  # CPF sem máscara, só números
    cnpj: tuple[str, ...] = ()  # CNPJs sem máscara, pode ser vários
    creditor: str | None = None  # Nome, nome fantasia ou código do credor


API_CONFIG = ApiConfig()
