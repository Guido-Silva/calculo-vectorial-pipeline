"""
merge.py — Módulo de unificación de fuentes del pipeline de Cálculo Vectorial UTEC.

Funciones para combinar el dashboard base de alumnos con las diferentes fuentes
de notas (Canvas, Gradescope), usando el código universitario como llave
primaria y el correo como fallback.
"""

from __future__ import annotations

import pandas as pd


def _nombres_temporales(
    columnas: list[str],
    columnas_existentes: set[str],
    prefijo: str,
) -> dict[str, str]:
    """Crea nombres temporales que no colisionen con el DataFrame base."""
    nombres: dict[str, str] = {}
    usados = set(columnas_existentes)
    for i, col in enumerate(columnas):
        candidato_base = f"__{prefijo}_{i}__"
        candidato = candidato_base
        j = 1
        while candidato in usados:
            candidato = f"{candidato_base}_{j}"
            j += 1
        nombres[col] = candidato
        usados.add(candidato)
    return nombres


def _aplicar_columnas_temporales(
    df: pd.DataFrame,
    nombres_tmp: dict[str, str],
    mask_filas: pd.Series | None = None,
) -> pd.DataFrame:
    """Copia valores temporales no nulos a las columnas canónicas."""
    for col, col_tmp in nombres_tmp.items():
        if col not in df.columns:
            df[col] = pd.NA

        valores_tmp_num = pd.to_numeric(df[col_tmp], errors="coerce")
        tmp_no_nulos = df[col_tmp].notna()
        fuente_es_numerica = bool(
            tmp_no_nulos.any() and valores_tmp_num[tmp_no_nulos].notna().all()
        )

        if fuente_es_numerica:
            df[col] = pd.to_numeric(
                df[col].astype("string").str.replace(",", ".", regex=False),
                errors="coerce",
            )
            df[col_tmp] = valores_tmp_num
        else:
            df[col] = df[col].astype("object")

        mask = df[col_tmp].notna()
        if mask_filas is not None:
            mask = mask & mask_filas

        df.loc[mask, col] = df.loc[mask, col_tmp]

    return df.drop(columns=list(nombres_tmp.values()))


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
    cols_disponibles = [c for c in columnas if c in df_fuente.columns]
    if not cols_disponibles:
        return df_base

    nombres_tmp = _nombres_temporales(
        cols_disponibles,
        set(df_base.columns) | set(df_fuente.columns),
        f"codigo{sufijo}",
    )
    df_fuente_sel = (
        df_fuente[["Código"] + cols_disponibles]
        .dropna(subset=["Código"])
        .drop_duplicates(subset=["Código"])
        .rename(columns=nombres_tmp)
    )

    resultado = df_base.merge(
        df_fuente_sel,
        on="Código",
        how="left",
    )
    return _aplicar_columnas_temporales(resultado, nombres_tmp)


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
    if "Código" in df_fuente.columns and "Código" in df_base.columns:
        nombres_codigo = _nombres_temporales(
            cols_disponibles,
            set(df_base.columns) | set(df_fuente.columns),
            f"codigo{sufijo}",
        )
        df_fuente_codigo = (
            df_fuente[["Código"] + cols_disponibles]
            .dropna(subset=["Código"])
            .drop_duplicates(subset=["Código"])
            .rename(columns=nombres_codigo)
        )
        df_merge1 = df_base.merge(
            df_fuente_codigo,
            on="Código",
            how="left",
        )
        cols_tmp_codigo = list(nombres_codigo.values())
        match_codigo = df_merge1[cols_tmp_codigo].notna().any(axis=1)
        df_merge1 = _aplicar_columnas_temporales(df_merge1, nombres_codigo)
    else:
        df_merge1 = df_base.copy()
        match_codigo = pd.Series(False, index=df_merge1.index)

    n_por_codigo = int(match_codigo.sum())
    sin_match = ~match_codigo

    # --- Paso 2: fallback por Correo ---
    match_correo = pd.Series(False, index=df_merge1.index)
    if "Correo" in df_fuente.columns and "Correo" in df_base.columns:
        nombres_correo = _nombres_temporales(
            cols_disponibles,
            set(df_merge1.columns) | set(df_fuente.columns),
            f"correo{sufijo}",
        )
        df_fuente_correo = (
            df_fuente[["Correo"] + cols_disponibles]
            .dropna(subset=["Correo"])
            .drop_duplicates(subset=["Correo"])
            .rename(columns=nombres_correo)
        )

        df_merge2 = df_merge1.merge(
            df_fuente_correo,
            on="Correo",
            how="left",
        )
        cols_tmp_correo = list(nombres_correo.values())
        match_correo = sin_match & df_merge2[cols_tmp_correo].notna().any(axis=1)

        # Para los alumnos sin match por Código, usar el valor del fallback
        df_resultado = _aplicar_columnas_temporales(
            df_merge2,
            nombres_correo,
            mask_filas=sin_match,
        )
    else:
        df_resultado = df_merge1

    # Calcular estadísticas de cobertura
    n_por_correo = int(match_correo.sum())
    n_sin_match = len(df_base) - n_por_codigo - n_por_correo
    total = len(df_base)

    if verbose:
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
