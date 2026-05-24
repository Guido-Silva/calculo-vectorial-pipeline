"""
canvas_admin.py - Utilidades administrativas para Canvas.

Este modulo contiene acciones con efecto real en Canvas, como crear
assignments en varios cursos. Por seguridad, las funciones de alto nivel usan
``dry_run=True`` por defecto.
"""

from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd
import requests


DESCRIPCION_GRADESCOPE = (
    "Nota sincronizada desde Gradescope. Para revisar tu examen y "
    "retroalimentación, ingresa a Gradescope."
)

GRUPO_EVALUACIONES_AULA = "Evaluaciones en Aula"
GRUPO_EXAMENES = "Exámenes"


@dataclass(frozen=True)
class AssignmentSpec:
    """Configuracion minima de un assignment de Canvas."""

    name: str
    points_possible: float
    description: str = DESCRIPCION_GRADESCOPE
    assignment_group_name: str = GRUPO_EVALUACIONES_AULA
    grading_type: str = "points"
    submission_types: tuple[str, ...] = ("none",)
    published: bool = True

    def canvas_payload(self, assignment_group_id: int | None = None) -> dict[str, Any]:
        """Retorna el payload esperado por Canvas para crear el assignment."""
        assignment: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "points_possible": self.points_possible,
            "grading_type": self.grading_type,
            "submission_types": list(self.submission_types),
            "published": self.published,
        }
        if assignment_group_id is not None:
            assignment["assignment_group_id"] = assignment_group_id
        return {"assignment": assignment}


SIMULACRO_EP = AssignmentSpec(
    name="Simulacro EP",
    points_possible=20,
    assignment_group_name=GRUPO_EXAMENES,
)

EXAMEN_PARCIAL = AssignmentSpec(
    name="Examen Parcial",
    points_possible=23,
    assignment_group_name=GRUPO_EXAMENES,
)


def evaluacion_en_aula(numero: int, points_possible: float = 20) -> AssignmentSpec:
    """Construye el spec de una Evaluación en Aula."""
    return AssignmentSpec(
        name=f"Evaluación en Aula {numero}",
        points_possible=points_possible,
        assignment_group_name=GRUPO_EVALUACIONES_AULA,
    )


def examen_canvas(nombre: str, points_possible: float) -> AssignmentSpec:
    """Construye el spec de un examen o simulacro en el grupo Exámenes."""
    return AssignmentSpec(
        name=nombre,
        points_possible=points_possible,
        assignment_group_name=GRUPO_EXAMENES,
    )


class CanvasAdminClient:
    """Cliente pequeño para acciones administrativas de Canvas."""

    def __init__(self, base_url: str | None = None, token: str | None = None) -> None:
        self.base_url = (base_url or os.environ["CANVAS_BASE_URL"]).rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token or os.environ['CANVAS_TOKEN']}",
                "Accept": "application/json",
            }
        )

    def _get(self, endpoint: str, params: dict | None = None) -> list[dict]:
        url: str | None = f"{self.base_url}{endpoint}"
        resultados: list[dict] = []
        while url:
            resp = self.session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            resultados.extend(resp.json())
            url = resp.links.get("next", {}).get("url")
            params = None
            time.sleep(0.1)
        return resultados

    def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{endpoint}"
        resp = self.session.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def listar_assignment_groups(self, course_id: int | str) -> pd.DataFrame:
        """Lista los grupos de tareas de un curso."""
        data = self._get(
            f"/api/v1/courses/{course_id}/assignment_groups",
            params={"per_page": 100},
        )
        return pd.DataFrame(
            [
                {
                    "id": group["id"],
                    "name": group["name"],
                    "position": group.get("position"),
                }
                for group in data
            ]
        )

    def buscar_assignment_group(
        self,
        course_id: int | str,
        group_name: str,
    ) -> dict[str, Any] | None:
        """Busca un grupo de tareas por nombre exacto."""
        groups = self._get(
            f"/api/v1/courses/{course_id}/assignment_groups",
            params={"per_page": 100},
        )
        for group in groups:
            if group.get("name") == group_name:
                return group
        return None

    def crear_assignment_group(
        self,
        course_id: int | str,
        group_name: str,
    ) -> dict[str, Any]:
        """Crea un grupo de tareas en Canvas."""
        payload = {"name": group_name}
        return self._post(
            f"/api/v1/courses/{course_id}/assignment_groups",
            payload,
        )

    def obtener_assignment_group_id(
        self,
        course_id: int | str,
        group_name: str,
        create_if_missing: bool = False,
    ) -> int:
        """Obtiene el ID de un grupo de tareas, opcionalmente creandolo."""
        group = self.buscar_assignment_group(course_id, group_name)
        if group is not None:
            return int(group["id"])

        if create_if_missing:
            group = self.crear_assignment_group(course_id, group_name)
            return int(group["id"])

        raise ValueError(
            f"No existe el grupo de tareas '{group_name}' en el curso {course_id}. "
            "Crea el grupo en Canvas o usa create_group_if_missing=True."
        )

    def listar_assignments(self, course_id: int | str) -> pd.DataFrame:
        """Lista assignments de un curso."""
        data = self._get(
            f"/api/v1/courses/{course_id}/assignments",
            params={"per_page": 100},
        )
        return pd.DataFrame(
            [
                {
                    "id": item["id"],
                    "name": item["name"],
                    "points_possible": item.get("points_possible"),
                    "published": item.get("published"),
                    "assignment_group_id": item.get("assignment_group_id"),
                }
                for item in data
            ]
        )

    def buscar_assignment(
        self,
        course_id: int | str,
        assignment_name: str,
    ) -> dict[str, Any] | None:
        """Busca un assignment por nombre exacto."""
        assignments = self._get(
            f"/api/v1/courses/{course_id}/assignments",
            params={"per_page": 100},
        )
        for assignment in assignments:
            if assignment.get("name") == assignment_name:
                return assignment
        return None

    def crear_assignment(
        self,
        course_id: int | str,
        spec: AssignmentSpec,
        create_group_if_missing: bool = False,
    ) -> dict[str, Any]:
        """Crea un assignment en Canvas usando la configuracion indicada."""
        group_id = self.obtener_assignment_group_id(
            course_id=course_id,
            group_name=spec.assignment_group_name,
            create_if_missing=create_group_if_missing,
        )
        return self._post(
            f"/api/v1/courses/{course_id}/assignments",
            spec.canvas_payload(assignment_group_id=group_id),
        )

    def asegurar_assignment(
        self,
        course_id: int | str,
        spec: AssignmentSpec,
        seccion: int | str | None = None,
        dry_run: bool = True,
        create_group_if_missing: bool = False,
    ) -> dict[str, Any]:
        """Crea el assignment si no existe. Nunca duplica por nombre exacto."""
        existente = self.buscar_assignment(course_id, spec.name)
        if existente is not None:
            return {
                "seccion": seccion,
                "course_id": course_id,
                "assignment": spec.name,
                "assignment_group": spec.assignment_group_name,
                "status": "exists",
                "assignment_id": existente.get("id"),
                "points_possible": existente.get("points_possible"),
                "published": existente.get("published"),
            }

        if dry_run:
            return {
                "seccion": seccion,
                "course_id": course_id,
                "assignment": spec.name,
                "assignment_group": spec.assignment_group_name,
                "status": "dry_run_create",
                "assignment_id": None,
                "points_possible": spec.points_possible,
                "published": spec.published,
                "payload": asdict(spec),
            }

        creado = self.crear_assignment(
            course_id=course_id,
            spec=spec,
            create_group_if_missing=create_group_if_missing,
        )
        return {
            "seccion": seccion,
            "course_id": course_id,
            "assignment": spec.name,
            "assignment_group": spec.assignment_group_name,
            "status": "created",
            "assignment_id": creado.get("id"),
            "points_possible": creado.get("points_possible"),
            "published": creado.get("published"),
        }


