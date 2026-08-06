from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from statistics import mean, pstdev
from typing import Iterable


DARCY_M2 = 9.869233e-13

# Valores de referência aproximados a 20 °C; a interface permite sobrescrever.
GAS_PROPERTIES: dict[str, dict[str, float | str]] = {
    "Helio": {"nome": "Hélio", "viscosidade_upa_s": 19.60, "massa_molar_g_mol": 4.0026},
    "Nitrogenio": {"nome": "Nitrogênio", "viscosidade_upa_s": 17.57, "massa_molar_g_mol": 28.0134},
    "Ar": {"nome": "Ar", "viscosidade_upa_s": 18.13, "massa_molar_g_mol": 28.965},
    "Argonio": {"nome": "Argônio", "viscosidade_upa_s": 22.23, "massa_molar_g_mol": 39.948},
    "CO2": {"nome": "Dióxido de carbono", "viscosidade_upa_s": 14.68, "massa_molar_g_mol": 44.0095},
}


def pressure_to_kpa(value: float, unit: str) -> float:
    factors = {"kPa": 1.0, "bar": 100.0, "MPa": 1000.0, "psi": 6.894757293}
    try:
        return value * factors[unit]
    except KeyError as exc:
        raise ValueError(f"Unidade de pressão não suportada: {unit}") from exc


def absolute_pressure_kpa(value: float, unit: str, reference: str, atmospheric_kpa: float) -> float:
    pressure = pressure_to_kpa(value, unit)
    if reference.lower().startswith("manom"):
        pressure += atmospheric_kpa
    if pressure <= 0:
        raise ValueError("A pressão absoluta precisa ser maior que zero")
    return pressure


def cylindrical_volume_cm3(length_mm: float, diameter_mm: float) -> float:
    if length_mm <= 0 or diameter_mm <= 0:
        raise ValueError("Comprimento e diâmetro precisam ser maiores que zero")
    return math.pi * (diameter_mm / 10.0) ** 2 * (length_mm / 10.0) / 4.0


@dataclass(frozen=True)
class BoyleCycleResult:
    free_volume_cm3: float
    skeletal_volume_cm3: float
    pore_volume_cm3: float | None
    porosity_percent: float | None
    skeletal_density_g_cm3: float | None
    bulk_density_g_cm3: float | None
    solid_fraction_percent: float | None

    def as_dict(self) -> dict[str, float | None]:
        return asdict(self)


@dataclass(frozen=True)
class BoyleSummary:
    cycles: int
    valid_cycles: int
    skeletal_volume_mean_cm3: float
    skeletal_volume_stddev_cm3: float
    coefficient_variation_percent: float
    pore_volume_mean_cm3: float | None
    porosity_mean_percent: float | None
    skeletal_density_g_cm3: float | None
    bulk_density_g_cm3: float | None
    solid_fraction_percent: float | None
    repeatability_ok: bool
    cycle_results: tuple[BoyleCycleResult, ...]

    def as_dict(self) -> dict:
        result = asdict(self)
        result["cycle_results"] = [cycle.as_dict() for cycle in self.cycle_results]
        return result


