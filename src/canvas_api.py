"""
canvas_api.py — Cliente para la Canvas REST API (UTEC).

Descarga notas de Tareas y EAs directamente desde Canvas,
devolviendo DataFrames compatibles con load_canvas_csv().
Soporta múltiples secciones (un course_id por sección) y
búsqueda de assignments por nombre exacto.
"""
from __future__ import annotations

import os
import re
import time
from typing import Optional

import pandas as pd
import requests


# ---------------------------------------------------------------------------
# Mapeo nombre Canvas → columna interna del pipeline
# ---------------------------------------------------------------------------

CANVAS_A_PIPELINE: dict[str, str] = {
    # Tareas
    "Tarea 1":           "T1",
    "Tarea 2":           "T2",
    "Tarea 3 - Parte A": "T3A",
    "Tarea 3 - Parte B": "T3B",
    "Tarea 4":           "T4",
    "Tarea 5":           "T5",
    "Tarea 6":           "T6",
    # Actividades Previas — Tramo 1 (12 videos)
    "AP1 - Video 1":     "AP1V1",
    "AP1 - Video 2":     "AP1V2",
    "AP2 - Video 1":     "AP2V1",
    "AP2 - Video 2":     "AP2V2",
    "AP3 - Video 1":     "AP3V1",
    "AP3 - Video 2":     "AP3V2",
    "AP4 - Video 1":     "AP4V1",
    "AP4 - Video 2":     "AP4V2",
    "AP5 - Video 1":     "AP5V1",
    "AP5 - Video 2":     "AP5V2",
    "AP6 - Video 1":     "AP6V1",
    "AP6 - Video 2":     "AP6V2",
    # Actividades Previas — Tramo 2 (5 videos, semanas 9, 10, 11, 13)
    "AP7 - Video 1":     "AP7V1",
    "AP7 - Video 2":     "AP7V2",
    "AP8 - Video 1":     "AP8V1",
    "AP9 - Video 1":     "AP9V1",
    "AP10 - Video 1":    "AP10V1",
    # RCs (Resolución de Casos)
    "RC - Primera Entrega":  "RC1",
    "RC - Segunda Entrega":  "RC2",
    # EAs (Evaluaciones en Aula — se crean en Canvas al sincronizar desde Gradescope)
    "Evaluación en Aula 1":  "EA1",
    "Evaluación en Aula 2":  "EA2",
    "Evaluación en Aula 3":  "EA3",
    "Evaluación en Aula 4":  "EA4",
    "Evaluación en Aula 5":  "EA5",
    "Evaluación en Aula 6":  "EA6",
    # Exámenes (pendiente confirmar nombres en Canvas)
    "Examen Parcial":    "ExP",
    "Examen Final":      "ExF",
    "Simulacro EP":      "SExP",
    "Simulacro EF":      "SExF",
}


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
        """Devuelve todos los alumnos con código SIS y correo.

        Endpoint: ``GET /api/v1/courses/{course_id}/enrollments``

        Parameters
        ----------
        course_id:
            ID del curso en Canvas.

        Returns
        -------
        pd.DataFrame
            Columnas: ``user_id``, ``Código`` (SIS user ID), ``Correo``
            (SIS Login ID = correo institucional en UTEC).
            La columna ``Sección`` la asigna ``fetch_canvas_grades_grupo``
            directamente desde la clave del dict del YAML.
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

    .. deprecated::
        Esta función asume un único ``course_id`` y busca assignments por ID
        numérico. En UTEC cada sección es un curso separado y los IDs de
        assignment varían entre secciones. Usar :func:`fetch_canvas_grades_grupo`
        en su lugar.

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


# ---------------------------------------------------------------------------
# Funciones multi-sección (diseño UTEC: un course_id por sección)
# ---------------------------------------------------------------------------


def fetch_canvas_grades_grupo(
    courses: dict[int, int],
    assignment_names: list[str],
    nombre_a_col: dict[str, str],
    base_url: str | None = None,
    token: str | None = None,
) -> pd.DataFrame:
    """Descarga notas de un grupo de secciones (auditorios o aulas).

    En UTEC cada sección es un curso separado en Canvas. Esta función
    itera sobre todas las secciones, busca los assignments por nombre exacto
    (en vez de por ID numérico, que varía entre secciones) y concatena los
    resultados en un único DataFrame.

    Parameters
    ----------
    courses:
        Mapeo ``{num_seccion: course_id}``.
        Ejemplo: ``{1: 20189, 2: 20205}``.
    assignment_names:
        Lista de nombres exactos de assignments en Canvas, tal como
        aparecen en la interfaz (p. ej. ``["Tarea 1", "AP1 - Video 1"]``).
    nombre_a_col:
        Mapeo nombre Canvas → columna del pipeline.
        Usar :data:`CANVAS_A_PIPELINE` para el mapeo completo del ciclo.
    base_url:
        URL base del servidor Canvas. Si no se provee, se lee de la
        variable de entorno ``CANVAS_BASE_URL``.
    token:
        Token de acceso personal de Canvas. Si no se provee, se lee de la
        variable de entorno ``CANVAS_TOKEN``.

    Returns
    -------
    pd.DataFrame
        Columnas: ``Código``, ``Correo``, ``Sección``,
        + columnas del pipeline correspondientes a los assignments
        encontrados (p. ej. ``T1``, ``T2``, ``AP1V1``, ``EA1``, ``RC1``).
        Compatible con el schema de ``load_canvas_csv()`` para que
        ``merge.py`` no cambie.

        Si un assignment no existe en una sección (aún no creado en Canvas),
        la columna tendrá ``NaN`` — no lanza error.

    Raises
    ------
    KeyError
        Si ``CANVAS_BASE_URL`` o ``CANVAS_TOKEN`` no están definidas en el
        entorno y no se proveen como argumentos.
    """
    base_url = base_url or os.environ["CANVAS_BASE_URL"]
    token = token or os.environ["CANVAS_TOKEN"]

    client = CanvasClient(base_url, token)
    nombres_set = set(assignment_names)
    partes: list[pd.DataFrame] = []

    for _seccion, course_id in courses.items():
        # 1. Alumnos de esta sección
        df_students = client.get_students(course_id)

        # 2. Sección viene directamente de la clave del dict YAML (ej. 11, 12, 13...)
        #    No dependemos de sis_section_id de Canvas (devuelve None en UTEC)
        df_students["Sección"] = _seccion

        # 3. Assignments: filtrar por nombre exacto
        df_assignments = client.get_assignments(course_id)
        df_found = df_assignments[df_assignments["name"].isin(nombres_set)]

        if df_found.empty:
            # No hay assignments conocidos en este curso — añadir filas vacías
            for col in nombre_a_col.values():
                if col not in df_students.columns:
                    df_students[col] = pd.NA
            partes.append(df_students.drop(columns="user_id"))
            continue

        assignment_ids = df_found["id"].tolist()

        # 4. Submissions
        df_subs = client.get_submissions(course_id, assignment_ids)

        # 5. Pivot: user_id × assignment_id → score
        if df_subs.empty:
            df_pivot = pd.DataFrame({"user_id": pd.Series(dtype="object")})
            for aid in assignment_ids:
                df_pivot[aid] = pd.Series(dtype="float64")
        else:
            df_pivot = df_subs.pivot_table(
                index="user_id",
                columns="assignment_id",
                values="score",
                aggfunc="first",
            )
            df_pivot.reset_index(inplace=True)

        # 6. Renombrar: assignment_id → nombre Canvas → columna pipeline
        id_to_canvas_name = df_found.set_index("id")["name"].to_dict()
        rename_map = {
            aid: nombre_a_col[cname]
            for aid, cname in id_to_canvas_name.items()
            if cname in nombre_a_col
        }
        df_pivot.rename(columns=rename_map, inplace=True)

        # Eliminar columnas que no tienen mapeo (IDs no renombrados)
        cols_to_drop = [c for c in df_pivot.columns if isinstance(c, int)]
        df_pivot.drop(columns=cols_to_drop, inplace=True)

        df_seccion = df_students.merge(df_pivot, on="user_id", how="left").drop(
            columns="user_id"
        )
        partes.append(df_seccion)

    if not partes:
        return pd.DataFrame(columns=["Código", "Correo", "Sección"])

    return pd.concat(partes, ignore_index=True)


def listar_assignments_grupo(
    courses: dict[int, int],
    base_url: str | None = None,
    token: str | None = None,
) -> pd.DataFrame:
    """Devuelve todos los assignments de todas las secciones del grupo.

    Función de diagnóstico útil para verificar los nombres exactos de los
    assignments en Canvas antes de configurar el pipeline.

    Parameters
    ----------
    courses:
        Mapeo ``{num_seccion: course_id}``.
        Ejemplo: ``{11: 20245, 12: 20246}``.
    base_url:
        URL base del servidor Canvas. Si no se provee, se lee de la
        variable de entorno ``CANVAS_BASE_URL``.
    token:
        Token de acceso personal de Canvas. Si no se provee, se lee de la
        variable de entorno ``CANVAS_TOKEN``.

    Returns
    -------
    pd.DataFrame
        Columnas: ``seccion``, ``course_id``, ``assignment_id``,
        ``nombre``, ``puntos_posibles``.

    Raises
    ------
    KeyError
        Si ``CANVAS_BASE_URL`` o ``CANVAS_TOKEN`` no están definidas en el
        entorno y no se proveen como argumentos.
    """
    base_url = base_url or os.environ["CANVAS_BASE_URL"]
    token = token or os.environ["CANVAS_TOKEN"]

    client = CanvasClient(base_url, token)
    partes: list[pd.DataFrame] = []

    for seccion, course_id in courses.items():
        df = client.get_assignments(course_id)
        df.insert(0, "seccion", seccion)
        df.insert(1, "course_id", course_id)
        df.rename(
            columns={"id": "assignment_id", "name": "nombre", "points_possible": "puntos_posibles"},
            inplace=True,
        )
        partes.append(df)

    if not partes:
        return pd.DataFrame(
            columns=["seccion", "course_id", "assignment_id", "nombre", "puntos_posibles"]
        )

    return pd.concat(partes, ignore_index=True)
