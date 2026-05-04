"""
ingesta.py — Módulo de carga de datos del pipeline de Cálculo Vectorial UTEC.

Funciones para cargar y limpiar CSVs provenientes de Canvas y Gradescope,
manejando encodings especiales (Latin-1/UTF-8), decimales con coma,
y la estructura particular de cada plataforma.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import chardet
import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Utilidades internas
# ---------------------------------------------------------------------------

def detectar_encoding(path: str | Path) -> str:
    """Detecta el encoding de un archivo usando chardet.

    Parameters
    ----------
    path:
        Ruta al archivo a analizar.

    Returns
    -------
    str
        Nombre del encoding detectado (ej. 'utf-8', 'latin-1').
    """
    with open(path, "rb") as f:
        resultado = chardet.detect(f.read())
    return resultado.get("encoding", "utf-8") or "utf-8"


def limpiar_decimal(valor) -> Optional[float]:
    """Convierte un valor con coma decimal al tipo float.

    Canvas exporta los decimales con coma dentro de comillas, por ejemplo:
    ``"20,00"`` → ``20.0``, ``"15,50"`` → ``15.5``.

    Parameters
    ----------
    valor:
        Valor a convertir. Puede ser str, int, float o NaN.

    Returns
    -------
    float o None
        El valor numérico, o None si no se puede convertir.
    """
    if pd.isna(valor):
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    # Reemplazar coma decimal por punto
    limpio = str(valor).strip().replace(",", ".")
    try:
        return float(limpio)
    except ValueError:
        return None


def mapear_seccion_gradescope(seccion_str: str) -> Optional[int]:
    """Extrae el número de sección del string de Gradescope.

    Gradescope usa el formato:
    ``"clculo-vectorial-cc1104---teora---12"`` → ``12``

    Parameters
    ----------
    seccion_str:
        String de sección tal como aparece en la columna ``Sections``
        de los CSVs de Gradescope.

    Returns
    -------
    int o None
        Número de sección, o None si no se puede extraer.
    """
    if pd.isna(seccion_str) or not isinstance(seccion_str, str):
        return None
    # Buscar el número al final del string (posiblemente separado por guiones)
    match = re.search(r"---(\d+)$", seccion_str.strip())
    if match:
        return int(match.group(1))
    # Fallback: buscar el último grupo de dígitos
    match = re.search(r"(\d+)$", seccion_str.strip())
    if match:
        return int(match.group(1))
    return None


def _extraer_seccion_canvas(seccion_str: str) -> Optional[int]:
    """Extrae el número de sección del string de Canvas.

    Canvas usa el formato (con posibles caracteres corruptos por encoding):
    ``"Cálculo Vectorial (CC1104) - Teoría - 2"`` → ``2``
    ``"CÃ¡lculo Vectorial (CC1104) - TeorÃa - 2"`` → ``2``

    Parameters
    ----------
    seccion_str:
        String de sección tal como aparece en la columna ``Section``
        de los CSVs de Canvas.

    Returns
    -------
    int o None
        Número de sección, o None si no se puede extraer.
    """
    if pd.isna(seccion_str) or not isinstance(seccion_str, str):
        return None
    # Buscar el número al final, precedido por " - "
    match = re.search(r"-\s*(\d+)\s*$", seccion_str.strip())
    if match:
        return int(match.group(1))
    return None


# ---------------------------------------------------------------------------
# Carga de Canvas
# ---------------------------------------------------------------------------

def load_canvas_csv(path: str | Path, ciclo_config: Optional[dict] = None) -> pd.DataFrame:
    """Carga un CSV exportado de Canvas y lo limpia.

    Pasos que realiza:
    1. Detecta el encoding automáticamente (Latin-1 o UTF-8).
    2. Lee el CSV con separador por coma.
    3. Elimina la fila "Points Possible" (segunda fila del CSV de Canvas).
    4. Convierte decimales con coma a punto (formato ``"20,00"``).
    5. Extrae ``Código`` desde ``SIS User ID`` y ``Correo`` desde ``SIS Login ID``.
    6. Extrae ``Sección`` desde la columna ``Section``.
    7. Elimina filas completamente vacías.

    Parameters
    ----------
    path:
        Ruta al archivo CSV de Canvas.
    ciclo_config:
        Configuración YAML del ciclo (actualmente no se usa internamente,
        pero se acepta para compatibilidad futura).

    Returns
    -------
    pd.DataFrame
        DataFrame limpio con columnas ``Código``, ``Correo``, ``Sección``
        y las columnas de evaluaciones presentes en el archivo.

    Notes
    -----
    - Alumnos con DNI o código ``PREPARATE_UTEC_*`` en ``SIS User ID``
      no matchearán por código; el merge usará el correo como fallback.
    - La fila "Points Possible" se detecta por el valor ``"Points Possible"``
      en la columna ``Student``.
    """
    path = Path(path)
    encoding = detectar_encoding(path)

    # Intentar leer con el encoding detectado; fallback a latin-1
    try:
        df = pd.read_csv(path, encoding=encoding, dtype=str)
    except UnicodeDecodeError:
        df = pd.read_csv(path, encoding="latin-1", dtype=str)

    # Eliminar fila "Points Possible" (segunda fila del export de Canvas)
    if "Student" in df.columns:
        df = df[df["Student"] != "Points Possible"].copy()
    elif df.iloc[0].astype(str).str.contains("Points Possible", case=False).any():
        df = df.iloc[1:].copy()

    # Eliminar filas completamente vacías
    df = df.dropna(how="all").reset_index(drop=True)

    # Extraer Código y Correo
    if "SIS User ID" in df.columns:
        df["Código"] = df["SIS User ID"].str.strip()
    else:
        df["Código"] = np.nan

    if "SIS Login ID" in df.columns:
        df["Correo"] = df["SIS Login ID"].str.strip()
    else:
        df["Correo"] = np.nan

    # Extraer Sección
    if "Section" in df.columns:
        df["Sección"] = df["Section"].apply(_extraer_seccion_canvas)
    else:
        df["Sección"] = np.nan

    # Convertir columnas numéricas (decimales con coma)
    columnas_a_excluir = {
        "Student", "ID", "SIS User ID", "SIS Login ID", "Section",
        "Código", "Correo", "Sección",
    }
    for col in df.columns:
        if col not in columnas_a_excluir:
            df[col] = df[col].apply(limpiar_decimal)

    return df


# ---------------------------------------------------------------------------
# Carga de Gradescope
# ---------------------------------------------------------------------------

def load_gradescope_csv(path: str | Path) -> pd.DataFrame:
    """Carga un CSV exportado de Gradescope y lo limpia.

    Pasos que realiza:
    1. Detecta el encoding automáticamente.
    2. Lee el CSV.
    3. Usa ``SID`` como ``Código`` y ``Email`` como ``Correo``.
    4. Extrae el número de sección desde la columna ``Sections``.
    5. Elimina filas sin identificador de alumno.

    Parameters
    ----------
    path:
        Ruta al archivo CSV de Gradescope.

    Returns
    -------
    pd.DataFrame
        DataFrame limpio con columnas ``Código``, ``Correo``, ``Sección``
        y las columnas de evaluación del archivo.

    Notes
    -----
    - Alumnos con ``Status = "Missing"`` tendrán ``Total Score`` vacío (NaN).
    - La columna ``Sections`` tiene formato
      ``"clculo-vectorial-cc1104---teora---12"``.
    """
    path = Path(path)
    encoding = detectar_encoding(path)

    try:
        df = pd.read_csv(path, encoding=encoding, dtype=str)
    except UnicodeDecodeError:
        df = pd.read_csv(path, encoding="latin-1", dtype=str)

    # Eliminar filas completamente vacías
    df = df.dropna(how="all").reset_index(drop=True)

    # Mapear identificadores
    if "SID" in df.columns:
        df["Código"] = df["SID"].str.strip()
    else:
        df["Código"] = np.nan

    if "Email" in df.columns:
        df["Correo"] = df["Email"].str.strip()
    else:
        df["Correo"] = np.nan

    # Extraer sección
    if "Sections" in df.columns:
        df["Sección"] = df["Sections"].apply(mapear_seccion_gradescope)
    else:
        df["Sección"] = np.nan

    # Convertir columnas numéricas
    columnas_id = {"First Name", "Last Name", "SID", "Email", "Sections",
                   "Status", "Código", "Correo", "Sección", "Submission ID",
                   "Submission Time", "Lateness (H:M:S)"}
    for col in df.columns:
        if col not in columnas_id:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Filtrar filas sin identificador
    df = df[df["Código"].notna() & (df["Código"] != "")].copy()
    df = df.reset_index(drop=True)

    return df


def load_gradescope_ea(
    carpeta: str | Path,
    n_ea: int,
    secciones: list[int],
    patron: str = "EA{n}_Teor{s}.csv",
) -> pd.DataFrame:
    """Carga todos los CSVs de una Evaluación en Aula (EA) para todas las secciones.

    Gradescope genera un CSV por sección. Esta función los concatena todos
    en un único DataFrame con la columna ``EA{n}`` (nota sobre 20).

    Parameters
    ----------
    carpeta:
        Ruta a la carpeta que contiene los CSVs de la EA.
    n_ea:
        Número de la EA (1, 2, 3, ...).
    secciones:
        Lista de números de sección a cargar (ej. ``[1, 2, 11, 12, ...]``).
    patron:
        Patrón de nombre de archivo. Las variables ``{n}`` y ``{s}``
        se reemplazan por el número de EA y sección respectivamente.

    Returns
    -------
    pd.DataFrame
        DataFrame concatenado con columnas: ``Código``, ``Correo``,
        ``Sección``, ``EA{n}``.

    Notes
    -----
    - Si un archivo de sección no existe, se omite con un aviso.
    - La nota se extrae de la columna ``Total Score``.
    """
    carpeta = Path(carpeta)
    nombre_columna = f"EA{n_ea}"
    partes: list[pd.DataFrame] = []

    for s in secciones:
        nombre_archivo = patron.format(n=n_ea, s=s)
        ruta = carpeta / nombre_archivo
        if not ruta.exists():
            print(f"[AVISO] Archivo no encontrado: {ruta}. Se omite la sección {s}.")
            continue
        df_sec = load_gradescope_csv(ruta)
        if "Total Score" in df_sec.columns:
            df_sec = df_sec.rename(columns={"Total Score": nombre_columna})
        df_sec = df_sec[["Código", "Correo", "Sección", nombre_columna]].copy()
        partes.append(df_sec)

    if not partes:
        print(f"[AVISO] No se encontraron archivos para EA{n_ea}. Retornando DataFrame vacío.")
        return pd.DataFrame(columns=["Código", "Correo", "Sección", nombre_columna])

    df_total = pd.concat(partes, ignore_index=True)
    # Eliminar duplicados por Código (en caso de que un alumno aparezca en varios archivos)
    df_total = df_total.drop_duplicates(subset=["Código"], keep="first")
    return df_total
