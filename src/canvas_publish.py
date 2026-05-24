"""
canvas_publish.py - Publicacion de notas calculadas a Canvas.

Este modulo agrupa acciones operativas que toman resultados del pipeline
(``df_calculado`` u otro DataFrame compatible) y los publican en Canvas.
La idea es mantener la logica de API fuera de los notebooks para que el
repositorio sea mas facil de entender y mantener.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.canvas_api import CanvasClient


@dataclass(frozen=True)
class PublishConfig:
    """Parametros de publicacion para una columna de notas."""

    assignment_name: str
    col_codigo: str = "Código"
    col_seccion: str = "Sección"
    col_nota: str = "EP"
    dry_run: bool = True
    skip_si_misma_nota: bool = True
    validar_points_possible_20: bool = False
    sleep_between_puts: float = 0.15


def normalizar_codigo(value: object) -> object:
    """Normaliza codigos para cruzar datos locales con Canvas."""
    if pd.isna(value):
        return pd.NA

    text = str(value).strip()
    if re.fullmatch(r"\d+\.0", text):
        text = text[:-2]
    return text


def normalizar_seccion(value: object) -> object:
    """Extrae el numero de seccion desde formatos comunes."""
    if pd.isna(value):
        return pd.NA

    match = re.search(r"(\d+)$", str(value).strip())
    if not match:
        return pd.NA
    return int(match.group(1))


def notas_iguales(a: object, b: object, tol: float = 1e-9) -> bool:
    """Compara notas tolerando diferencias flotantes minimas."""
    if pd.isna(a) and pd.isna(b):
        return True
    if pd.isna(a) or pd.isna(b):
        return False
    return abs(float(a) - float(b)) <= tol


def validar_dataframe_publicacion(
    df_calculado: pd.DataFrame,
    *,
    col_codigo: str,
    col_seccion: str,
    col_nota: str,
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """Valida y limpia el DataFrame antes de publicar notas."""
    for column in (col_codigo, col_seccion, col_nota):
        if column not in df_calculado.columns:
            raise KeyError(f"Falta la columna '{column}' en df_calculado.")

    df_local = df_calculado.copy()
    df_local["_codigo_norm"] = df_local[col_codigo].map(normalizar_codigo)
    df_local["_seccion_num"] = df_local[col_seccion].map(normalizar_seccion)
    df_local["_nota_num"] = pd.to_numeric(df_local[col_nota], errors="coerce")

    reportes = {
        "sin_codigo": df_local[df_local["_codigo_norm"].isna()].copy(),
        "sin_seccion": df_local[df_local["_seccion_num"].isna()].copy(),
        "sin_nota": df_local[df_local["_nota_num"].isna()].copy(),
    }

    df_local = df_local[
        df_local["_codigo_norm"].notna()
        & df_local["_seccion_num"].notna()
        & df_local["_nota_num"].notna()
    ].copy()

    df_fuera_rango = df_local[(df_local["_nota_num"] < 0) | (df_local["_nota_num"] > 20)]
    if not df_fuera_rango.empty:
        raise ValueError("Hay notas fuera del rango [0, 20]. Revisa antes de publicar.")

    df_duplicados = df_local[df_local["_codigo_norm"].duplicated(keep=False)]
    if not df_duplicados.empty:
        raise ValueError("Hay codigos duplicados en df_calculado. Revisa antes de publicar.")

    reportes["validos"] = df_local.copy()
    return df_local, reportes


def buscar_assignment_exactamente(
    client: CanvasClient,
    course_id: int | str,
    assignment_name: str,
) -> pd.Series:
    """Busca un assignment por nombre exacto en un curso."""
    df_assignments = client.get_assignments(course_id)
    if df_assignments.empty:
        raise ValueError(f"No hay assignments visibles por API en course_id={course_id}.")

    nombres = df_assignments["name"].astype(str).str.strip()
    encontrados = df_assignments[nombres.eq(assignment_name.strip())].copy()

    if encontrados.empty:
        parecidos = df_assignments[
            df_assignments["name"].astype(str).str.contains(
                assignment_name,
                case=False,
                na=False,
                regex=False,
            )
        ][["id", "name", "points_possible"]]

        mensaje = (
            f"No encontre el assignment exacto '{assignment_name}' "
            f"en course_id={course_id}."
        )
        if not parecidos.empty:
            mensaje += "\n\nAssignments parecidos:\n" + parecidos.to_string(index=False)
        raise ValueError(mensaje)

    if len(encontrados) > 1:
        raise ValueError(
            f"Hay mas de un assignment llamado '{assignment_name}' en course_id={course_id}."
        )

    return encontrados.iloc[0]


def subir_nota_canvas(
    client: CanvasClient,
    *,
    course_id: int | str,
    assignment_id: int,
    user_id: int,
    score: float,
) -> dict:
    """Actualiza una nota en Canvas usando posted_grade."""
    endpoint = (
        f"/api/v1/courses/{course_id}"
        f"/assignments/{assignment_id}"
        f"/submissions/{user_id}"
    )
    url = f"{client.base_url}{endpoint}"
    response = client.session.put(
        url,
        data={"submission[posted_grade]": str(score)},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def publicar_notas_por_seccion(
    df_calculado: pd.DataFrame,
    *,
    client: CanvasClient,
    course_id_by_grupo: dict[int, int | str],
    secciones_by_grupo: dict[int, list[int]],
    config: PublishConfig,
) -> dict[str, object]:
    """
    Prepara y opcionalmente ejecuta la publicacion de una columna de notas.

    Retorna un diccionario con DataFrames de plan, errores y filas no
    encontradas para que el notebook pueda inspeccionarlos facilmente.
    """
    df_local, reportes = validar_dataframe_publicacion(
        df_calculado,
        col_codigo=config.col_codigo,
        col_seccion=config.col_seccion,
        col_nota=config.col_nota,
    )

    filas_plan: list[dict[str, object]] = []
    filas_no_encontrados: list[dict[str, object]] = []
    filas_errores: list[dict[str, object]] = []
    resumen_grupos: list[dict[str, object]] = []

    for grupo, secciones in secciones_by_grupo.items():
        course_id = course_id_by_grupo[grupo]
        df_grupo = df_local[df_local["_seccion_num"].isin(secciones)].copy()

        if df_grupo.empty:
            resumen_grupos.append(
                {
                    "grupo": grupo,
                    "course_id": course_id,
                    "assignment": config.assignment_name,
                    "alumnos_validos": 0,
                    "status": "sin_alumnos",
                }
            )
            continue

        assignment = buscar_assignment_exactamente(client, course_id, config.assignment_name)
        assignment_id = int(assignment["id"])
        points_possible = assignment.get("points_possible")

        if (
            config.validar_points_possible_20
            and pd.notna(points_possible)
            and float(points_possible) != 20.0
        ):
            raise ValueError(
                f"El assignment '{config.assignment_name}' en grupo {grupo} "
                f"tiene points_possible={points_possible}, no 20."
            )

        df_students = client.get_students(course_id).copy()
        if df_students.empty:
            raise ValueError(f"No encontre estudiantes en Canvas para course_id={course_id}.")

        df_students["_codigo_norm"] = df_students["Código"].map(normalizar_codigo)
        df_upload = df_grupo.merge(
            df_students[["user_id", "Código", "Correo", "_codigo_norm"]],
            on="_codigo_norm",
            how="left",
            suffixes=("_local", "_canvas"),
        )

        df_missing = df_upload[df_upload["user_id"].isna()].copy()
        for _, row in df_missing.iterrows():
            filas_no_encontrados.append(
                {
                    "grupo": grupo,
                    "course_id": course_id,
                    "codigo": row.get(config.col_codigo),
                    "seccion": row.get(config.col_seccion),
                    "nota": row.get(config.col_nota),
                }
            )

        df_upload = df_upload[df_upload["user_id"].notna()].copy()
        if df_upload.empty:
            resumen_grupos.append(
                {
                    "grupo": grupo,
                    "course_id": course_id,
                    "assignment": config.assignment_name,
                    "alumnos_validos": len(df_grupo),
                    "status": "sin_cruce_canvas",
                }
            )
            continue

        df_submissions = client.get_submissions(course_id, [assignment_id])
        notas_canvas = (
            {}
            if df_submissions.empty
            else df_submissions.set_index("user_id")["score"].to_dict()
        )

        for _, row in df_upload.iterrows():
            user_id = int(row["user_id"])
            score_local = float(row["_nota_num"])
            score_canvas = notas_canvas.get(user_id, np.nan)
            misma_nota = notas_iguales(score_local, score_canvas)

            status = "pendiente"
            error = None

            if config.skip_si_misma_nota and misma_nota:
                status = "omitida_misma_nota"
            elif config.dry_run:
                status = "dry_run_update"
            else:
                try:
                    subir_nota_canvas(
                        client,
                        course_id=course_id,
                        assignment_id=assignment_id,
                        user_id=user_id,
                        score=score_local,
                    )
                    status = "updated"
                    time.sleep(config.sleep_between_puts)
                except Exception as exc:  # pragma: no cover
                    status = "error"
                    error = repr(exc)
                    filas_errores.append(
                        {
                            "grupo": grupo,
                            "course_id": course_id,
                            "assignment_id": assignment_id,
                            "codigo": row["_codigo_norm"],
                            "user_id": user_id,
                            "nota_local": score_local,
                            "nota_canvas_actual": score_canvas,
                            "error": error,
                        }
                    )

            filas_plan.append(
                {
                    "grupo": grupo,
                    "seccion": int(row["_seccion_num"]),
                    "course_id": course_id,
                    "assignment": config.assignment_name,
                    "assignment_id": assignment_id,
                    "codigo": row["_codigo_norm"],
                    "user_id": user_id,
                    "correo": row.get("Correo"),
                    "nota_local": score_local,
                    "nota_canvas_actual": score_canvas,
                    "status": status,
                    "error": error,
                }
            )

        resumen_grupos.append(
            {
                "grupo": grupo,
                "course_id": course_id,
                "assignment": config.assignment_name,
                "alumnos_validos": len(df_grupo),
                "alumnos_con_match_canvas": len(df_upload),
                "no_encontrados": len(df_missing),
                "status": "procesado",
            }
        )

    return {
        "df_validado": df_local,
        "reportes_validacion": reportes,
        "df_plan_publicacion": pd.DataFrame(filas_plan),
        "df_no_encontrados": pd.DataFrame(filas_no_encontrados),
        "df_errores_publicacion": pd.DataFrame(filas_errores),
        "df_resumen_publicacion": pd.DataFrame(resumen_grupos),
    }
