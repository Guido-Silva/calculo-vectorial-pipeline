"""
merge.py — Módulo de unificación de fuentes del pipeline de Cálculo Vectorial UTEC.

Funciones para combinar el dashboard base de alumnos con las diferentes fuentes
de notas (Canvas, Gradescope), usando el código universitario como llave
primaria y el correo como fallback.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd


# ---------------------------------------------------------------------------
# Merge básico
# ---------------------------------------------------------------------------

def merge_por_codigo(
    df_base: pd.DataFrame,
    df_fuente: pd.DataFrame,
    columnas: list[str],
    sufijo: str = "_fuente",
) -> pd.DataFrame:
    """Realiza un merge entre el dashboard base y una fuente, usando el Código.

    Siempre es un left join para no perder alumnos del dashboard.

    Parameters
    ----------
    df_base:
        DataFrame base (dashboard de Notas) con todos los alumnos del ciclo.
    df_fuente:
        DataFrame de la fuente (Canvas o Gradescope) con la columna ``Código``.
    columnas:
        Lista de columnas de ``df_fuente`` a agregar al ``df_base``.
    sufijo:
        Sufijo para columnas en conflicto (default: ``"_fuente"``).

    Returns
    -------
    pd.DataFrame
        df_base enriquecido con las columnas de la fuente.
    """
    columnas_merge = ["Código"] + [c for c in columnas if c in df_fuente.columns]
    df_fuente_sel = df_fuente[columnas_merge].copy()

    resultado = df_base.merge(
        df_fuente_sel,
        on="Código",
        how="left",
        suffixes=("", sufijo),
    )
    return resultado


# ---------------------------------------------------------------------------
# Merge con fallback por Correo
# ---------------------------------------------------------------------------

def merge_con_fallback(
    df_base: pd.DataFrame,
    df_fuente: pd.DataFrame,
    columnas: list[str],
    sufijo: str = "_fuente",
    verbose: bool = True,
) -> pd.DataFrame:
    """Merge por Código con fallback por Correo para alumnos sin match.

    Para cada alumno del dashboard:
    1. Intenta hacer match por ``Código``.
    2. Si no matcheó (las columnas quedan NaN), intenta match por ``Correo``.
    3. Registra el resultado de cada método.

    Parameters
    ----------
    df_base:
        DataFrame base con todos los alumnos. Debe tener columnas
        ``Código`` y ``Correo``.
    df_fuente:
        DataFrame de la fuente. Debe tener columnas ``Código`` y/o ``Correo``,
        más las columnas de evaluación.
    columnas:
        Lista de columnas de evaluación a traspasar desde ``df_fuente``.
    sufijo:
        Sufijo para columnas en conflicto.
    verbose:
        Si True, imprime resumen del merge.

    Returns
    -------
    pd.DataFrame
        df_base enriquecido. Nunca pierde filas (left join).
    """
    # Filtrar columnas que realmente existen en la fuente
    cols_disponibles = [c for c in columnas if c in df_fuente.columns]
    if not cols_disponibles:
        if verbose:
            print(f"[AVISO] Ninguna de las columnas {columnas} existe en la fuente.")
        return df_base

    # --- Paso 1: merge por Código ---
    cols_fuente_codigo = ["Código"] + cols_disponibles
    df_merge1 = df_base.merge(
        df_fuente[cols_fuente_codigo].drop_duplicates(subset=["Código"]),
        on="Código",
        how="left",
        suffixes=("", sufijo),
    )

    # Identificar alumnos que NO matchearon por Código
    # (tienen NaN en TODAS las columnas que queríamos agregar)
    sin_match = df_merge1[cols_disponibles].isna().all(axis=1)
    n_por_codigo = (~sin_match).sum()

    # --- Paso 2: fallback por Correo ---
    if "Correo" in df_fuente.columns and "Correo" in df_base.columns:
        cols_fuente_correo = ["Correo"] + cols_disponibles
        df_fuente_correo = (
            df_fuente[cols_fuente_correo]
            .drop_duplicates(subset=["Correo"])
            .rename(columns={c: f"{c}_fallback" for c in cols_disponibles})
        )

        df_merge2 = df_merge1.merge(
            df_fuente_correo,
            on="Correo",
            how="left",
            suffixes=("", "_fb"),
        )

        # Para los alumnos sin match por Código, usar el valor del fallback
        for col in cols_disponibles:
            col_fb = f"{col}_fallback"
            if col_fb in df_merge2.columns:
                # Solo reemplazar donde había NaN Y hay valor en el fallback
                mask_reemplazar = sin_match & df_merge2[col_fb].notna()
                df_merge2.loc[mask_reemplazar, col] = df_merge2.loc[mask_reemplazar, col_fb]
                df_merge2 = df_merge2.drop(columns=[col_fb])

        df_resultado = df_merge2
    else:
        df_resultado = df_merge1

    # Calcular estadísticas de cobertura
    sin_match_final = df_resultado[cols_disponibles].isna().all(axis=1)
    n_por_correo = (~sin_match_final).sum() - n_por_codigo
    n_sin_match = sin_match_final.sum()
    total = len(df_base)

    if verbose:
        col_repr = cols_disponibles[0] if cols_disponibles else "?"
        print(f"\n[MERGE] Columnas: {cols_disponibles}")
        print(f"  Total alumnos en base : {total}")
        print(f"  Match por Código      : {n_por_codigo}")
        print(f"  Match por Correo      : {n_por_correo}")
        print(f"  Sin match             : {n_sin_match}")

    return df_resultado


# ---------------------------------------------------------------------------
# Merge de múltiples fuentes
# ---------------------------------------------------------------------------

def merge_todas_fuentes(
    df_base: pd.DataFrame,
    fuentes_dict: dict[str, dict],
    verbose: bool = True,
) -> pd.DataFrame:
    """Aplica merge_con_fallback para cada fuente en el diccionario.

    Parameters
    ----------
    df_base:
        DataFrame base con todos los alumnos del ciclo.
    fuentes_dict:
        Diccionario con la estructura::

            {
                "nombre_fuente": {
                    "df": pd.DataFrame,
                    "columnas": ["EA1"],
                    "sufijo": "_gs",  # opcional
                },
                ...
            }
    verbose:
        Si True, imprime resumen de cada merge.

    Returns
    -------
    pd.DataFrame
        df_base enriquecido con todas las fuentes.
    """
    df_resultado = df_base.copy()

    for nombre, info in fuentes_dict.items():
        df_fuente = info.get("df")
        columnas = info.get("columnas", [])
        sufijo = info.get("sufijo", "_fuente")

        if df_fuente is None or df_fuente.empty:
            if verbose:
                print(f"[AVISO] Fuente '{nombre}' está vacía o es None. Se omite.")
            continue

        if verbose:
            print(f"\n--- Mergeando fuente: {nombre} ---")

        df_resultado = merge_con_fallback(
            df_resultado, df_fuente, columnas=columnas, sufijo=sufijo, verbose=verbose
        )

    return df_resultado


# ---------------------------------------------------------------------------
# Reporte de cobertura
# ---------------------------------------------------------------------------

def reporte_merge(df_resultado: pd.DataFrame) -> pd.DataFrame:
    """Imprime y retorna un resumen de cobertura de datos por columna de evaluación.

    Parameters
    ----------
    df_resultado:
        DataFrame resultado del merge con todas las columnas de evaluación.

    Returns
    -------
    pd.DataFrame
        DataFrame con columnas: ``Evaluación``, ``Con datos``, ``Sin datos (NaN)``,
        ``Cobertura (%)``.
    """
    # Columnas que NO son evaluaciones
    cols_base = {"Código", "Correo", "Sección", "Apellidos y nombres",
                 "Apellidos", "Nombres", "DNI", "Carrera"}
    cols_eval = [c for c in df_resultado.columns if c not in cols_base]

    total = len(df_resultado)
    filas = []

    for col in cols_eval:
        con_datos = df_resultado[col].notna().sum()
        sin_datos = total - con_datos
        cobertura = round(con_datos / total * 100, 1) if total > 0 else 0.0
        filas.append({
            "Evaluación": col,
            "Con datos": con_datos,
            "Sin datos (NaN)": sin_datos,
            "Cobertura (%)": cobertura,
        })

    df_reporte = pd.DataFrame(filas)
    print("\n=== REPORTE DE COBERTURA ===")
    print(df_reporte.to_string(index=False))
    return df_reporte
