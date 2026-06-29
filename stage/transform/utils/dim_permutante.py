

"""
stages/transform/dim_permutante_transformer.py
-----------------------------------------------
Constrói a dim_permutante a partir de uma planilha manual (fonte de verdade)
e gera a chave composta normalizada para relacionamento com fato_estoque_unidades
e fato_vendas.

Chave composta:
    cod_centro_de_custo + "_" + nome_unidade_normalizado

Normalização do nome_unidade:
    - lower()
    - strip()
    - ponto (.) vira underscore quando seguido de letra ou número  → "BL.C" → "bl_c"
    - /, -, espaço viram underscore                                → "BL.C/707" → "bl_c_707"
    - múltiplos underscores colapsados
    - underscores nas bordas removidos

Isso preserva a distinção entre blocos:
    BL.A/708 → bl_a_708  ≠  BL.B/708 → bl_b_708

Para adicionar novos permutantes:
    1. Adicione linhas na planilha dim_permutantes.xlsx
       (colunas: Empreend. | Unidade | Permutante)
    2. Rode este script — upsert: mantém existentes, acrescenta novos.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
import logging

import pandas as pd

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURAÇÃO
# ─────────────────────────────────────────────────────────────────────────────

pasta_origem = Path(__file__).resolve().parents[1]

REFERENCE_DIR = pasta_origem / "files" / "reference"
OUTPUT_DIR = pasta_origem /  "files" / "output"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger(__name__)

ARQUIVO_PERMUTANTES = REFERENCE_DIR / "dim_permutantes.xlsx"


# ─────────────────────────────────────────────────────────────────────────────
# NORMALIZAÇÃO
# ─────────────────────────────────────────────────────────────────────────────

def normalizar_unidade(valor: str | float | None) -> str:
    """
    Normaliza o nome da unidade para chave de join entre fontes distintas.

    Regras (nesta ordem):
        1. strip + lower
        2. ponto + espaços opcionais + letra/número → underscore + caractere
           "BL.C"  → "bl_c"    (sem espaço)
           "BL. C" → "bl_c"    (com espaço — variação real dos dados)
        3. separadores restantes (/, -, espaço) → underscore
        4. múltiplos underscores → um único underscore
        5. underscores nas bordas removidos

    Exemplos:
        "BL.C/707"  → "bl_c_707"
        "BL. B/807" → "bl_b_807"   ← espaço após ponto tratado
        "BL.B/708"  → "bl_b_708"   ← distinto de "BL.A/708" → "bl_a_708"
        "APT 301"   → "apt_301"
        "LOJAO 12"  → "lojao_12"
        "401"       → "401"
        "UND-503"   → "und_503"
    """
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return ""

    texto = str(valor).strip().lower()

    # Ponto seguido de espaços opcionais + letra/número → underscore + caractere
    # Cobre "BL.C" e "BL. C" (variação com espaço após o ponto)
    texto = re.sub(r"\.\s*([a-z0-9])", r"_\1", texto)

    # Demais separadores (/, -, espaço) → underscore
    texto = re.sub(r"[\s/\-]+", "_", texto)

    # Colapsa múltiplos underscores e remove das bordas
    texto = re.sub(r"_+", "_", texto).strip("_")

    return texto


def gerar_chave_permutante(cod_centro_de_custo, nome_unidade: str | float) -> str:
    """
    Gera a chave composta usada para relacionar as três tabelas:
        fato_estoque_unidades  →  dim_permutante  ←  fato_vendas

    Formato: "{cod_centro_de_custo}_{nome_unidade_normalizado}"

    Importável pelos outros transformers:

        from dim_permutante_transformer import gerar_chave_permutante

        df["chave_permutante"] = df.apply(
            lambda r: gerar_chave_permutante(
                r["cod_centro_de_custo"], r["nome_unidade"]
            ),
            axis=1,
        )
    """
    centro = str(cod_centro_de_custo).strip().lower()
    unidade = normalizar_unidade(nome_unidade)
    return f"{centro}_{unidade}"


# ─────────────────────────────────────────────────────────────────────────────
# FUNÇÃO PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

def executar(
        arquivo_permutantes: Path = ARQUIVO_PERMUTANTES,
        output_dir: Path = OUTPUT_DIR,
) -> pd.DataFrame:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # ── 1. Leitura da planilha manual ─────────────────────────────────────────
    print("\n── 1. Leitura da planilha de permutantes ───────────────────────────")

    df_raw = pd.read_excel(arquivo_permutantes, dtype=str)

    # Mapeamento flexível de cabeçalhos (aceita variações)
    col_map = {}
    for col in df_raw.columns:
        c = col.strip().lower()
        if c in ("empreend.", "empreendimento", "emp.", "cod_centro_de_custo", "obra"):
            col_map[col] = "cod_centro_de_custo"
        elif c in ("unidade", "und", "und.", "unid"):
            col_map[col] = "nome_unidade_raw"
        elif c in ("permutante", "nome_permutante", "permutante_nome"):
            col_map[col] = "nome_permutante"
        # Colunas extras (ex: "Chave = obra+unidades") são ignoradas — recalculamos aqui

    df_raw = df_raw.rename(columns=col_map)

    colunas_necessarias = {"cod_centro_de_custo", "nome_unidade_raw", "nome_permutante"}
    faltando = colunas_necessarias - set(df_raw.columns)
    if faltando:
        raise ValueError(
            f"Planilha não tem as colunas esperadas: {faltando}. "
            f"Encontradas: {list(df_raw.columns)}"
        )

    df_raw = df_raw.dropna(subset=["cod_centro_de_custo", "nome_unidade_raw", "nome_permutante"])
    df_raw = df_raw[df_raw["nome_permutante"].str.strip() != ""]

    print(f"  {len(df_raw)} registros lidos.")

    # ── 2. Normalização e geração da chave ────────────────────────────────────
    print("\n── 2. Normalização ─────────────────────────────────────────────────")

    df_raw["cod_centro_de_custo"] = df_raw["cod_centro_de_custo"].str.strip()
    df_raw["nome_unidade_norm"] = df_raw["nome_unidade_raw"].apply(normalizar_unidade)
    df_raw["chave_permutante"] = df_raw.apply(
        lambda r: gerar_chave_permutante(r["cod_centro_de_custo"], r["nome_unidade_raw"]),
        axis=1,
    )

    # Alerta de chaves duplicadas (mesmo empreendimento + mesma unidade normalizada)
    dupes = df_raw[df_raw.duplicated("chave_permutante", keep=False)]
    if not dupes.empty:
        logger.warning(
            "  %d linhas com chave_permutante duplicada — verifique a planilha:\n%s",
            len(dupes),
            dupes[["nome_unidade_raw", "chave_permutante", "nome_permutante"]].to_string(index=False),
        )

    # ── 3. Montagem da dim ────────────────────────────────────────────────────
    print("\n── 3. Montagem da dim_permutante ───────────────────────────────────")

    dim = df_raw[[
        "chave_permutante",  # PK — join com fato_estoque e fato_vendas
        "cod_centro_de_custo",  # FK → dim_centro_custo
        "nome_unidade_raw",  # valor original (auditoria)
        "nome_unidade_norm",  # valor normalizado (conferência)
        "nome_permutante",  # dado de negócio
    ]].copy()

    dim["data_carga"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ── 4. Upsert ─────────────────────────────────────────────────────────────
    print("\n── 4. Upsert ───────────────────────────────────────────────────────")

    saida_path = output_dir / "dim_permutante.csv"

    if saida_path.exists():
        dim_existente = pd.read_csv(saida_path, sep=";", dtype=str)
        chaves_existentes = set(dim_existente["chave_permutante"].dropna())

        novos = dim[~dim["chave_permutante"].isin(chaves_existentes)]
        atualizados = dim[dim["chave_permutante"].isin(chaves_existentes)]

        dim_existente = dim_existente.set_index("chave_permutante")
        for _, row in atualizados.iterrows():
            chave = row["chave_permutante"]
            if chave in dim_existente.index:
                dim_existente.at[chave, "nome_permutante"] = row["nome_permutante"]
                dim_existente.at[chave, "nome_unidade_norm"] = row["nome_unidade_norm"]
                dim_existente.at[chave, "data_carga"] = row["data_carga"]

        dim_final = pd.concat([dim_existente.reset_index(), novos], ignore_index=True)
        logger.info("  %d atualizados, %d novos.", len(atualizados), len(novos))
    else:
        dim_final = dim
        logger.info("  Arquivo novo — %d registros.", len(dim_final))

    # ── 5. Diagnóstico ────────────────────────────────────────────────────────
    print("\n── 5. Diagnóstico (amostra) ────────────────────────────────────────")
    print(
        dim_final[["nome_unidade_raw", "nome_unidade_norm", "chave_permutante", "nome_permutante"]]
        .head(12)
        .to_string(index=False)
    )

    # ── 6. Exportação ─────────────────────────────────────────────────────────
    dim_final.to_csv(saida_path, sep=";", index=False, encoding="utf-8-sig")
    print(f"\n── Exportado: {saida_path} ({len(dim_final)} linhas)")

    # ── 7. Resumo ─────────────────────────────────────────────────────────────
    print("\n── Resumo ──────────────────────────────────────────────────────────")
    print(f"  {'dim_permutante':<40} {str(dim_final.shape):>12}")
    print(f"  Permutantes únicos  : {dim_final['nome_permutante'].nunique()}")
    print(f"  Empreendimentos     : {dim_final['cod_centro_de_custo'].nunique()}")
    print(f"  Chaves únicas       : {dim_final['chave_permutante'].nunique()}")

    return dim_final


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    executar()