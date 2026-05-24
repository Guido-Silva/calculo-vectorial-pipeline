# Pipeline de Cálculo Vectorial — UTEC

Pipeline automatizado para procesar notas de **Canvas** y **Gradescope**, calcular evaluaciones continuas y subir resultados a **Google Sheets**. El repositorio también incluye utilidades operativas para administrar Canvas cuando hace falta crear assignments o publicar notas calculadas. Desarrollado para el curso CC1104 - Cálculo Vectorial en la Universidad de Ingeniería y Tecnología (UTEC).

---

## 📋 Descripción del proyecto

Este pipeline permite:
- **Ingestar** notas desde Canvas (CSV) y Gradescope (CSV) de forma automática
- **Mergear** las fuentes usando el código universitario como llave primaria (y correo como fallback)
- **Calcular** PT1, PT2, PEA1, PEA2, BPEA1, BPEA2, TA1, TA2, EP, EF y NF según las fórmulas del sistema de evaluación UTEC
- **Subir** los resultados al dashboard de Google Sheets del curso
- **Comparar** resultados entre ciclos académicos

Además, fuera del pipeline principal:
- **Administrar Canvas** para crear assignments o revisar grupos de tareas
- **Publicar notas calculadas a Canvas** cuando una evaluación final debe volver al gradebook

## Arquitectura conceptual

El repo tiene dos zonas con objetivos distintos:

1. **Pipeline principal**
   - Descarga datos desde Canvas
   - Los mergea con la base del curso
   - Calcula notas
   - Exporta resultados a CSV y Google Sheets

2. **Operaciones Canvas**
   - Acciones con efecto real sobre Canvas
   - Creación de assignments
   - Publicación manual de notas calculadas

Esta separación ayuda a que el notebook principal sea analítico y reproducible, mientras que las tareas operativas quedan encapsuladas en módulos y notebooks administrativos.

---

## 🗂️ Estructura del repositorio

```
calculo-vectorial-pipeline/
├── config/
│   ├── 2026-1.yaml          # Configuración del ciclo actual
│   └── 2025-2.yaml          # Configuración del ciclo anterior
├── src/
│   ├── __init__.py
│   ├── ingesta.py           # Carga de CSVs (Canvas + Gradescope)
│   ├── merge.py             # Unificación de fuentes por Código/Correo
│   ├── calculos.py          # Fórmulas de evaluación
│   ├── reporte.py           # Estadísticas y gráficas
│   ├── gdrive.py            # Integración con Google Sheets
│   ├── canvas_api.py        # Descarga de datos y cliente base de Canvas
│   ├── canvas_admin.py      # Creación de assignments y otras tareas administrativas
│   └── canvas_publish.py    # Publicación de notas calculadas a Canvas
├── notebooks/
│   ├── 2026-1_exploracion.ipynb     # Pipeline interactivo ciclo actual
│   ├── 2026-1_admin_canvas.ipynb    # Operaciones manuales/administrativas en Canvas
│   └── comparacion_ciclos.ipynb     # Comparación entre ciclos
├── data/                    # ⚠️ NO se sube a GitHub (ver nota de privacidad)
│   ├── 2026-1/
│   │   ├── raw/
│   │   │   ├── canvas/      # CSVs descargados de Canvas
│   │   │   └── gradescope/
│   │   │       ├── EA/      # CSVs de Evaluaciones en Aula
│   │   │       └── tareas/  # CSVs de tareas (T2, T3B, etc.)
│   │   ├── processed/       # DataFrames intermedios
│   │   └── output/          # Notas finales exportadas
│   └── 2025-2/
│       ├── raw/
│       │   ├── canvas/
│       │   └── gradescope/
│       ├── processed/
│       └── output/
├── credentials/             # ⚠️ NO se sube a GitHub
│   └── (service_account.json va aquí)
├── requirements.txt
└── README.md
```

---

## ⚙️ Requisitos

