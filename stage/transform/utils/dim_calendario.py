from pathlib import Path

import pandas as pd


pasta_origem = Path(__file__).resolve().parents[1]
OUTPUT_DIR = pasta_origem /  "files" / "output"


def gerar_dim_calendario(data_inicio: str, data_fim: str) -> pd.DataFrame:
    datas = pd.date_range(start=data_inicio, end=data_fim, freq="D")
    df = pd.DataFrame({"data": datas})

    # Semana Sáb → Sex
    # dayofweek: Seg=0 ... Sáb=5, Dom=6
    df["offset_para_sabado"] = df["data"].dt.dayofweek.map(
        {0: 2, 1: 1, 2: 0, 3: 6, 4: 5, 5: 0, 6: 1}
    )
    # alternativa com fórmula:
    # df["offset_para_sabado"] = (df["data"].dt.dayofweek - 5) % 7

    df["semana_inicio"] = (
            df["data"]
            - pd.to_timedelta((df["data"].dt.dayofweek + 2) % 7, unit="D")
    )
    df["semana_fim"]    = df["semana_inicio"] + pd.Timedelta(days=6)

    # Número sequencial da semana (para ordenação no Power BI)
    semanas_unicas = sorted(df["semana_inicio"].unique())
    semana_seq_map = {s: i + 1 for i, s in enumerate(semanas_unicas)}
    df["semana_seq"] = df["semana_inicio"].map(semana_seq_map)

    # Labels
    df["semana_label"] = (
        "Sem " + df["semana_inicio"].dt.strftime("%d/%m")
        + " → " + df["semana_fim"].dt.strftime("%d/%m")
    )
    df["semana_label_curto"] = "Sem " + df["semana_inicio"].dt.strftime("%d/%m")

    # Atributos de data
    df["ano"]            = df["data"].dt.year
    df["mes_num"]        = df["data"].dt.month
    df["mes_nome"]       = df["data"].dt.strftime("%B").str.capitalize()
    df["ano_mes"]        = df["data"].dt.strftime("%Y-%m")  # para ordenação
    df["dia_semana_num"] = df["data"].dt.dayofweek  # Seg=0 ... Dom=6
    df["is_fim_de_semana"] = df["data"].dt.dayofweek.isin([5, 6])  # Sáb=5, Dom=6
    df["dia_do_mes"]     = df["data"].dt.day
    df["trimestre"]      = df["data"].dt.quarter

    dias_semana = {
        0: "Segunda-feira",
        1: "Terça-feira",
        2: "Quarta-feira",
        3: "Quinta-feira",
        4: "Sexta-feira",
        5: "Sábado",
        6: "Domingo"
    }

    df["dia_semana_nome"] = (
        df["data"]
        .dt.dayofweek
        .map(dias_semana)
    )

    # Garante semanas completas — preenche com zeros nos fatos via left join
    # A dim_calendario É a espinha — ela tem todos os dias, os fatos é que podem ter lacunas

    return df[[
        "data",
        "ano", "trimestre", "mes_num", "mes_nome", "ano_mes",
        "dia_do_mes", "dia_semana_num", "dia_semana_nome", "is_fim_de_semana",
        "semana_inicio", "semana_fim", "semana_seq",
        "semana_label", "semana_label_curto",
    ]]



def gerar_dim_periodo_semanas() -> pd.DataFrame:
    return pd.DataFrame([
        {"id_periodo": 1, "label_periodo": "Última semana",    "qtd_semanas": 1},
        {"id_periodo": 2, "label_periodo": "Últimas 3 semanas", "qtd_semanas": 3},
        {"id_periodo": 3, "label_periodo": "Últimas 4 semanas", "qtd_semanas": 4},
        {"id_periodo": 4, "label_periodo": "Últimas 6 semanas", "qtd_semanas": 6},
        {"id_periodo": 5, "label_periodo": "Últimas 8 semanas", "qtd_semanas": 8},
        {"id_periodo": 6, "label_periodo": "Últimas 12 semanas","qtd_semanas": 12},
        {"id_periodo": 7, "label_periodo": "Todo o período",    "qtd_semanas": 9999},
    ])

dim_periodo = gerar_dim_periodo_semanas()
dim_periodo.to_csv((OUTPUT_DIR / "dim_periodo_semanas.csv"), sep=";", index=False)

# Gerar para o período completo do projeto
dim_cal = gerar_dim_calendario("2000-01-01", "2050-12-31")
dim_cal.to_csv((OUTPUT_DIR / "dim_calendario.csv"), sep=";", index=False)