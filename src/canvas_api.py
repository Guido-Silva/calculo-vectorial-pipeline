"""
canvas_api.py — Cliente para la Canvas REST API (UTEC).

Descarga notas de Tareas y EAs directamente desde Canvas,
devolviendo DataFrames compatibles con load_canvas_csv().
"""
from __future__ import annotations

import os
import re
import time
from typing import Optional

import pandas as pd
import requests


# ---------------------------------------------------------------------------
# Utilidades internas
# ---------------------------------------------------------------------------


def _extraer_seccion(sis_section_id: str) -> Optional[int]:
    """Extrae el número de sección desde el identificador SIS de Canvas.

    Parameters
    ----------
    sis_section_id:
        Identificador de sección SIS de Canvas.
        Ejemplo: ``"CC1104 - Teoría - 12"`` → ``12``.

    Returns
    -------
    int o None
        Número de sección, o ``None`` si no se puede extraer.
    """
    if not sis_section_id:
        return None
    m = re.search(r"-\s*(\d+)\s*$", sis_section_id.strip())
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# Cliente REST
# ---------------------------------------------------------------------------


class CanvasClient:
    """Cliente liviano para la Canvas REST API con paginación automática (rel=next).

    Parameters
    ----------
    base_url:
        URL base del servidor Canvas, p. ej. ``"https://utec.instructure.com"``.
    token:
        Token de acceso personal de Canvas (Bearer token).
    """

    def __init__(self, base_url: str, token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {token}"})

    def _get(self, endpoint: str, params: dict | None = None) -> list[dict]:
        """GET paginado — sigue el header ``Link: rel=next`` automáticamente.

        Incluye ``time.sleep(0.1)`` entre páginas para respetar el rate-limit
        de la API de Canvas.

        Parameters
        ----------
        endpoint:
            Ruta relativa al ``base_url``, p. ej. ``"/api/v1/courses/123/enrollments"``.
        params:
            Parámetros de la primera petición. Se ignoran en páginas sucesivas
            porque la URL paginada ya los incluye.

        Returns
        -------
        list[dict]
            Lista de objetos JSON devueltos por todas las páginas concatenadas.
        """
        url: str | None = f"{self.base_url}{endpoint}"
        resultados: list[dict] = []
        while url:
            resp = self.session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            resultados.extend(resp.json())
            url = resp.links.get("next", {}).get("url")
            params = None  # solo en la primera request
            time.sleep(0.1)  # respetar rate-limit
        return resultados

    # ------------------------------------------------------------------
    # Métodos de negocio
    # ------------------------------------------------------------------

    def get_students(self, course_id: str) -> pd.DataFrame:
        """Devuelve todos los alumnos con código SIS, correo y sección.

        Endpoint: ``GET /api/v1/courses/{course_id}/enrollments``

        Parameters
        ----------
        course_id:
            ID del curso en Canvas.

        Returns
        -------
        pd.DataFrame
            Columnas: ``user_id``, ``Código`` (SIS user ID), ``Correo``
            (SIS Login ID = correo institucional en UTEC) y ``Sección``
            (número extraído del ``sis_section_id``).
        """
        enrollments = self._get(
            f"/api/v1/courses/{course_id}/enrollments",
            params={
                "type[]": "StudentEnrollment",
                "state[]": ["active", "completed"],
                "per_page": 100,
                "include[]": ["user", "sis_user_id"],
            },
        )
        rows = []
        for e in enrollments:
            user = e.get("user", {})
            rows.append(
                {
                    "user_id": e.get("user_id"),
                    "Código": e.get("sis_user_id") or user.get("sis_user_id"),
                    "Correo": user.get("login_id"),  # = SIS Login ID en UTEC
                    "Sección": _extraer_seccion(e.get("sis_section_id", "") or ""),
                }
            )
        return pd.DataFrame(rows)

    def get_assignments(self, course_id: str) -> pd.DataFrame:
        """Devuelve todos los assignments del curso.

        Endpoint: ``GET /api/v1/courses/{course_id}/assignments``

        Parameters
        ----------
        course_id:
            ID del curso en Canvas.

        Returns
        -------
        pd.DataFrame
            Columnas: ``id``, ``name``, ``points_possible``.
        """
        data = self._get(
            f"/api/v1/courses/{course_id}/assignments",
            params={"per_page": 100},
        )
        return pd.DataFrame(
            [
                {
                    "id": a["id"],
                    "name": a["name"],
                    "points_possible": a.get("points_possible"),
                }
                for a in data
            ]
        )

    def get_submissions(
        self, course_id: str, assignment_ids: list[int]
    ) -> pd.DataFrame:
        """Devuelve las notas de los assignments indicados para todos los alumnos.

        Endpoint: ``GET /api/v1/courses/{course_id}/students/submissions``

        Parameters
        ----------
        course_id:
            ID del curso en Canvas.
        assignment_ids:
            Lista de IDs de assignments a consultar.

        Returns
        -------
        pd.DataFrame
            Columnas: ``user_id``, ``assignment_id``, ``score`` (float o None).
        """
        data = self._get(
            f"/api/v1/courses/{course_id}/students/submissions",
            params={
                "student_ids[]": "all",
                "assignment_ids[]": assignment_ids,
                "include[]": ["user"],
                "per_page": 100,
            },
        )
        rows = []
        for s in data:
            score = s.get("score")
            rows.append(
                {
                    "user_id": s["user_id"],
                    "assignment_id": s["assignment_id"],
                    "score": float(score) if score is not None else None,
                }
            )
        return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Función de alto nivel
# ---------------------------------------------------------------------------


def fetch_canvas_grades(
    course_id: str,
    columnas: dict[str, int],
    base_url: str | None = None,
    token: str | None = None,
) -> pd.DataFrame:
    """Descarga notas de Canvas y devuelve un DataFrame compatible con load_canvas_csv().

    Parameters
    ----------
    course_id:
        ID del curso en Canvas (número o string).
    columnas:
        Mapeo ``{nombre_columna_pipeline: assignment_id_canvas}``.
        Ejemplo: ``{"Tarea 1": 234567, "EA1": 234589}``.
    base_url:
        URL base del servidor Canvas. Si no se provee, se lee de la
        variable de entorno ``CANVAS_BASE_URL``. Levanta ``KeyError`` si
        la variable no está definida.
    token:
        Token de acceso personal de Canvas. Si no se provee, se lee de la
        variable de entorno ``CANVAS_TOKEN``. Levanta ``KeyError`` si la
        variable no está definida.

    Returns
    -------
    pd.DataFrame
        Columnas: ``Código``, ``Correo``, ``Sección``, + cada clave de
        ``columnas``. Compatible con el schema exacto de
        ``load_canvas_csv()`` para que ``merge.py`` no cambie.

    Raises
    ------
    KeyError
        Si ``CANVAS_BASE_URL`` o ``CANVAS_TOKEN`` no están definidas en el
        entorno y no se proveen como argumentos.
    """
    base_url = base_url or os.environ["CANVAS_BASE_URL"]
    token = token or os.environ["CANVAS_TOKEN"]

    client = CanvasClient(base_url, token)

    df_students = client.get_students(course_id)
    assignment_ids = list(columnas.values())
    df_subs = client.get_submissions(course_id, assignment_ids)

    # Pivot: user_id × assignment_id → score
    if df_subs.empty:
        df_pivot = pd.DataFrame({"user_id": pd.Series(dtype="object")})
        for nombre in columnas:
            df_pivot[nombre] = pd.Series(dtype="float64")
    else:
        df_pivot = df_subs.pivot_table(
            index="user_id", columns="assignment_id", values="score", aggfunc="first"
        )
        # Renombrar columnas de ID numérico al nombre del pipeline
        id_to_nombre = {v: k for k, v in columnas.items()}
        df_pivot.rename(columns=id_to_nombre, inplace=True)
        df_pivot.reset_index(inplace=True)

    df = df_students.merge(df_pivot, on="user_id", how="left").drop(columns="user_id")
    return df
