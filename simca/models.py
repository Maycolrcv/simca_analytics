"""Modelos de datos compartidos entre extracción, unificación y UI."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

APROBADO_MIN = 3.0
SEMESTRE_ELECTIVAS = 0   # columna «Electivas» del programa (el pensum no trae semestre para ellas)
SEMESTRE_FISH = -2       # columna «Electivas Fish»


@dataclass
class Requisito:
    id: str | None
    codigo: str | None
    nombre: str


@dataclass
class MateriaPensum:
    id: str                 # ID interno SIMCA (== "ID Materia" en la historia académica)
    codigo: str             # código del pensum (A25014, M33956, ...)
    nombre: str
    creditos: int
    semestre: int           # 0 = electivas / sin semestre
    prerrequisitos: list[Requisito] = field(default_factory=list)
    correquisitos: list[Requisito] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MateriaPensum":
        data = dict(data)
        data["prerrequisitos"] = [Requisito(**r) for r in data.get("prerrequisitos", [])]
        data["correquisitos"] = [Requisito(**r) for r in data.get("correquisitos", [])]
        return cls(**data)


@dataclass
class RegistroNota:
    periodo: str
    id: str
    nombre: str
    creditos: int | None
    semestre_cursado: int | None
    nota: float | None           # nota original (puede ser < 3 si luego se habilitó)
    definitiva: float | None     # ÚNICA nota que decide aprobación
    habilitacion: float | None = None
    tipo: str = ""               # p. ej. "HABILITACION"

    @property
    def aprobada(self) -> bool:
        return self.definitiva is not None and self.definitiva >= APROBADO_MIN

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RegistroNota":
        validos = cls.__dataclass_fields__.keys()  # tolera snapshots de versiones anteriores/futuras
        return cls(**{k: v for k, v in data.items() if k in validos})


@dataclass
class Horario:
    dia: str
    horario: str
    salon: str = ""
    ubicacion: str = ""


@dataclass
class MateriaMatriculada:
    periodo: str
    codigo: str                   # código del pensum (31605, M32511, ...)
    nombre: str
    semestre: int | None = None   # vacío en electivas/optativas
    seccion: str = ""
    id_grupo: str = ""
    docentes: str = ""
    repeticion: int = 0
    horarios: list[Horario] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MateriaMatriculada":
        data = dict(data)
        data["horarios"] = [Horario(**h) for h in data.get("horarios", [])]
        return cls(**data)