def calculate_boyle_cycle(
    *,
    sample_chamber_volume_cm3: float,
    expansion_volume_cm3: float,
    initial_sample_pressure_kpa_abs: float,
    equilibrium_pressure_kpa_abs: float,
    initial_expansion_pressure_kpa_abs: float,
    bulk_volume_cm3: float | None = None,
    sample_mass_g: float | None = None,
    temperature_initial_k: float = 293.15,
    temperature_equilibrium_k: float = 293.15,
    temperature_expansion_k: float = 293.15,
    z_initial: float = 1.0,
    z_equilibrium: float = 1.0,
    z_expansion: float = 1.0,
) -> BoyleCycleResult:
    """Calcula o volume deslocado após expansão da câmara da amostra.

    A câmara de amostra (volume livre desconhecido) começa em P1 e expande
    para uma câmara conhecida inicialmente em P0, atingindo P2.
    Pressões devem ser absolutas.
    """
    positives = {
        "volume da câmara": sample_chamber_volume_cm3,
        "volume de expansão": expansion_volume_cm3,
        "P1": initial_sample_pressure_kpa_abs,
        "P2": equilibrium_pressure_kpa_abs,
        "P0": initial_expansion_pressure_kpa_abs,
        "T1": temperature_initial_k,
        "T2": temperature_equilibrium_k,
        "T0": temperature_expansion_k,
        "Z1": z_initial,
        "Z2": z_equilibrium,
        "Z0": z_expansion,
    }
    if any(value <= 0 for value in positives.values()):
        invalid = next(name for name, value in positives.items() if value <= 0)
        raise ValueError(f"{invalid} precisa ser maior que zero")
    p1_term = initial_sample_pressure_kpa_abs / (z_initial * temperature_initial_k)
    p2_term = equilibrium_pressure_kpa_abs / (z_equilibrium * temperature_equilibrium_k)
    p0_term = initial_expansion_pressure_kpa_abs / (z_expansion * temperature_expansion_k)
    denominator = p1_term - p2_term
    if denominator <= 0 or p2_term <= p0_term:
        raise ValueError("As pressões precisam obedecer P1 > P2 > P0 após correções de T e Z")
    free_volume = expansion_volume_cm3 * (p2_term - p0_term) / denominator
    skeletal_volume = sample_chamber_volume_cm3 - free_volume
    if skeletal_volume <= 0 or skeletal_volume >= sample_chamber_volume_cm3:
        raise ValueError("O volume calculado é incompatível com o volume da câmara")

    pore_volume = porosity = bulk_density = solid_fraction = None
    if bulk_volume_cm3 is not None:
        if bulk_volume_cm3 <= 0:
            raise ValueError("O volume geométrico precisa ser maior que zero")
        pore_volume = bulk_volume_cm3 - skeletal_volume
        if pore_volume < 0:
            raise ValueError("O volume esquelético não pode exceder o volume geométrico")
        porosity = pore_volume / bulk_volume_cm3 * 100.0
        solid_fraction = skeletal_volume / bulk_volume_cm3 * 100.0
        if sample_mass_g is not None and sample_mass_g > 0:
            bulk_density = sample_mass_g / bulk_volume_cm3
    skeletal_density = None
    if sample_mass_g is not None:
        if sample_mass_g <= 0:
            raise ValueError("A massa da amostra precisa ser maior que zero")
        skeletal_density = sample_mass_g / skeletal_volume
    return BoyleCycleResult(
        free_volume, skeletal_volume, pore_volume, porosity,
        skeletal_density, bulk_density, solid_fraction,
    )


def summarize_boyle_cycles(
    cycle_results: Iterable[BoyleCycleResult], repeatability_limit_percent: float = 0.5
) -> BoyleSummary:
    cycles = tuple(cycle_results)
    if not cycles:
        raise ValueError("Adicione ao menos um ciclo de expansão")
    volumes = [cycle.skeletal_volume_cm3 for cycle in cycles]
    average_volume = mean(volumes)
    deviation = pstdev(volumes) if len(volumes) > 1 else 0.0
    cv = deviation / average_volume * 100.0

    def average_optional(name: str) -> float | None:
        values = [getattr(cycle, name) for cycle in cycles]
        valid = [value for value in values if value is not None]
        return mean(valid) if valid else None

    return BoyleSummary(
        cycles=len(cycles),
        valid_cycles=len(cycles),
        skeletal_volume_mean_cm3=average_volume,
        skeletal_volume_stddev_cm3=deviation,
        coefficient_variation_percent=cv,
        pore_volume_mean_cm3=average_optional("pore_volume_cm3"),
        porosity_mean_percent=average_optional("porosity_percent"),
        skeletal_density_g_cm3=average_optional("skeletal_density_g_cm3"),
        bulk_density_g_cm3=average_optional("bulk_density_g_cm3"),
        solid_fraction_percent=average_optional("solid_fraction_percent"),
        repeatability_ok=cv <= repeatability_limit_percent,
        cycle_results=cycles,
    )


