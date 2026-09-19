"""Geração headless e reutilizável dos gráficos do ensaio."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from io import BytesIO
from typing import Any, Iterable

import matplotlib

matplotlib.use("Agg", force=True)

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from ui.theme import COLORS

INSUFFICIENT_DATA_MESSAGE = "Dados insuficientes para gerar este gráfico."
INVALID_STATES = {
    "STALE",
    "INVALID",
    "INVALIDA",
    "INVÁLIDA",
    "MISSING",
    "AUSENTE",
    "DISCONNECTED",
    "DESCONECTADA",
}


@dataclass(frozen=True)
class ChartImage:
    key: str
    title: str
    image: BytesIO


class ChartService:
    """Constrói PNGs sem depender de widgets ou de uma sessão Qt ativa."""

    def __init__(
        self,
        max_points: int = 2500,
        dpi: int = 160,
        sync_tolerance_seconds: float = 1.05,
    ):
        self.max_points = max(50, max_points)
        self.dpi = max(100, dpi)
        self.sync_tolerance_seconds = max(0.0, sync_tolerance_seconds)

    @staticmethod
    def _frame(records: pd.DataFrame | Iterable[dict[str, Any]]) -> pd.DataFrame:
        if isinstance(records, pd.DataFrame):
            return records.copy()
        return pd.DataFrame(
            [dict(record) if hasattr(record, "keys") else record for record in records]
        )

    @staticmethod
    def _valid_mask(frame: pd.DataFrame, sensor: str) -> pd.Series:
        valid_column = f"{sensor}_valida"
        status_column = f"status_{sensor}"
        valid = (
            pd.to_numeric(frame[valid_column], errors="coerce").fillna(0).astype(bool)
            if valid_column in frame
            else pd.Series(True, index=frame.index, dtype=bool)
        )
        if status_column in frame:
            statuses = frame[status_column].fillna("").astype(str).str.upper()
            invalid = statuses.apply(lambda value: any(state in value for state in INVALID_STATES))
            valid &= ~invalid
        if "qualidade" in frame:
            qualities = frame["qualidade"].fillna("").astype(str).str.upper()
            invalid = qualities.apply(lambda value: any(state in value for state in INVALID_STATES))
            valid &= ~invalid
        return valid

    @staticmethod
    def _timestamps(frame: pd.DataFrame, sensor: str) -> pd.Series:
        column = f"timestamp_{sensor}"
        if column not in frame:
            column = "timestamp_computador"
        if column not in frame:
            return pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns]")
        return pd.to_datetime(frame[column], errors="coerce")

    def validated_sensor_series(
        self, records: pd.DataFrame | Iterable[dict[str, Any]], sensor: str
    ) -> pd.DataFrame:
        """Retorna a série integral; inválidos permanecem como lacunas NaN."""
        frame = self._frame(records)
        value_column = "pressao" if sensor == "pressao" else "vazao"
        if frame.empty or value_column not in frame:
            return pd.DataFrame(columns=["timestamp", "value", "valid"])
        result = pd.DataFrame(
            {
                "timestamp": self._timestamps(frame, sensor),
                "value": pd.to_numeric(frame[value_column], errors="coerce"),
                "valid": self._valid_mask(frame, sensor),
            }
        )
        result.loc[~result["valid"] | ~np.isfinite(result["value"]), "value"] = np.nan
        result = (
            result.dropna(subset=["timestamp"])
            .sort_values("timestamp", kind="stable")
            .reset_index(drop=True)
        )
        return result

    def plot_sensor_series(
        self, records: pd.DataFrame | Iterable[dict[str, Any]], sensor: str
    ) -> pd.DataFrame:
        """Retorna somente a representação reduzida usada para renderização."""
        return self._reduce(self.validated_sensor_series(records, sensor))

    def sensor_series(
        self, records: pd.DataFrame | Iterable[dict[str, Any]], sensor: str
    ) -> pd.DataFrame:
        """Compatibilidade: seleção validada sempre significa a série integral."""
        return self.validated_sensor_series(records, sensor)

    @staticmethod
    def valid_values(records: pd.DataFrame | Iterable[dict[str, Any]], sensor: str) -> pd.Series:
        return ChartService().validated_sensor_series(records, sensor)["value"].dropna()

    def combined_pairs(self, records: pd.DataFrame | Iterable[dict[str, Any]]) -> pd.DataFrame:
        """Seleciona somente pares persistidos, válidos e sincronizados."""
        frame = self._frame(records)
        required = {"pressao", "vazao"}
        if frame.empty or not required.issubset(frame.columns):
            return pd.DataFrame(columns=["timestamp", "pressure", "flow"])
        pressure_ts = (
            pd.to_datetime(frame["timestamp_pressao"], errors="coerce")
            if "timestamp_pressao" in frame
            else pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns]")
        )
        flow_ts = (
            pd.to_datetime(frame["timestamp_vazao"], errors="coerce")
            if "timestamp_vazao" in frame
            else pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns]")
        )
        pressure = pd.to_numeric(frame["pressao"], errors="coerce")
        flow = pd.to_numeric(frame["vazao"], errors="coerce")
        valid = self._valid_mask(frame, "pressao") & self._valid_mask(frame, "vazao")
        valid &= np.isfinite(pressure) & np.isfinite(flow)
        states = (
            frame["estado_comunicacao"].fillna("").astype(str).str.upper()
            if "estado_comunicacao" in frame
            else pd.Series("", index=frame.index)
        )
        schema = (
            pd.to_numeric(frame["versao_schema"], errors="coerce")
            if "versao_schema" in frame
            else pd.Series(float("nan"), index=frame.index)
        )
        legacy = schema.eq(0) | states.isin({"CONECTADO", "CONNECTED", "LEGACY_OK"})
        computer_ts = (
            pd.to_datetime(frame["timestamp_computador"], errors="coerce")
            if "timestamp_computador" in frame
            else pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns]")
        )
        # Bancos antigos podem ter apenas timestamp_computador. O fallback é
        # permitido exclusivamente para registros identificados como legados.
        pressure_ts = pressure_ts.where(pressure_ts.notna(), computer_ts.where(legacy))
        flow_ts = flow_ts.where(flow_ts.notna(), computer_ts.where(legacy))
        if "estado_comunicacao" in frame:
            valid &= states.eq("OK") | (
                legacy & states.isin({"CONECTADO", "CONNECTED", "LEGACY_OK", ""})
            )
        else:
            valid &= legacy
        valid &= pressure_ts.notna() & flow_ts.notna()
        deltas = (pressure_ts - flow_ts).abs().dt.total_seconds()
        valid &= deltas.le(self.sync_tolerance_seconds)
        result = pd.DataFrame(
            {
                "timestamp": pd.concat([pressure_ts, flow_ts], axis=1).max(axis=1),
                "pressure": pressure,
                "flow": flow,
            }
        )[valid]
        return result.sort_values("timestamp", kind="stable").reset_index(drop=True)

    def _reduce(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Reduz séries longas preservando início, fim, lacunas e extremos por bloco."""
        if len(frame) <= self.max_points:
            return frame.reset_index(drop=True)
        numeric = [c for c in frame.columns if c not in {"timestamp", "valid"}]
        bucket_count = max(1, self.max_points // 4)
        edges = np.linspace(0, len(frame), bucket_count + 1, dtype=int)
        keep = {0, len(frame) - 1}
        for start, end in zip(edges[:-1], edges[1:]):
            if end <= start:
                continue
            block = frame.iloc[start:end]
            keep.update({start, end - 1})
            for column in numeric:
                values = pd.to_numeric(block[column], errors="coerce")
                finite = values[np.isfinite(values)]
                if not finite.empty:
                    keep.add(int(finite.idxmin()))
                    keep.add(int(finite.idxmax()))
                missing = values[values.isna()]
                if not missing.empty:
                    keep.add(int(missing.index[0]))
        return frame.loc[sorted(keep)].reset_index(drop=True)

    @staticmethod
    def calculation_records(
        calculations: pd.DataFrame | Iterable[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        frame = ChartService._frame(calculations)
        records: list[dict[str, Any]] = []
        for record in frame.to_dict(orient="records"):
            try:
                inputs = record.get("entradas_json", {})
                results = record.get("resultados_json", {})
                if isinstance(inputs, str):
                    inputs = json.loads(inputs)
                if isinstance(results, str):
                    results = json.loads(results)
            except (TypeError, json.JSONDecodeError):
                continue
            records.append({**record, "inputs": inputs or {}, "results": results or {}})
        records.sort(key=lambda item: str(item.get("timestamp") or ""))
        return records

    @classmethod
    def klinkenberg_points(cls, record: dict[str, Any]) -> list[tuple[float, float]]:
        """Lê pontos atuais/legados sem avaliar divisões inválidas antecipadamente."""
        result = record.get("results") or {}
        inputs = record.get("inputs") or {}
        raw_points = result.get("points_used") or inputs.get("points") or []
        parsed: list[tuple[float, float]] = []
        for point in raw_points:
            if not isinstance(point, dict):
                continue
            inverse = point.get("inverse_pressure_kpa")
            if not cls._finite_positive(inverse):
                pressure = point.get("mean_pressure_kpa_abs", point.get("Pm"))
                if not cls._finite_positive(pressure):
                    continue
                inverse = 1.0 / float(pressure)
            permeability = point.get("permeability_md")
            if cls._finite_positive(permeability):
                parsed.append((float(inverse), float(permeability)))
        return parsed

    def _new_figure(self, title: str):
        fig, ax = plt.subplots(figsize=(7.2, 3.55), constrained_layout=True)
        fig.patch.set_facecolor("white")
        ax.set_title(title, color=COLORS["text"], fontsize=11, fontweight="bold")
        ax.grid(True, alpha=0.22, linewidth=0.7)
        ax.spines[["top", "right"]].set_visible(False)
        return fig, ax

    def _finish(self, fig, key: str, title: str) -> ChartImage:
        stream = BytesIO()
        try:
            fig.savefig(stream, format="png", dpi=self.dpi, bbox_inches="tight")
            stream.seek(0)
            return ChartImage(key, title, stream)
        finally:
            plt.close(fig)

    @staticmethod
    def _has_data(series: pd.DataFrame, column: str = "value", minimum: int = 1) -> bool:
        if series.empty or column not in series:
            return False
        values = pd.to_numeric(series[column], errors="coerce")
        return int(np.isfinite(values).sum()) >= minimum

    @staticmethod
    def _time_formatter(*series: pd.DataFrame) -> mdates.DateFormatter:
        timestamps = pd.concat(
            [item["timestamp"].dropna() for item in series if "timestamp" in item],
            ignore_index=True,
        )
        days = timestamps.dt.normalize().nunique() if not timestamps.empty else 0
        return mdates.DateFormatter("%d/%m %H:%M" if days > 1 else "%H:%M:%S")

    def sensor_time_chart(self, records, sensor: str, unit: str) -> ChartImage | None:
        names = {"pressao": "Pressão × tempo", "vazao": "Vazão × tempo"}
        series = self.plot_sensor_series(records, sensor)
        if not self._has_data(series):
            return None
        title = names[sensor]
        fig, ax = self._new_figure(title)
        color = COLORS["pressure" if sensor == "pressao" else "flow"]
        ax.plot(series["timestamp"], series["value"], color=color, linewidth=1.5)
        ax.set_xlabel("Data e hora")
        ax.set_ylabel(f"{'Pressão' if sensor == 'pressao' else 'Vazão'} ({unit})", color=color)
        ax.xaxis.set_major_formatter(self._time_formatter(series))
        fig.autofmt_xdate(rotation=25)
        return self._finish(fig, f"{sensor}_tempo", title)

    def combined_time_chart(self, records, pressure_unit: str, flow_unit: str) -> ChartImage | None:
        pressure = self.plot_sensor_series(records, "pressao")
        flow = self.plot_sensor_series(records, "vazao")
        if not self._has_data(pressure) or not self._has_data(flow):
            return None
        title = "Pressão e vazão × tempo"
        fig, left = self._new_figure(title)
        right = left.twinx()
        p_line = left.plot(
            pressure["timestamp"], pressure["value"], color=COLORS["pressure"], label="Pressão"
        )[0]
        f_line = right.plot(flow["timestamp"], flow["value"], color=COLORS["flow"], label="Vazão")[
            0
        ]
        left.set_xlabel("Data e hora")
        left.set_ylabel(f"Pressão ({pressure_unit})", color=COLORS["pressure"])
        right.set_ylabel(f"Vazão ({flow_unit})", color=COLORS["flow"])
        left.legend([p_line, f_line], ["Pressão", "Vazão"], loc="best")
        left.xaxis.set_major_formatter(self._time_formatter(pressure, flow))
        fig.autofmt_xdate(rotation=25)
        return self._finish(fig, "pressao_vazao_tempo", title)

    def flow_pressure_chart(self, records, pressure_unit: str, flow_unit: str) -> ChartImage | None:
        pairs = self._reduce(self.combined_pairs(records))
        if len(pairs) < 2:
            return None
        title = "Vazão × pressão"
        fig, ax = self._new_figure(title)
        ax.plot(
            pairs["pressure"],
            pairs["flow"],
            color=COLORS["accent"],
            marker="o",
            markersize=3,
            linewidth=1,
        )
        ax.set_xlabel(f"Pressão ({pressure_unit})")
        ax.set_ylabel(f"Vazão ({flow_unit})")
        return self._finish(fig, "vazao_pressao", title)

    def permeability_time_chart(self, calculations) -> ChartImage | None:
        records = self.calculation_records(calculations)
        points = []
        for record in records:
            value = record["results"].get("permeability_md")
            timestamp = pd.to_datetime(record.get("timestamp"), errors="coerce")
            if pd.notna(timestamp) and self._finite_positive(value):
                points.append((timestamp, float(value)))
        if not points:
            return None
        title = "Permeabilidade aparente × tempo"
        fig, ax = self._new_figure(title)
        ax.plot(*zip(*points), color=COLORS["accent"], marker="o", linewidth=1.2)
        ax.set_xlabel("Data e hora do cálculo")
        ax.set_ylabel("Permeabilidade aparente (mD)")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m %H:%M"))
        fig.autofmt_xdate(rotation=25)
        return self._finish(fig, "permeabilidade_tempo", title)

    def permeability_pressure_chart(self, calculations) -> ChartImage | None:
        points = []
        for record in self.calculation_records(calculations):
            result = record["results"]
            pressure, permeability = (
                result.get("mean_pressure_kpa_abs"),
                result.get("permeability_md"),
            )
            if self._finite_positive(pressure) and self._finite_positive(permeability):
                points.append((float(pressure), float(permeability)))
        if not points:
            return None
        points.sort()
        title = "Permeabilidade aparente × pressão média absoluta"
        fig, ax = self._new_figure(title)
        ax.plot(*zip(*points), color=COLORS["accent"], marker="o", linewidth=1.2)
        ax.set_xlabel("Pressão média absoluta (kPa abs)")
        ax.set_ylabel("Permeabilidade aparente (mD)")
        return self._finish(fig, "permeabilidade_pressao", title)

    def klinkenberg_chart(self, calculations) -> ChartImage | None:
        records = [
            item
            for item in self.calculation_records(calculations)
            if str(item.get("tipo", "")).lower() == "klinkenberg"
        ]
        if not records:
            return None
        selected = None
        for record in reversed(records):
            result = record["results"]
            inverse_points = self.klinkenberg_points(record)
            intercept = result.get("intrinsic_permeability_md", result.get("k_infinity_md"))
            slope = result.get("slope_md_kpa")
            if len(inverse_points) >= 2 and self._finite(intercept) and self._finite(slope):
                selected = (result, inverse_points, float(intercept), float(slope))
                break
        if selected is None:
            return None
        result, inverse_points, intercept, slope = selected
        xs = np.array([inverse for inverse, _ in inverse_points])
        ys = np.array([permeability for _, permeability in inverse_points])
        fit_x = np.linspace(xs.min(), xs.max(), 100)
        fit_y = intercept + slope * fit_x
        r2 = result.get("r_squared")
        slip = result.get("slip_factor_kpa")
        title = "Klinkenberg: permeabilidade × 1/Pm"
        fig, ax = self._new_figure(title)
        ax.scatter(xs, ys, color=COLORS["pressure"], label="Pontos experimentais", zorder=3)
        label = f"Ajuste: k∞={intercept:.5g} mD"
        if self._finite(slip):
            label += f"; b={float(slip):.5g} kPa"
        if self._finite(r2):
            label += f"; R²={float(r2):.4f}"
        ax.plot(fit_x, fit_y, color=COLORS["flow"], label=label)
        ax.set_xlabel("1/Pm (1/kPa)")
        ax.set_ylabel("Permeabilidade aparente (mD)")
        ax.legend(fontsize=8)
        return self._finish(fig, "klinkenberg", title)

    @staticmethod
    def _finite(value: Any) -> bool:
        try:
            return math.isfinite(float(value))
        except (TypeError, ValueError):
            return False

    @classmethod
    def _finite_positive(cls, value: Any) -> bool:
        return cls._finite(value) and float(value) > 0

    def generate_all(
        self,
        measurements,
        calculations,
        pressure_unit: str = "psi",
        flow_unit: str = "NL/min",
    ) -> dict[str, ChartImage | None]:
        return {
            "pressao_tempo": self.sensor_time_chart(measurements, "pressao", pressure_unit),
            "vazao_tempo": self.sensor_time_chart(measurements, "vazao", flow_unit),
            "pressao_vazao_tempo": self.combined_time_chart(measurements, pressure_unit, flow_unit),
            "vazao_pressao": self.flow_pressure_chart(measurements, pressure_unit, flow_unit),
            "permeabilidade_tempo": self.permeability_time_chart(calculations),
            "permeabilidade_pressao": self.permeability_pressure_chart(calculations),
            "klinkenberg": self.klinkenberg_chart(calculations),
        }
