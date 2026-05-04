"""
reporte.py — Módulo de reportes y visualizaciones del pipeline de Cálculo Vectorial UTEC.

Funciones para generar estadísticas por sección, identificar alumnos en riesgo,
comparar resultados entre ciclos y generar gráficas con matplotlib/seaborn.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns


# ---------------------------------------------------------------------------
# Estadísticas por sección
# ---------------------------------------------------------------------------

def estadisticas_por_seccion(
    df: pd.DataFrame,
    columna: str,
    col_seccion: str = "Sección",
) -> pd.DataFrame:
    """Calcula estadísticas de una columna de notas agrupadas por sección.

    Parameters
    ----------
    df:
        DataFrame con los datos de alumnos.
    columna:
        Nombre de la columna de notas a analizar (ej. "NF", "EA1").
    col_seccion:
        Nombre de la columna de sección (default: "Sección").

    Returns
    -------
    pd.DataFrame
        DataFrame con columnas: ``Sección``, ``N``, ``Media``, ``Mediana``,
        ``Std``, ``Mín``, ``Máx``, ``% >= 10.5``.
    """
    if columna not in df.columns:
        print(f"[AVISO] La columna '{columna}' no existe en el DataFrame.")
        return pd.DataFrame()

    if col_seccion not in df.columns:
        print(f"[AVISO] La columna de sección '{col_seccion}' no existe en el DataFrame.")
        # Calcular estadísticas globales sin agrupar
        serie = df[columna].dropna()
        fila = {
            "Sección": "Global",
            "N": len(serie),
            "Media": round(serie.mean(), 2),
            "Mediana": round(serie.median(), 2),
            "Std": round(serie.std(), 2),
            "Mín": round(serie.min(), 2),
            "Máx": round(serie.max(), 2),
            "% >= 10.5": round((serie >= 10.5).mean() * 100, 1),
        }
        return pd.DataFrame([fila])

    filas = []
    for seccion, grupo in df.groupby(col_seccion, dropna=True):
        serie = grupo[columna].dropna()
        if len(serie) == 0:
            continue
        filas.append({
            "Sección": seccion,
            "N": len(serie),
            "Media": round(serie.mean(), 2),
            "Mediana": round(serie.median(), 2),
            "Std": round(serie.std(), 2),
            "Mín": round(serie.min(), 2),
            "Máx": round(serie.max(), 2),
            "% >= 10.5": round((serie >= 10.5).mean() * 100, 1),
        })

    return pd.DataFrame(filas).sort_values("Sección").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Alumnos en riesgo
# ---------------------------------------------------------------------------

def alumnos_en_riesgo(
    df: pd.DataFrame,
    umbral: float = 10.5,
    col_nota: str = "NF",
    cols_mostrar: Optional[list[str]] = None,
) -> pd.DataFrame:
    """Identifica alumnos cuya nota proyectada está por debajo del umbral.

    Parameters
    ----------
    df:
        DataFrame con los datos de alumnos.
    umbral:
        Nota mínima aprobatoria (default: 10.5).
    col_nota:
        Columna de nota a evaluar (default: "NF").
    cols_mostrar:
        Columnas adicionales a mostrar en el reporte. Si es None,
        se muestran las columnas de identidad más la nota.

    Returns
    -------
    pd.DataFrame
        DataFrame con los alumnos en riesgo, ordenados por nota ascendente.
    """
    if col_nota not in df.columns:
        print(f"[AVISO] La columna '{col_nota}' no existe en el DataFrame.")
        return pd.DataFrame()

    if cols_mostrar is None:
        # Columnas de identidad disponibles
        posibles = ["Código", "Apellidos y nombres", "Apellidos", "Nombres",
                    "Correo", "Sección", col_nota]
        cols_mostrar = [c for c in posibles if c in df.columns]

    df_riesgo = (
        df[df[col_nota] < umbral][cols_mostrar]
        .sort_values(col_nota)
        .reset_index(drop=True)
    )

    total = df[col_nota].notna().sum()
    n_riesgo = len(df_riesgo)
    print(f"\n[RIESGO] Alumnos con {col_nota} < {umbral}: {n_riesgo}/{total} "
          f"({round(n_riesgo/total*100, 1) if total > 0 else 0}%)")

    return df_riesgo


# ---------------------------------------------------------------------------
# Resumen global del curso
# ---------------------------------------------------------------------------

def resumen_curso(
    df: pd.DataFrame,
    columnas: Optional[list[str]] = None,
) -> pd.DataFrame:
    """Calcula estadísticas globales del curso para las columnas especificadas.

    Parameters
    ----------
    df:
        DataFrame con los datos de alumnos.
    columnas:
        Lista de columnas a resumir. Si es None, se usan las columnas
        calculadas por el pipeline.

    Returns
    -------
    pd.DataFrame
        DataFrame con estadísticas descriptivas por columna.
    """
    if columnas is None:
        columnas_candidatas = [
            "T1", "T2", "T3", "T4", "T5", "T6",
            "EA1", "EA2", "EA3", "EA4", "EA5", "EA6",
            "PT1", "PT2", "PEA1", "PEA2",
            "PfEA1", "PfEA2", "TA1", "TA2",
            "EP", "EF", "NF",
        ]
        columnas = [c for c in columnas_candidatas if c in df.columns]

    if not columnas:
        print("[AVISO] No se encontraron columnas de evaluación para resumir.")
        return pd.DataFrame()

    filas = []
    for col in columnas:
        serie = df[col].dropna()
        if len(serie) == 0:
            continue
        filas.append({
            "Evaluación": col,
            "N": len(serie),
            "Media": round(serie.mean(), 2),
            "Mediana": round(serie.median(), 2),
            "Std": round(serie.std(), 2),
            "Mín": round(serie.min(), 2),
            "Máx": round(serie.max(), 2),
            "% >= 10.5": round((serie >= 10.5).mean() * 100, 1),
        })

    df_resumen = pd.DataFrame(filas)
    print("\n=== RESUMEN GLOBAL DEL CURSO ===")
    print(df_resumen.to_string(index=False))
    return df_resumen


# ---------------------------------------------------------------------------
# Comparación entre ciclos
# ---------------------------------------------------------------------------

def comparar_ciclos(
    df_ciclo1: pd.DataFrame,
    df_ciclo2: pd.DataFrame,
    evaluaciones: list[str],
    ciclo1_nombre: str = "Ciclo 1",
    ciclo2_nombre: str = "Ciclo 2",
) -> pd.DataFrame:
    """Compara las medias de evaluaciones entre dos ciclos académicos.

    Parameters
    ----------
    df_ciclo1:
        DataFrame del primer ciclo con las columnas de evaluaciones.
    df_ciclo2:
        DataFrame del segundo ciclo con las columnas de evaluaciones.
    evaluaciones:
        Lista de nombres de columnas a comparar (ej. ["EA1", "EA2", "EA3"]).
    ciclo1_nombre:
        Nombre descriptivo del primer ciclo (ej. "2025-2").
    ciclo2_nombre:
        Nombre descriptivo del segundo ciclo (ej. "2026-1").

    Returns
    -------
    pd.DataFrame
        DataFrame comparativo con columnas:
        ``Evaluación``, ``Media {ciclo1}``, ``N {ciclo1}``,
        ``Media {ciclo2}``, ``N {ciclo2}``, ``Diferencia``.
    """
    filas = []
    for eval_nombre in evaluaciones:
        col1 = df_ciclo1[eval_nombre].dropna() if eval_nombre in df_ciclo1.columns else pd.Series(dtype=float)
        col2 = df_ciclo2[eval_nombre].dropna() if eval_nombre in df_ciclo2.columns else pd.Series(dtype=float)

        media1 = round(col1.mean(), 2) if len(col1) > 0 else np.nan
        media2 = round(col2.mean(), 2) if len(col2) > 0 else np.nan
        diferencia = round(media2 - media1, 2) if pd.notna(media1) and pd.notna(media2) else np.nan

        filas.append({
            "Evaluación": eval_nombre,
            f"Media {ciclo1_nombre}": media1,
            f"N {ciclo1_nombre}": len(col1),
            f"Media {ciclo2_nombre}": media2,
            f"N {ciclo2_nombre}": len(col2),
            "Diferencia": diferencia,
        })

    return pd.DataFrame(filas)


# ---------------------------------------------------------------------------
# Gráfica de comparación entre ciclos
# ---------------------------------------------------------------------------

def grafica_comparacion_ciclos(
    df_comparacion: pd.DataFrame,
    ciclo1_nombre: str = "Ciclo 1",
    ciclo2_nombre: str = "Ciclo 2",
    guardar_en: Optional[str | Path] = None,
    figsize: tuple[int, int] = (12, 6),
) -> None:
    """Genera una gráfica de barras dobles comparando medias entre ciclos.

    Parameters
    ----------
    df_comparacion:
        DataFrame retornado por ``comparar_ciclos()``.
    ciclo1_nombre:
        Nombre del primer ciclo para la leyenda.
    ciclo2_nombre:
        Nombre del segundo ciclo para la leyenda.
    guardar_en:
        Ruta donde guardar la imagen (PNG). Si es None, solo muestra la gráfica.
    figsize:
        Tamaño de la figura en pulgadas (ancho, alto).
    """
    col_media1 = f"Media {ciclo1_nombre}"
    col_media2 = f"Media {ciclo2_nombre}"

    if col_media1 not in df_comparacion.columns or col_media2 not in df_comparacion.columns:
        print("[AVISO] Las columnas de media no coinciden con los nombres de ciclo proporcionados.")
        return

    evaluaciones = df_comparacion["Evaluación"].tolist()
    medias1 = df_comparacion[col_media1].tolist()
    medias2 = df_comparacion[col_media2].tolist()

    x = np.arange(len(evaluaciones))
    ancho = 0.35

    fig, ax = plt.subplots(figsize=figsize)

    barras1 = ax.bar(x - ancho / 2, medias1, ancho, label=ciclo1_nombre, color="#4C72B0", alpha=0.85)
    barras2 = ax.bar(x + ancho / 2, medias2, ancho, label=ciclo2_nombre, color="#DD8452", alpha=0.85)

    # Etiquetas de valor sobre cada barra
    for barra in barras1:
        altura = barra.get_height()
        if not np.isnan(altura):
            ax.annotate(f"{altura:.1f}",
                        xy=(barra.get_x() + barra.get_width() / 2, altura),
                        xytext=(0, 3), textcoords="offset points",
                        ha="center", va="bottom", fontsize=9)

    for barra in barras2:
        altura = barra.get_height()
        if not np.isnan(altura):
            ax.annotate(f"{altura:.1f}",
                        xy=(barra.get_x() + barra.get_width() / 2, altura),
                        xytext=(0, 3), textcoords="offset points",
                        ha="center", va="bottom", fontsize=9)

    ax.set_xlabel("Evaluación", fontsize=12)
    ax.set_ylabel("Media (sobre 20)", fontsize=12)
    ax.set_title(f"Comparación de medias: {ciclo1_nombre} vs {ciclo2_nombre}", fontsize=14)
    ax.set_xticks(x)
    ax.set_xticklabels(evaluaciones, rotation=45, ha="right")
    ax.set_ylim(0, 22)
    ax.axhline(y=10.5, color="red", linestyle="--", alpha=0.5, label="Mínimo aprobatorio (10.5)")
    ax.legend(fontsize=10)
    ax.grid(axis="y", alpha=0.3)

    plt.tight_layout()

    if guardar_en is not None:
        ruta = Path(guardar_en)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(ruta, dpi=150, bbox_inches="tight")
        print(f"[GRÁFICA] Guardada en: {ruta}")

    plt.show()