@dataclass(frozen=True)
class PermeabilityResult:
    permeability_m2: float
    permeability_darcy: float
    permeability_md: float
    pressure_drop_kpa: float
    mean_pressure_kpa_abs: float
    superficial_velocity_m_s: float
    pressure_gradient_pa_m: float

    def as_dict(self) -> dict[str, float]:
        return asdict(self)


def calculate_gas_permeability(
    *,
    flow_l_min: float,
    viscosity_upa_s: float,
    length_mm: float,
    diameter_mm: float,
    inlet_pressure_kpa_abs: float,
    outlet_pressure_kpa_abs: float,
    flow_reference_pressure_kpa_abs: float | None = None,
) -> PermeabilityResult:
    """Darcy compressível isotérmico; vazão referida à pressão informada."""
    if min(flow_l_min, viscosity_upa_s, length_mm, diameter_mm) <= 0:
        raise ValueError("Vazão, viscosidade, comprimento e diâmetro devem ser positivos")
    if inlet_pressure_kpa_abs <= outlet_pressure_kpa_abs or outlet_pressure_kpa_abs <= 0:
        raise ValueError("A pressão de entrada absoluta deve ser maior que a de saída")
    reference_pressure = flow_reference_pressure_kpa_abs or outlet_pressure_kpa_abs
    if reference_pressure <= 0:
        raise ValueError("A pressão de referência da vazão precisa ser positiva")
    flow_m3_s = flow_l_min / 1000.0 / 60.0
    viscosity_pa_s = viscosity_upa_s * 1e-6
    length_m = length_mm / 1000.0
    diameter_m = diameter_mm / 1000.0
    area_m2 = math.pi * diameter_m**2 / 4.0
    pin_pa = inlet_pressure_kpa_abs * 1000.0
    pout_pa = outlet_pressure_kpa_abs * 1000.0
    pref_pa = reference_pressure * 1000.0
    permeability = (
        2.0 * viscosity_pa_s * length_m * flow_m3_s * pref_pa
        / (area_m2 * (pin_pa**2 - pout_pa**2))
    )
    return PermeabilityResult(
        permeability_m2=permeability,
        permeability_darcy=permeability / DARCY_M2,
        permeability_md=permeability / DARCY_M2 * 1000.0,
        pressure_drop_kpa=inlet_pressure_kpa_abs - outlet_pressure_kpa_abs,
        mean_pressure_kpa_abs=(inlet_pressure_kpa_abs + outlet_pressure_kpa_abs) / 2.0,
        superficial_velocity_m_s=flow_m3_s / area_m2,
        pressure_gradient_pa_m=(pin_pa - pout_pa) / length_m,
    )


@dataclass(frozen=True)
class KlinkenbergResult:
    intrinsic_permeability_md: float
    slip_factor_kpa: float
    slope_md_kpa: float
    r_squared: float
    points: int

    def as_dict(self) -> dict[str, float | int]:
        return asdict(self)


def calculate_klinkenberg(points: Iterable[tuple[float, float]]) -> KlinkenbergResult:
    """Ajusta k_aparente = k_infinito + inclinação / pressão_média."""
    values = list(points)
    if len(values) < 2:
        raise ValueError("São necessários ao menos dois pontos de pressão e permeabilidade")
    if any(pressure <= 0 or permeability <= 0 for pressure, permeability in values):
        raise ValueError("Pressões absolutas e permeabilidades precisam ser positivas")
    xs = [1.0 / pressure for pressure, _ in values]
    ys = [permeability for _, permeability in values]
    x_mean, y_mean = mean(xs), mean(ys)
    denominator = sum((x - x_mean) ** 2 for x in xs)
    if denominator == 0:
        raise ValueError("Use pressões médias distintas")
    slope = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys)) / denominator
    intercept = y_mean - slope * x_mean
    if intercept <= 0:
        raise ValueError("O ajuste resultou em permeabilidade intrínseca não positiva")
    residual = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(xs, ys))
    total = sum((y - y_mean) ** 2 for y in ys)
    r_squared = 1.0 - residual / total if total > 0 else 1.0
    return KlinkenbergResult(intercept, slope / intercept, slope, r_squared, len(values))
