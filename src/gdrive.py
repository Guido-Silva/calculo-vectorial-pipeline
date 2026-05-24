"""
gdrive.py — Módulo de integración con Google Sheets del pipeline de Cálculo Vectorial UTEC.

Funciones para autenticarse con una Service Account de Google, leer hojas
de cálculo y escribir columnas calculadas sin pisar otros datos.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

try:
    import gspread
    from google.oauth2.service_account import Credentials
    GSPREAD_DISPONIBLE = True
except ImportError:
    GSPREAD_DISPONIBLE = False


# Alcances necesarios para leer y escribir en Google Sheets y Drive
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


COLUMNAS_REDONDEO_ENTERO = {
    "EA1", "EA2", "EA3", "EA4", "EA5", "EA6",
    "T2", "T3",
}


def _redondear_mitad_arriba(valor) -> int | float:
    """Redondea notas no negativas al entero más cercano, con .5 hacia arriba."""
    if pd.isna(valor):
        return np.nan
    try:
        numero = float(str(valor).strip().replace(",", "."))
    except ValueError:
        return valor
    return int(np.floor(numero + 0.5))


def _valor_para_google_sheets(columna: str, valor):
    """Prepara un valor antes de escribirlo en Google Sheets."""
    if columna in COLUMNAS_REDONDEO_ENTERO:
        return _redondear_mitad_arriba(valor)
    return valor


# ---------------------------------------------------------------------------
# Autenticación
# ---------------------------------------------------------------------------

def conectar_gspread(credentials_path: str | Path) -> "gspread.Client":
    """Autentica con Google Sheets usando un archivo de Service Account JSON.

    Parameters
    ----------
    credentials_path:
        Ruta al archivo ``service_account.json`` con las credenciales de Google.

    Returns
    -------
    gspread.Client
        Cliente autenticado de gspread.

    Raises
    ------
    ImportError
        Si gspread o google-auth no están instalados.
    FileNotFoundError
        Si el archivo de credenciales no existe.
    Exception
        Si la autenticación falla por credenciales inválidas.
    """
    if not GSPREAD_DISPONIBLE:
        raise ImportError(
            "gspread y/o google-auth no están instalados. "
            "Ejecuta: uv pip install -r requirements.txt"
        )

    credentials_path = Path(credentials_path)
    if not credentials_path.exists():
        raise FileNotFoundError(
            f"No se encontró el archivo de credenciales: {credentials_path}\n"
            "Coloca tu service_account.json en la carpeta credentials/."
        )

    try:
        creds = Credentials.from_service_account_file(str(credentials_path), scopes=SCOPES)
        gc = gspread.authorize(creds)
        print(f"[GDRIVE] Conexión exitosa con Google Sheets.")
        return gc
    except Exception as e:
        raise Exception(
            f"Error al autenticar con Google Sheets: {e}\n"
            "Verifica que el archivo service_account.json sea válido y que la "
            "Service Account tenga acceso al Google Sheet."
        ) from e


# ---------------------------------------------------------------------------
# Lectura de hojas
# ---------------------------------------------------------------------------

def leer_hoja(
    sheet_id: str,
    nombre_hoja: str,
    gc: Optional["gspread.Client"] = None,
    credentials_path: Optional[str | Path] = None,
) -> pd.DataFrame:
    """Lee una hoja de Google Sheets y retorna un DataFrame.

    Parameters
    ----------
    sheet_id:
        ID del Google Sheet (parte de la URL después de /d/).
    nombre_hoja:
        Nombre de la pestaña/hoja a leer.
    gc:
        Cliente de gspread ya autenticado. Si es None, se usa credentials_path.
    credentials_path:
        Ruta a las credenciales (solo si gc es None).

    Returns
    -------
    pd.DataFrame
        DataFrame con los datos de la hoja. La primera fila se usa como encabezado.

    Raises
    ------
    ValueError
        Si ni gc ni credentials_path son proporcionados.
    """
    if gc is None:
        if credentials_path is None:
            raise ValueError("Debes proporcionar gc o credentials_path.")
        gc = conectar_gspread(credentials_path)

    try:
        hoja = gc.open_by_key(sheet_id).worksheet(nombre_hoja)
        datos = hoja.get_all_records()
        df = pd.DataFrame(datos)
        print(f"[GDRIVE] Hoja '{nombre_hoja}' leída: {len(df)} filas, {len(df.columns)} columnas.")
        return df
    except gspread.exceptions.WorksheetNotFound:
        raise Exception(
            f"No se encontró la hoja '{nombre_hoja}' en el Sheet {sheet_id}.\n"
            "Verifica que el nombre de la hoja sea correcto."
        )
    except Exception as e:
        raise Exception(f"Error al leer la hoja '{nombre_hoja}': {e}") from e


# ---------------------------------------------------------------------------
# Escritura de columnas calculadas
# ---------------------------------------------------------------------------

def escribir_columnas_notas(
    sheet_id: str,
    df: pd.DataFrame,
    columnas: list[str],
    gc: Optional["gspread.Client"] = None,
    credentials_path: Optional[str | Path] = None,
    nombre_hoja: str = "Notas",
    col_llave: str = "Código",
) -> None:
    """Escribe solo las columnas calculadas en la hoja 'Notas', sin tocar otras columnas.

    Hace match por la columna llave (Código) entre el DataFrame y el Sheet.
    Solo actualiza las celdas correspondientes a las columnas especificadas.

    Parameters
    ----------
    sheet_id:
        ID del Google Sheet.
    df:
        DataFrame con los datos calculados.
    columnas:
        Lista de columnas a escribir en el Sheet (ej. ["EA1", "PT1", "NF"]).
    gc:
        Cliente de gspread autenticado. Si es None, usa credentials_path.
    credentials_path:
        Ruta a las credenciales (solo si gc es None).
    nombre_hoja:
        Nombre de la hoja donde escribir (default: "Notas").
    col_llave:
        Columna de match entre el DataFrame y el Sheet (default: "Código").

    Notes
    -----
    - Solo se actualizan las columnas especificadas; el resto del Sheet queda intacto.
    - El match es por col_llave. Alumnos sin match en el Sheet no se agregan.
    - Si una columna no existe en el Sheet, se agrega al final.
    """
    if gc is None:
        if credentials_path is None:
            raise ValueError("Debes proporcionar gc o credentials_path.")
        gc = conectar_gspread(credentials_path)

    try:
        spreadsheet = gc.open_by_key(sheet_id)
        hoja = spreadsheet.worksheet(nombre_hoja)

        # Leer encabezados actuales del Sheet
        encabezados = hoja.row_values(1)
        n_cols_sheet = len(encabezados)

        # Verificar/agregar columnas que no existen en el Sheet
        for col in columnas:
            if col not in encabezados:
                encabezados.append(col)
                idx_nueva_col = len(encabezados)  # 1-indexed
                hoja.update_cell(1, idx_nueva_col, col)
                print(f"[GDRIVE] Columna '{col}' agregada al Sheet en posición {idx_nueva_col}.")

        # Leer la columna llave del Sheet para hacer match
        idx_llave_sheet = encabezados.index(col_llave) + 1  # 1-indexed
        valores_llave_sheet = hoja.col_values(idx_llave_sheet)
        # valores_llave_sheet[0] es el encabezado; los datos comienzan en el índice 1.
        # fila_idx es 0-indexed en la enumeración → fila real en el sheet = fila_idx + 2
        # (fila 1 = encabezado, fila 2 = primer dato)
        llave_a_fila = {
            str(val).strip(): fila_idx + 2
            for fila_idx, val in enumerate(valores_llave_sheet[1:])
            if val
        }

        # Preparar actualizaciones batch
        actualizaciones = []
        n_actualizados = 0

        for _, row in df.iterrows():
            codigo = str(row.get(col_llave, "")).strip()
            if codigo not in llave_a_fila:
                continue
            fila_sheet = llave_a_fila[codigo]

            for col in columnas:
                if col not in df.columns:
                    continue
                valor = _valor_para_google_sheets(col, row.get(col))
                if pd.isna(valor):
                    continue
                idx_col_sheet = encabezados.index(col) + 1  # 1-indexed
                actualizaciones.append({
                    "range": gspread.utils.rowcol_to_a1(fila_sheet, idx_col_sheet),
                    "values": [[valor]],
                })
            n_actualizados += 1

        # Ejecutar actualizaciones en batch
        if actualizaciones:
            hoja.batch_update(actualizaciones)
            print(f"[GDRIVE] Actualizados {n_actualizados} alumnos con columnas: {columnas}")
        else:
            print("[GDRIVE] No hay datos para actualizar.")

    except Exception as e:
        raise Exception(f"Error al escribir en la hoja '{nombre_hoja}': {e}") from e


# ---------------------------------------------------------------------------
# Escritura de hoja Formativa
# ---------------------------------------------------------------------------

def escribir_formativa(
    sheet_id: str,
    df_formativa: pd.DataFrame,
    gc: Optional["gspread.Client"] = None,
    credentials_path: Optional[str | Path] = None,
    nombre_hoja: str = "Formativa",
    columnas: Optional[list[str]] = None,
) -> None:
    """Escribe los datos de actividades previas en la hoja 'Formativa'.

    Escribe las columnas de actividades previas (PAP1, PAP2, BPEA1_prov, BPEA2)
    en la hoja Formativa del Google Sheet.

    Parameters
    ----------
    sheet_id:
        ID del Google Sheet.
    df_formativa:
        DataFrame con los datos de actividades previas.
        Debe tener columna ``Código`` para hacer match.
    gc:
        Cliente de gspread autenticado.
    credentials_path:
        Ruta a las credenciales (solo si gc es None).
    nombre_hoja:
        Nombre de la hoja de formativas (default: "Formativa").
    columnas:
        Lista de columnas a escribir. Si es None, se escriben todas las
        columnas de actividades previas y bonificaciones disponibles.
    """
    if columnas is None:
        columnas_posibles = [
            "PV1", "PV2", "BPEA1_prov", "BPEA1_final", "BPEA2",
        ] + [f"AP{i}V{j}" for i in range(1, 11) for j in range(1, 3)]
        columnas = [c for c in columnas_posibles if c in df_formativa.columns]

    if not columnas:
        print("[GDRIVE] No hay columnas de formativa para escribir.")
        return

    escribir_columnas_notas(
        sheet_id=sheet_id,
        df=df_formativa,
        columnas=columnas,
        gc=gc,
        credentials_path=credentials_path,
        nombre_hoja=nombre_hoja,
    )
