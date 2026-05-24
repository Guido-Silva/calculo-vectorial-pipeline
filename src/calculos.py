"""
calculos.py — Módulo de cálculo de notas del pipeline de Cálculo Vectorial UTEC.

Implementa todas las fórmulas del sistema de evaluación:
  - PT1, PT2: promedio de tareas por tramo
  - PEA1, PEA2: promedio de evaluaciones en aula (con y sin eliminación de mínimo)
  - PV1, PV2: promedio de videos de actividades previas
  - BPEA1, BPEA2: bonificaciones por actividades previas
  - PfEA1, PfEA2: promedio final de EAs con bonificación
  - TA1, TA2: evaluación continua por tramo
  - EP, EF: examen parcial y final (con cap en 20 y bonus simulacro)
  - NF: nota final

Reglas de redondeo:
  - Cada T y EA individual: redondeo académico al entero más cercano antes de calcular
    (.5 sube)
  - PT1, PT2, PEA1, PEA2, PfEA1, PfEA2: round a 2 decimales
  - T3 = T3A + T3B (T3A sobre 12, T3B sobre 8, suma = sobre 20)
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Utilidades internas
# ---------------------------------------------------------------------------

def _redondear_mitad_arriba(valor) -> float:
    """Redondea notas no negativas al entero más cercano, con .5 hacia arriba."""
    if pd.isna(valor):
        return np.nan
    try:
        numero = float(str(valor).strip().replace(",", "."))
    except ValueError:
        return np.nan
    return float(np.floor(numero + 0.5))


def _redondear_columna(df: pd.DataFrame, col: str) -> pd.Series:
    """Retorna la columna redondeada al entero más cercano.

    Si la columna no existe en el DataFrame, retorna una Serie de NaN.

    Parameters
    ----------
    df:
        DataFrame con los datos.
    col:
        Nombre de la columna a redondear.

    Returns
    -------
    pd.Series
        Serie con valores redondeados (o NaN si la columna no existe).
    """
    if col not in df.columns:
        return pd.Series(np.nan, index=df.index)
    return df[col].apply(_redondear_mitad_arriba)


def _promedio_fila(*series: pd.Series) -> pd.Series:
    """Calcula el promedio fila a fila. Si algún valor es NaN, el resultado es NaN.

    Esto asegura que si falta alguna evaluación requerida, el promedio
    no se calcule parcialmente (por ejemplo PT1 requiere T1, T2, T3 y T4).

    Parameters
    ----------
    *series:
        Series de pandas a promediar.

    Returns
    -------
    pd.Series
        Serie con el promedio por fila. NaN si algún componente es NaN.
    """
    df_tmp = pd.concat(series, axis=1)
    return df_tmp.mean(axis=1, skipna=False)


def _top_n_promedio(df_vals: pd.DataFrame, n: int) -> pd.Series:
    """Calcula el promedio de los ``n`` mejores valores por fila.

    Si alguna celda es NaN, se excluye del conteo. Si hay menos de
    ``n`` valores no-NaN disponibles, se promedian los que haya.

    Parameters
    ----------
    df_vals:
        DataFrame donde cada columna es una evaluación y cada fila es un alumno.
    n:
        Número de mejores valores a considerar.

    Returns
    -------
    pd.Series
        Promedio de los n mejores por fila. NaN si no hay valores disponibles.
    """
    def top_n_fila(fila):
        valores = fila.dropna().sort_values(ascending=False)
        if len(valores) == 0:
            return np.nan
        return valores.iloc[:n].mean()

    return df_vals.apply(top_n_fila, axis=1)


# ---------------------------------------------------------------------------
# Tareas semanales
# ---------------------------------------------------------------------------

def calcular_PT1(df: pd.DataFrame) -> pd.Series:
    """Calcula el Promedio de Tareas del tramo 1 (PT1).

    Fórmula::

        T3 = T3A + T3B  (antes de redondear)
        PT1 = mean(round(T1), round(T2), round(T3), round(T4))  → 2 decimales

    Parameters
    ----------
    df:
        DataFrame con columnas T1, T2, T3A, T3B, T4.

    Returns
    -------
    pd.Series
        PT1 redondeado a 2 decimales. NaN si alguna tarea falta.
    """
    # T3 = T3A + T3B antes de redondear (T3A sobre 12, T3B sobre 8)
    if "T3A" in df.columns and "T3B" in df.columns:
        T3 = df["T3A"].add(df["T3B"], fill_value=np.nan)
    elif "T3" in df.columns:
        T3 = df["T3"]
    else:
        T3 = pd.Series(np.nan, index=df.index)

    T1 = _redondear_columna(df, "T1")
    T2 = _redondear_columna(df, "T2")
    T3r = T3.apply(_redondear_mitad_arriba)
    T4 = _redondear_columna(df, "T4")

    resultado = _promedio_fila(T1, T2, T3r, T4)
    return resultado.round(2)


def calcular_PT2(df: pd.DataFrame) -> pd.Series:
    """Calcula el Promedio de Tareas del tramo 2 (PT2).

    Fórmula::

        PT2 = mean(round(T5), round(T6))  → 2 decimales

    Parameters
    ----------
    df:
        DataFrame con columnas T5, T6.

    Returns
    -------
    pd.Series
        PT2 redondeado a 2 decimales. NaN si alguna tarea falta.
    """
    T5 = _redondear_columna(df, "T5")
    T6 = _redondear_columna(df, "T6")
    return _promedio_fila(T5, T6).round(2)


# ---------------------------------------------------------------------------
# Evaluaciones en Aula
# ---------------------------------------------------------------------------

def calcular_PEA1(df: pd.DataFrame) -> pd.Series:
    """Calcula el Promedio de EA del tramo 1 (PEA1).

    Fórmula::

        PEA1 = mean de top 2 de {round(EA1), round(EA2), round(EA3)}
        (se elimina el mínimo si las 3 están disponibles)
        → 2 decimales

    Parameters
    ----------
    df:
        DataFrame con columnas EA1, EA2, EA3.

    Returns
    -------
    pd.Series
        PEA1 redondeado a 2 decimales.
    """
    EA1 = _redondear_columna(df, "EA1")
    EA2 = _redondear_columna(df, "EA2")
    EA3 = _redondear_columna(df, "EA3")
    df_eas = pd.concat([EA1, EA2, EA3], axis=1)
    df_eas.columns = ["EA1", "EA2", "EA3"]
    return _top_n_promedio(df_eas, n=2).round(2)


def calcular_PEA2(df: pd.DataFrame) -> pd.Series:
    """Calcula el Promedio de EA del tramo 2 (PEA2).

    Fórmula::

        PEA2 = mean(round(EA4), round(EA5), round(EA6))  → 2 decimales
        (sin eliminar ninguna)

    Parameters
    ----------
    df:
        DataFrame con columnas EA4, EA5, EA6.

    Returns
    -------
    pd.Series
        PEA2 redondeado a 2 decimales.
    """
    EA4 = _redondear_columna(df, "EA4")
    EA5 = _redondear_columna(df, "EA5")
    EA6 = _redondear_columna(df, "EA6")
    return _promedio_fila(EA4, EA5, EA6).round(2)


# ---------------------------------------------------------------------------
# Actividades Previas (videos)
# ---------------------------------------------------------------------------

def calcular_PV1(df: pd.DataFrame, cols_ap_bpea1: list[str]) -> pd.Series:
    """Calcula el Promedio de Videos del tramo 1 (PV1).

    Toma el promedio de los mejores 11 de 12 videos (AP1V1...AP6V2).
    Se elimina el mínimo si los 12 están disponibles.

    Parameters
    ----------
    df:
        DataFrame con las columnas de videos de AP (tramo 1).
    cols_ap_bpea1:
        Lista de 12 nombres de columnas de videos (ej. AP1V1, AP1V2, ..., AP6V2).

    Returns
    -------
    pd.Series
        PV1 (promedio de top 11). NaN si no hay ningún video disponible.
    """
    cols_presentes = [c for c in cols_ap_bpea1 if c in df.columns]
    if not cols_presentes:
        return pd.Series(np.nan, index=df.index)
    df_videos = df[cols_presentes].copy()
    return _top_n_promedio(df_videos, n=11)


def calcular_PV2(df: pd.DataFrame, cols_ap_bpea2: list[str]) -> pd.Series:
    """Calcula el Promedio de Videos del tramo 2 (PV2).

    Toma el promedio de los 5 videos de las semanas 9,10,11,13:
    AP7V1, AP7V2, AP8V1, AP9V1, AP10V1.
    Sin eliminar ninguno. Se promedian los videos disponibles (skipna=True)
    para no penalizar a alumnos que aún no tienen todos los videos registrados.

    Parameters
    ----------
    df:
        DataFrame con las columnas de videos de AP (tramo 2).
    cols_ap_bpea2:
        Lista de 5 nombres de columnas de videos
        (ej. ['AP7V1', 'AP7V2', 'AP8V1', 'AP9V1', 'AP10V1']).

    Returns
    -------
    pd.Series
        PV2 (promedio de los videos disponibles). NaN si no hay ningún video disponible.
    """
    cols_presentes = [c for c in cols_ap_bpea2 if c in df.columns]
    if not cols_presentes:
        return pd.Series(np.nan, index=df.index)
    df_videos = df[cols_presentes].copy()
    # skipna=True: si falta algún video (aún no disponible), se promedian los existentes
    resultado = df_videos.mean(axis=1, skipna=True)
    # Retornar NaN solo si TODOS los videos son NaN
    todo_nan = df_videos.isna().all(axis=1)
    resultado[todo_nan] = np.nan
    return resultado


# ---------------------------------------------------------------------------
# Bonificaciones de Actividades Previas
# ---------------------------------------------------------------------------

def _calcular_bonus_pv(pv_serie: pd.Series) -> pd.Series:
    """Calcula el bonus según el valor de PV (lógica común para BPEA1 y BPEA2).

    Reglas::

        PV >= 16  → bonus = 2
        11 <= PV < 16 → bonus = 1
        PV < 11   → bonus = 0
        NaN       → NaN

    Parameters
    ----------
    pv_serie:
        Serie con los valores de PV1 o PV2.

    Returns
    -------
    pd.Series
        Bonus (0, 1, 2 o NaN).
    """
    def bonus_fila(pv):
        if pd.isna(pv):
            return np.nan
        if pv >= 16:
            return 2
        if pv >= 11:
            return 1
        return 0

    return pv_serie.apply(bonus_fila)


def calcular_BPEA1_provisional(df: pd.DataFrame) -> pd.Series:
    """Calcula BPEA1 provisional (sin verificar condición EP >= 8).

    Se llama "provisional" porque la condición ``EP >= 8`` requiere la nota
    del Examen Parcial, que puede no estar disponible aún.

    Reglas::

        PV1 >= 16  → BPEA1_prov = 2
        11 <= PV1 < 16 → BPEA1_prov = 1
        PV1 < 11   → BPEA1_prov = 0

    Parameters
    ----------
    df:
        DataFrame con la columna ``PV1``.

    Returns
    -------
    pd.Series
        BPEA1 provisional.
    """
    if "PV1" not in df.columns:
        return pd.Series(np.nan, index=df.index)
    return _calcular_bonus_pv(df["PV1"])


def calcular_BPEA1_final(df: pd.DataFrame) -> pd.Series:
    """Calcula BPEA1 final aplicando la condición EP >= 8.

    Si el alumno tiene EP < 8, su BPEA1 final es 0.
    Solo puede calcularse cuando la nota de EP está disponible.

    Parameters
    ----------
    df:
        DataFrame con columnas ``BPEA1_prov`` y ``EP``.

    Returns
    -------
    pd.Series
        BPEA1 final (0, 1 o 2). NaN si PV1 o EP son NaN.
    """
    if "BPEA1_prov" not in df.columns:
        return pd.Series(np.nan, index=df.index)
    if "EP" not in df.columns:
        return pd.Series(np.nan, index=df.index)

    bpea1_final = df["BPEA1_prov"].copy()
    # Si EP < 8, anular el bonus
    mask_sin_bonus = df["EP"].notna() & (df["EP"] < 8)
    bpea1_final[mask_sin_bonus] = 0
    return bpea1_final


def calcular_BPEA2(df: pd.DataFrame) -> pd.Series:
    """Calcula BPEA2 con la condición RC2 >= 15.

    Si el alumno tiene RC2 < 15, su BPEA2 es 0.

    Reglas::

        Si RC2 < 15 → BPEA2 = 0
        Si RC2 >= 15:
            PV2 >= 16  → BPEA2 = 2
            11 <= PV2 < 16 → BPEA2 = 1
            PV2 < 11   → BPEA2 = 0

    Parameters
    ----------
    df:
        DataFrame con columnas ``PV2`` y ``RC2``.

    Returns
    -------
    pd.Series
        BPEA2 (0, 1 o 2). NaN si PV2 es NaN.
    """
    if "PV2" not in df.columns:
        return pd.Series(np.nan, index=df.index)

    bonus_base = _calcular_bonus_pv(df["PV2"])

    if "RC2" in df.columns:
        # Si RC2 está disponible y es < 15, anular el bonus
        mask_sin_bonus = df["RC2"].notna() & (df["RC2"] < 15)
        bonus_base[mask_sin_bonus] = 0

    return bonus_base


# ---------------------------------------------------------------------------
# Promedios finales de EA con bonificación
# ---------------------------------------------------------------------------

def calcular_PfEA1(df: pd.DataFrame) -> pd.Series:
    """Calcula el Promedio final de EA1 con bonificación (PfEA1).

    Fórmula::

        PfEA1 = round(PEA1 + BPEA1, 2)

    Usa BPEA1_final si está disponible, sino BPEA1_prov.

    Parameters
    ----------
    df:
        DataFrame con columnas ``PEA1`` y (``BPEA1_final`` o ``BPEA1_prov``).

    Returns
    -------
    pd.Series
        PfEA1 redondeado a 2 decimales.
    """
    if "PEA1" not in df.columns:
        return pd.Series(np.nan, index=df.index)

    if "BPEA1_final" in df.columns:
        bpea1 = df["BPEA1_final"]
    elif "BPEA1_prov" in df.columns:
        bpea1 = df["BPEA1_prov"]
    else:
        bpea1 = pd.Series(0.0, index=df.index)

    return (df["PEA1"] + bpea1.fillna(0)).round(2)


def calcular_PfEA2(df: pd.DataFrame) -> pd.Series:
    """Calcula el Promedio final de EA2 con bonificación (PfEA2).

    Fórmula::

        PfEA2 = round(PEA2 + BPEA2, 2)

    Parameters
    ----------
    df:
        DataFrame con columnas ``PEA2`` y ``BPEA2``.

    Returns
    -------
    pd.Series
        PfEA2 redondeado a 2 decimales.
    """
    if "PEA2" not in df.columns:
        return pd.Series(np.nan, index=df.index)

    if "BPEA2" in df.columns:
        bpea2 = df["BPEA2"]
    else:
        bpea2 = pd.Series(0.0, index=df.index)

    return (df["PEA2"] + bpea2.fillna(0)).round(2)


# ---------------------------------------------------------------------------
# Exámenes (con cap en 20 y bonus simulacro)
# ---------------------------------------------------------------------------

def _calcular_bonus_simulacro(simulacro_serie: pd.Series) -> pd.Series:
    """Calcula el bonus de simulacro (SExP o SExF).

    Reglas::

        simulacro >= 18         → bonus = 2
        14 <= simulacro <= 17   → bonus = 1
        simulacro < 14 o NaN   → bonus = 0

    Parameters
    ----------
    simulacro_serie:
        Serie con las notas del simulacro.

    Returns
    -------
    pd.Series
        Bonus (0, 1 o 2).
    """
    def bonus_sim(s):
        if pd.isna(s):
            return 0
        if s >= 18:
            return 2
        if s >= 14:
            return 1
        return 0

    return simulacro_serie.apply(bonus_sim)


def calcular_EP(df: pd.DataFrame) -> pd.Series:
    """Calcula la nota del Examen Parcial (EP) con cap y bonus simulacro.

    Fórmula::

        ExP_norm = min(ExP_raw, 20)   ← cap simple, no escala lineal
        SExP = 0, 1 ó 2 puntos según nota del simulacro
        EP = min(ExP_norm + SExP, 20) ← cap final en 20

    Parameters
    ----------
    df:
        DataFrame con columnas ``ExP`` y opcionalmente ``SExP``.

    Returns
    -------
    pd.Series
        Nota del Examen Parcial (0-20). NaN si ExP es NaN.
    """
    if "ExP" not in df.columns:
        return pd.Series(np.nan, index=df.index)

    exp_norm = df["ExP"].apply(lambda x: min(x, 20) if pd.notna(x) else np.nan)

    if "SExP" in df.columns:
        bonus = _calcular_bonus_simulacro(df["SExP"])
    else:
        bonus = pd.Series(0, index=df.index)

    ep = exp_norm + bonus
    return ep.apply(lambda x: min(x, 20) if pd.notna(x) else np.nan)


def calcular_EF(df: pd.DataFrame) -> pd.Series:
    """Calcula la nota del Examen Final (EF) con cap y bonus simulacro.

    Fórmula::

        ExF_norm = min(ExF_raw, 20)
        SExF = 0, 1 ó 2 puntos según nota del simulacro
        EF = min(ExF_norm + SExF, 20)

    Parameters
    ----------
    df:
        DataFrame con columnas ``ExF`` y opcionalmente ``SExF``.

    Returns
    -------
    pd.Series
        Nota del Examen Final (0-20). NaN si ExF es NaN.
    """
    if "ExF" not in df.columns:
        return pd.Series(np.nan, index=df.index)

    exf_norm = df["ExF"].apply(lambda x: min(x, 20) if pd.notna(x) else np.nan)

    if "SExF" in df.columns:
        bonus = _calcular_bonus_simulacro(df["SExF"])
    else:
        bonus = pd.Series(0, index=df.index)

    ef = exf_norm + bonus
    return ef.apply(lambda x: min(x, 20) if pd.notna(x) else np.nan)


# ---------------------------------------------------------------------------
# Evaluación continua por tramo
# ---------------------------------------------------------------------------

def calcular_TA1(df: pd.DataFrame) -> pd.Series:
    """Calcula la Evaluación Continua del tramo 1 (TA1).

    Fórmula::

        TA1 = 0.25*PT1 + 0.70*PfEA1 + 0.05*RC1

    Parameters
    ----------
    df:
        DataFrame con columnas ``PT1``, ``PfEA1`` y ``RC1``.

    Returns
    -------
    pd.Series
        TA1 redondeada a 2 decimales. NaN si algún componente falta.
    """
    requeridos = ["PT1", "PfEA1", "RC1"]
    for col in requeridos:
        if col not in df.columns:
            return pd.Series(np.nan, index=df.index)

    ta1 = (
        0.25 * df["PT1"]
        + 0.70 * df["PfEA1"]
        + 0.05 * df["RC1"]
    )
    return ta1.round(2)


def calcular_TA2(df: pd.DataFrame) -> pd.Series:
    """Calcula la Evaluación Continua del tramo 2 (TA2).

    Fórmula::

        TA2 = 0.10*PT2 + 0.70*PfEA2 + 0.20*RC2

    Parameters
    ----------
    df:
        DataFrame con columnas ``PT2``, ``PfEA2`` y ``RC2``.

    Returns
    -------
    pd.Series
        TA2 redondeada a 2 decimales. NaN si algún componente falta.
    """
    requeridos = ["PT2", "PfEA2", "RC2"]
    for col in requeridos:
        if col not in df.columns:
            return pd.Series(np.nan, index=df.index)

    ta2 = (
        0.10 * df["PT2"]
        + 0.70 * df["PfEA2"]
        + 0.20 * df["RC2"]
    )
    return ta2.round(2)


# ---------------------------------------------------------------------------
# Nota Final
# ---------------------------------------------------------------------------

def calcular_NF(df: pd.DataFrame) -> pd.Series:
    """Calcula la Nota Final (NF).

    Fórmula::

        NF = 0.25*TA1 + 0.25*TA2 + 0.20*EP + 0.30*EF

    Parameters
    ----------
    df:
        DataFrame con columnas ``TA1``, ``TA2``, ``EP``, ``EF``.

    Returns
    -------
    pd.Series
        NF redondeada a 2 decimales. NaN si algún componente falta.
    """
    requeridos = ["TA1", "TA2", "EP", "EF"]
    for col in requeridos:
        if col not in df.columns:
            return pd.Series(np.nan, index=df.index)

    nf = (
        0.25 * df["TA1"]
        + 0.25 * df["TA2"]
        + 0.20 * df["EP"]
        + 0.30 * df["EF"]
    )
    return nf.round(2)


# ---------------------------------------------------------------------------
# Función principal de cálculo
# ---------------------------------------------------------------------------

def ejecutar_calculos(
    df: pd.DataFrame,
    config: dict,
    cols_ap_bpea1: list[str] | None = None,
    cols_ap_bpea2: list[str] | None = None,
) -> pd.DataFrame:
    """Ejecuta todos los cálculos del pipeline en el orden correcto.

    Si una columna requerida es NaN, el resultado también es NaN (sin error).
    Agrega las columnas calculadas al DataFrame sin modificar las originales.

    Parameters
    ----------
    df:
        DataFrame con todos los datos mergeados (notas crudas de evaluaciones).
    config:
        Configuración YAML del ciclo con los pesos y parámetros.
    cols_ap_bpea1:
        Lista de columnas de videos del tramo 1 (AP1V1...AP6V2).
        Si es None, se usan los nombres por defecto.
    cols_ap_bpea2:
        Lista de columnas de videos del tramo 2 (AP7V1, AP7V2, AP8V1, AP9V1, AP10V1).
        Si es None, se usan los nombres por defecto.

    Returns
    -------
    pd.DataFrame
        DataFrame con todas las columnas calculadas agregadas.

    Notes
    -----
    Orden de cálculo:

    1. PT1, PT2
    2. PEA1, PEA2
    3. PV1, PV2 → BPEA1_prov, BPEA2
    4. EP (para BPEA1_final)
    5. BPEA1_final
    6. PfEA1, PfEA2
    7. TA1, TA2
    8. EF
    9. NF
    """
    resultado = df.copy()

    # Columnas de videos por defecto
    if cols_ap_bpea1 is None:
        cols_ap_bpea1 = [
            "AP1V1", "AP1V2",
            "AP2V1", "AP2V2",
            "AP3V1", "AP3V2",
            "AP4V1", "AP4V2",
            "AP5V1", "AP5V2",
            "AP6V1", "AP6V2",
        ]
    if cols_ap_bpea2 is None:
        # Semana 9 tiene 2 videos (AP7V1, AP7V2), resto 1 video cada una
        cols_ap_bpea2 = ["AP7V1", "AP7V2", "AP8V1", "AP9V1", "AP10V1"]

    # 1. Promedios de tareas
    resultado["PT1"] = calcular_PT1(resultado)
    resultado["PT2"] = calcular_PT2(resultado)

    # 2. Promedios de EAs
    resultado["PEA1"] = calcular_PEA1(resultado)
    resultado["PEA2"] = calcular_PEA2(resultado)

    # 3. Videos de actividades previas
    resultado["PV1"] = calcular_PV1(resultado, cols_ap_bpea1)
    resultado["PV2"] = calcular_PV2(resultado, cols_ap_bpea2)

    # 4. Bonificaciones provisionales
    resultado["BPEA1_prov"] = calcular_BPEA1_provisional(resultado)
    resultado["BPEA2"] = calcular_BPEA2(resultado)

    # 5. Examen Parcial (necesario para BPEA1_final)
    # Conservar notas crudas de ExP y SExP
    if "ExP" in resultado.columns:
        resultado["ExP_raw"] = resultado["ExP"]
    if "SExP" in resultado.columns:
        resultado["SExP_raw"] = resultado["SExP"]

    # Calcular ExP normalizada (cap en 20)
    if "ExP" in resultado.columns:
        resultado["ExP"] = resultado["ExP"].apply(lambda x: min(x, 20) if pd.notna(x) else np.nan)

    # Calcular bonus SExP según reglas
    if "SExP_raw" in resultado.columns:
        def bonus_simulacro(val):
            if pd.isna(val):
                return np.nan  # Deja celda vacía si no se presentó
            if val >= 18:
                return 2
            if val >= 14:
                return 1
            return 0
        resultado["SExP_bonus"] = resultado["SExP_raw"].apply(bonus_simulacro)
    else:
        resultado["SExP_bonus"] = 0

    # EP final: ExP normalizada + bonus, cap en 20
    if "ExP" in resultado.columns:
        resultado["EP"] = (resultado["ExP"] + resultado["SExP_bonus"]).apply(lambda x: min(x, 20) if pd.notna(x) else np.nan)
    else:
        resultado["EP"] = np.nan

    # 6. BPEA1 final con condición EP >= 8
    resultado["BPEA1_final"] = calcular_BPEA1_final(resultado)

    # 7. Promedios finales de EA con bonificación
    resultado["PfEA1"] = calcular_PfEA1(resultado)
    resultado["PfEA2"] = calcular_PfEA2(resultado)

    # 8. Evaluación continua por tramo
    resultado["TA1"] = calcular_TA1(resultado)
    resultado["TA2"] = calcular_TA2(resultado)

    # 9. Examen Final
    resultado["EF"] = calcular_EF(resultado)

    # 10. Nota Final
    resultado["NF"] = calcular_NF(resultado)

    print("\n[CÁLCULOS] Columnas calculadas:")
    cols_calculadas = [
        "PT1", "PT2", "PEA1", "PEA2", "PV1", "PV2",
        "BPEA1_prov", "BPEA1_final", "BPEA2",
        "PfEA1", "PfEA2", "TA1", "TA2", "EP", "EF", "NF",
    ]
    for col in cols_calculadas:
        if col in resultado.columns:
            n_validos = resultado[col].notna().sum()
            print(f"  {col}: {n_validos}/{len(resultado)} alumnos con valor")

    return resultado