- Python 3.10+
- [uv](https://github.com/astral-sh/uv) (gestor de paquetes recomendado)
- Cuenta de Google Cloud con una Service Account habilitada

### Instalar dependencias

```bash
uv pip install -r requirements.txt
```

---

## 🔑 Configurar credenciales de Google

1. Crear un proyecto en [Google Cloud Console](https://console.cloud.google.com/)
2. Habilitar las APIs: **Google Sheets API** y **Google Drive API**
3. Crear una **Service Account** y descargar la clave JSON
4. Renombrar el archivo a `service_account.json` y colocarlo en la carpeta `credentials/`
5. Compartir el Google Sheet con el email de la Service Account (con permisos de editor)

```
credentials/
└── service_account.json   ← Nunca subir este archivo a GitHub
```

---

## 🚀 Cómo usar el pipeline

El pipeline está dividido en fases. Ejecutar el notebook correspondiente al ciclo:

```
notebooks/2026-1_exploracion.ipynb
```

### Fases del pipeline principal

| Fase | Descripción |
|------|-------------|
| 1. Ingesta | Carga CSVs de Canvas y Gradescope |
| 2. Merge | Unifica fuentes por Código universitario |
| 3. Cálculos | Calcula PT, PEA, BPEA, TA, EP, EF, NF |
| 4. Reporte | Estadísticas por sección y alumnos en riesgo |
| 5. Exportar | Guarda CSV local y/o actualiza Google Sheets |

### Operaciones fuera del pipeline principal

| Tarea | Dónde vive |
|------|-------------|
| Crear assignments en Canvas | `src/canvas_admin.py` y `notebooks/2026-1_admin_canvas.ipynb` |
| Publicar notas calculadas a Canvas | `src/canvas_publish.py` y `notebooks/2026-1_admin_canvas.ipynb` |

### Ejemplo de uso programático

```python
import yaml
import pandas as pd
from src.ingesta import load_canvas_csv, load_gradescope_ea
from src.merge import merge_con_fallback
from src.calculos import ejecutar_calculos
from src.gdrive import conectar_gspread, escribir_columnas_notas

# Cargar configuración del ciclo
with open("config/2026-1.yaml") as f:
    config = yaml.safe_load(f)

# Cargar datos base (dashboard de Notas)
df_base = pd.read_csv("data/2026-1/raw/Notas.csv", sep=";", encoding="latin-1")

# Cargar Canvas
df_canvas1 = load_canvas_csv("data/2026-1/raw/canvas/Teoria_1.csv", config)

# Mergear y calcular
df = merge_con_fallback(df_base, df_canvas1, columnas=["T1", "T3A", "T4"])
df = ejecutar_calculos(df, config)

# Subir a Google Sheets
gc = conectar_gspread("credentials/service_account.json")
escribir_columnas_notas(config["dashboard"]["sheet_id"], df, columnas=["EA1","EA2","EA3","PT1","TA1","NF"])
```

---

## 🔌 Canvas API (descarga automática de notas)

### Estrategia

Todo pasa por Canvas: las Tareas ya viven ahí y las notas de Gradescope (EAs y Tareas de Gradescope) se sincronizan a Canvas con **1 click** usando la integración LTI ya activa en UTEC (`GRADESCOPE_API`). El pipeline Python descarga todo desde un solo lugar.

```
Gradescope (corrección)
       ↓  "Post Grades to Canvas"  ← el docente hace click una vez por evaluación
Canvas Gradebook  (Tareas, EAs, …)
       ↓  Canvas REST API          ← fetch_canvas_grades_grupo() lo descarga todo
Google Sheets Dashboard
```

### Distribución de assignments por grupo de cursos

| Grupo | Secciones | Assignments |
|---|---|---|
| **Auditorios** | Teoría 1 (20189), Teoría 2 (20205) | Tareas + Actividades Previas |
| **Aulas** | Teoría 11–24 (20245–20252) | RC - Primera/Segunda Entrega + Evaluaciones en Aula 1–6 |

### Obtener `course_id`

| Dato | Cómo conseguirlo |
|---|---|
| `course_id` | URL del curso en Canvas: `.../courses/**123456**` |

Los assignments se buscan por **nombre exacto** en Canvas — no requieren ID numérico.

### Configurar el token de Canvas

1. Ir a **Canvas → Cuenta → Configuración → + Nuevo token de acceso**
2. Copiar el token generado
3. Crear un archivo `.env` en la raíz del proyecto (basarse en `.env.example`):

```bash
CANVAS_BASE_URL=https://utec.instructure.com
CANVAS_TOKEN=tu_token_aqui
```

> ⚠️ El archivo `.env` está en `.gitignore`. **Nunca** subirlo a GitHub.

### Linkear assignments de Gradescope a Canvas

Para que "Post Grades to Canvas" funcione con las EAs y Tareas de Gradescope:

1. Crear el assignment en **Canvas** (puede ser de tipo "Sin entrega" o "En papel").
2. Abrir el assignment en **Gradescope** → `Edit Assignment` → sección **LTI** → `Link to Canvas Assignment`.
3. Seleccionar el assignment creado en el paso 1.
4. Después de corregir: `Publish Grades` → `Post Grades to Canvas`.

### Ejemplo de uso

```python
import yaml, os
from dotenv import load_dotenv
from src.canvas_api import fetch_canvas_grades_grupo, CANVAS_A_PIPELINE

load_dotenv()
with open("config/2026-1.yaml") as f:
    config = yaml.safe_load(f)

api_cfg = config["canvas_api"]

# Descargar notas de auditorios (Tareas + APs)
df_auditorio = fetch_canvas_grades_grupo(
    courses=api_cfg["courses_auditorio"],
    assignment_names=api_cfg["assignments_auditorio"],
    nombre_a_col=CANVAS_A_PIPELINE,
)

# Descargar notas de aulas (EAs + RCs)
df_aula = fetch_canvas_grades_grupo(
    courses=api_cfg["courses_aula"],
    assignment_names=api_cfg["assignments_aula"],
    nombre_a_col=CANVAS_A_PIPELINE,
)
```

### Verificar nombres de assignments (diagnóstico)

Antes de configurar el pipeline, verificar que los nombres en Canvas coinciden exactamente:

```python
# Verificar nombres exactos de assignments antes de configurar
from src.canvas_api import listar_assignments_grupo
df_lista = listar_assignments_grupo(api_cfg["courses_aula"])
print(df_lista[["seccion", "nombre", "puntos_posibles"]])
```

---

## 🗓️ Ciclos soportados

| Ciclo | Archivo de configuración | Estado |
|-------|--------------------------|--------|
| 2026-1 | `config/2026-1.yaml` | ✅ Activo |
| 2025-2 | `config/2025-2.yaml` | 📦 Histórico |

---

## 🔒 Nota sobre privacidad

> **La carpeta `data/` NUNCA se sube a GitHub.**

Esta carpeta contiene datos personales de estudiantes (nombres, códigos, notas) que son información confidencial. Está incluida en el `.gitignore` junto con la carpeta `credentials/`.

Solo se mantienen en el repositorio los archivos `.gitkeep` vacíos para preservar la estructura de carpetas.

---

## 🛠️ Clonar y configurar localmente

```bash
# 1. Clonar el repositorio
git clone https://github.com/Guido-Silva/calculo-vectorial-pipeline.git
cd calculo-vectorial-pipeline

# 2. Instalar dependencias
uv pip install -r requirements.txt

# 3. Colocar credenciales de Google
cp /ruta/a/tu/service_account.json credentials/

# 4. Editar configuración del ciclo (NO subir el Sheet ID real)
# Abrir config/2026-1.yaml y reemplazar TU_SHEET_ID_AQUI

# 5. Colocar datos en data/2026-1/raw/
# - canvas/Teoria_1.csv (desde Canvas)
# - canvas/Teoria_2.csv (desde Canvas)
# - gradescope/EA/ (CSVs de EAs desde Gradescope)
# - gradescope/tareas/ (CSVs de tareas desde Gradescope)

# 6. Abrir el notebook de exploración
jupyter notebook notebooks/2026-1_exploracion.ipynb
```