def asegurar_assignments_grupo(
    courses: dict[int, int],
    spec: AssignmentSpec,
    *,
    dry_run: bool = True,
    create_group_if_missing: bool = False,
    base_url: str | None = None,
    token: str | None = None,
) -> pd.DataFrame:
    """Asegura un assignment en todas las secciones de un grupo."""
    client = CanvasAdminClient(base_url=base_url, token=token)
    filas = []
    for seccion, course_id in courses.items():
        filas.append(
            client.asegurar_assignment(
                course_id=course_id,
                spec=spec,
                seccion=seccion,
                dry_run=dry_run,
                create_group_if_missing=create_group_if_missing,
            )
        )
    return pd.DataFrame(filas)


def asegurar_specs_grupo(
    courses: dict[int, int],
    specs: list[AssignmentSpec],
    *,
    dry_run: bool = True,
    create_group_if_missing: bool = False,
    base_url: str | None = None,
    token: str | None = None,
) -> pd.DataFrame:
    """Asegura varios assignments en todas las secciones de un grupo."""
    client = CanvasAdminClient(base_url=base_url, token=token)
    filas = []
    for seccion, course_id in courses.items():
        for spec in specs:
            filas.append(
                client.asegurar_assignment(
                    course_id=course_id,
                    spec=spec,
                    seccion=seccion,
                    dry_run=dry_run,
                    create_group_if_missing=create_group_if_missing,
                )
            )
    return pd.DataFrame(filas)


def preparar_examen_parcial_2026_1(
    config: dict,
    *,
    dry_run: bool = True,
    create_group_if_missing: bool = False,
    base_url: str | None = None,
    token: str | None = None,
) -> pd.DataFrame:
    """Prepara Simulacro EP en auditorios y Examen Parcial en aulas.

    ``dry_run=True`` no crea nada: solo reporta que se crearia. Cambiar a
    ``False`` cuando el plan haya sido revisado.
    """
    api_cfg = config["canvas_api"]
    resultados = []

    resultados.append(
        asegurar_assignments_grupo(
            api_cfg["courses_auditorio"],
            SIMULACRO_EP,
            dry_run=dry_run,
            create_group_if_missing=create_group_if_missing,
            base_url=base_url,
            token=token,
        )
    )
    resultados.append(
        asegurar_assignments_grupo(
            api_cfg["courses_aula"],
            EXAMEN_PARCIAL,
            dry_run=dry_run,
            create_group_if_missing=create_group_if_missing,
            base_url=base_url,
            token=token,
        )
    )

    return pd.concat(resultados, ignore_index=True)


def preparar_evaluaciones_aula(
    config: dict,
    numeros: list[int] | tuple[int, ...],
    *,
    dry_run: bool = True,
    create_group_if_missing: bool = False,
    base_url: str | None = None,
    token: str | None = None,
) -> pd.DataFrame:
    """Prepara Evaluaciones en Aula en las secciones de aula reducida."""
    api_cfg = config["canvas_api"]
    specs = [evaluacion_en_aula(numero) for numero in numeros]
    return asegurar_specs_grupo(
        api_cfg["courses_aula"],
        specs,
        dry_run=dry_run,
        create_group_if_missing=create_group_if_missing,
        base_url=base_url,
        token=token,
    )
