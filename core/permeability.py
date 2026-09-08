"""Cálculos de permeabilidade para gás compressível e Klinkenberg."""
from __future__ import annotations
import math
from dataclasses import asdict, dataclass
from statistics import mean
from typing import Iterable

DARCY_M2 = 9.869233e-13
GAS_PROPERTIES = {"Helio":{"nome":"Hélio","viscosidade_upa_s":19.60},"Nitrogenio":{"nome":"Nitrogênio","viscosidade_upa_s":17.57},"Ar":{"nome":"Ar","viscosidade_upa_s":18.13},"Argonio":{"nome":"Argônio","viscosidade_upa_s":22.23},"CO2":{"nome":"Dióxido de carbono","viscosidade_upa_s":14.68}}

def pressure_to_kpa(value: float, unit: str) -> float:
    try: return value * {"kPa":1., "bar":100., "MPa":1000., "psi":6.894757293}[unit]
    except KeyError as exc: raise ValueError(f"Unidade de pressão não suportada: {unit}") from exc
def absolute_pressure_kpa(value: float, unit: str, reference: str, atmospheric_kpa: float) -> float:
    result = pressure_to_kpa(value, unit) + (atmospheric_kpa if reference.lower().startswith("manom") else 0.)
    if result <= 0: raise ValueError("A pressão absoluta precisa ser maior que zero")
    return result
def cylindrical_volume_cm3(length_mm: float, diameter_mm: float) -> float:
    if length_mm <= 0 or diameter_mm <= 0: raise ValueError("Comprimento e diâmetro precisam ser maiores que zero")
    return math.pi * (diameter_mm / 10) ** 2 * (length_mm / 10) / 4

@dataclass(frozen=True)
class PermeabilityResult:
    permeability_m2: float; permeability_darcy: float; permeability_md: float; pressure_drop_kpa: float; mean_pressure_kpa_abs: float; superficial_velocity_m_s: float; pressure_gradient_pa_m: float
    def as_dict(self) -> dict[str, float]: return asdict(self)

def calculate_gas_permeability(*, flow_l_min: float, viscosity_upa_s: float, length_mm: float, diameter_mm: float, inlet_pressure_kpa_abs: float, outlet_pressure_kpa_abs: float, flow_reference_pressure_kpa_abs: float | None = None) -> PermeabilityResult:
    """Darcy isotérmico compressível: k=2μLQref·Pref/[A(Pin²-Pout²)], em SI."""
    if min(flow_l_min, viscosity_upa_s, length_mm, diameter_mm) <= 0: raise ValueError("Vazão, viscosidade, comprimento e diâmetro devem ser positivos")
    if inlet_pressure_kpa_abs <= outlet_pressure_kpa_abs or outlet_pressure_kpa_abs <= 0: raise ValueError("A pressão de entrada absoluta deve ser maior que a de saída")
    reference = flow_reference_pressure_kpa_abs or outlet_pressure_kpa_abs
    if reference <= 0: raise ValueError("A pressão de referência da vazão precisa ser positiva")
    q, mu, length, diameter = flow_l_min / 60000, viscosity_upa_s * 1e-6, length_mm / 1000, diameter_mm / 1000
    area = math.pi * diameter**2 / 4; pin, pout, pref = inlet_pressure_kpa_abs*1000, outlet_pressure_kpa_abs*1000, reference*1000
    k = 2*mu*length*q*pref / (area*(pin**2-pout**2))
    return PermeabilityResult(k, k/DARCY_M2, k/DARCY_M2*1000, inlet_pressure_kpa_abs-outlet_pressure_kpa_abs, (inlet_pressure_kpa_abs+outlet_pressure_kpa_abs)/2, q/area, (pin-pout)/length)

@dataclass(frozen=True)
class KlinkenbergResult:
    intrinsic_permeability_md: float; slip_factor_kpa: float; slope_md_kpa: float; r_squared: float; points: int
    def as_dict(self) -> dict[str, float | int]: return asdict(self)
def calculate_klinkenberg(points: Iterable[tuple[float, float]]) -> KlinkenbergResult:
    values=list(points)
    if len(values)<2: raise ValueError("São necessários ao menos dois pontos de pressão e permeabilidade")
    if any(p<=0 or k<=0 for p,k in values): raise ValueError("Pressões absolutas e permeabilidades precisam ser positivas")
    xs,ys=[1/p for p,_ in values],[k for _,k in values]; xm,ym=mean(xs),mean(ys); d=sum((x-xm)**2 for x in xs)
    if d==0: raise ValueError("Use pressões médias distintas")
    slope=sum((x-xm)*(y-ym) for x,y in zip(xs,ys))/d; intercept=ym-slope*xm
    if intercept<=0: raise ValueError("O ajuste resultou em permeabilidade intrínseca não positiva")
    total=sum((y-ym)**2 for y in ys); residual=sum((y-(intercept+slope*x))**2 for x,y in zip(xs,ys))
    return KlinkenbergResult(intercept,slope/intercept,slope,1-residual/total if total else 1.,len(values))
