from datetime import date
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


# Request Query Parameters (Standardized for Reusability)
class FiltroFechaBase(BaseModel):
    fecha_inicio: Optional[date] = None
    fecha_fin: Optional[date] = None


# 1. Sales by date
class VentaDia(BaseModel):
    fecha: date
    # Net of the refunds registered that day.
    total: float
    bruto: float = 0
    devoluciones: float = 0
    cantidad_ventas: int


class VentasTotalesReporte(BaseModel):
    # NET revenue: gross sales minus refunds (by return date).
    total_ingresos: float
    total_bruto: float = 0
    total_devoluciones: float = 0
    cantidad_operaciones: int
    ventas_por_dia: List[VentaDia]

    model_config = ConfigDict(from_attributes=True)


# 2. Best-selling products
class ProductoTopReporte(BaseModel):
    variante_id: str
    nombre_producto: str
    talle: Optional[str] = None
    color: Optional[str] = None
    cantidad_vendida: int
    ingresos_generados: float


# 3. Cash sessions summary
class CajaResumenDiario(BaseModel):
    fecha: date
    sesiones_abiertas: int
    monto_inicial_total: float
    ventas_efectivo: float = 0
    ingresos: float
    egresos: float
    monto_real_efectivo_total: float
    diferencia_esperado_vs_real: float


class CajaResumenReporte(BaseModel):
    resumen_diario: List[CajaResumenDiario]
    diferencia_total_periodo: float

    model_config = ConfigDict(from_attributes=True)
