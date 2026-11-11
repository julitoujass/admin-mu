from pydantic import BaseModel, ConfigDict
from typing import List, Optional
from datetime import date

# Request Query Parameters (Standardized for Reusability)
class FiltroFechaBase(BaseModel):
    fecha_inicio: Optional[date] = None
    fecha_fin: Optional[date] = None

# 1. Ventas por Fecha Reporte
class VentaDia(BaseModel):
    fecha: date
    total: float
    cantidad_ventas: int

class VentasTotalesReporte(BaseModel):
    total_ingresos: float
    cantidad_operaciones: int
    ventas_por_dia: List[VentaDia]

    model_config = ConfigDict(from_attributes=True)

# 2. Productos Más Vendidos
class ProductoTopReporte(BaseModel):
    variante_id: str
    nombre_producto: str
    talle: Optional[str] = None
    color: Optional[str] = None
    cantidad_vendida: int
    ingresos_generados: float

# 3. Resumen y Cierre de Cajas
class CajaResumenDiario(BaseModel):
    fecha: date
    sesiones_abiertas: int
    monto_inicial_total: float
    ingresos: float
    egresos: float
    monto_real_efectivo_total: float
    diferencia_esperado_vs_real: float

class CajaResumenReporte(BaseModel):
    resumen_diario: List[CajaResumenDiario]
    diferencia_total_periodo: float
    
    model_config = ConfigDict(from_attributes=True)
