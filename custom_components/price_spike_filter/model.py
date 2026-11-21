"""Pure forecast parsing and configurable price filtering."""

import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from .const import MAX_POINTS

NUMERIC_RANGES = {
    "preserve_hours": (0.0, 48.0),
    "midpoint_hours": (0.1, 168.0),
    "transition_hours": (0.1, 48.0),
    "minimum_retention": (0.0, 1.0),
    "baseline_window_hours": (0.5, 72.0),
    "spike_scale": (0.001, 100.0),
    "max_suppression": (0.0, 1.0),
    "max_source_age_minutes": (1.0, 1440.0),
}


class EarlyObservationError(ValueError):
    """A slightly early observation has replaced the forecast covering now."""


@dataclass(frozen=True, slots=True)
class Settings:
    """An operator-selected filtering policy, rather than a probability model."""

    enabled: bool = True
    preserve_hours: float = 1.0
    midpoint_hours: float = 12.0
    transition_hours: float = 2.0
    minimum_retention: float = 0.0
    baseline_window_hours: float = 6.0
    spike_scale: float = 0.1
    max_suppression: float = 0.9
    spike_direction: str = "positive"
    max_source_age_minutes: float = 30.0

    def __post_init__(self) -> None:
        for name, (minimum, maximum) in NUMERIC_RANGES.items():
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be numeric")
            if not math.isfinite(value) or not minimum <= value <= maximum:
                raise ValueError(f"{name} is outside its supported range")
        if not isinstance(self.enabled, bool):
            raise ValueError("enabled must be a boolean")
        if self.midpoint_hours <= self.preserve_hours:
            raise ValueError("midpoint_hours must exceed preserve_hours")
        if self.spike_direction not in ("positive", "negative", "both"):
            raise ValueError("Invalid spike direction")

    @classmethod
    def from_options(cls, options: Mapping) -> "Settings":
        defaults = asdict(cls())
        return cls(**{name: options.get(name, value) for name, value in defaults.items()})


@dataclass(frozen=True, slots=True)
class Point:
    start: datetime
    end: datetime
    value: float


@dataclass(frozen=True, slots=True)
class Snapshot:
    current_price: float
    points: tuple[Point, ...]
    current_price_estimated: bool = False


@dataclass(frozen=True, slots=True)
class Result:
    current_price: float
    raw: tuple[Point, ...]
    filtered: tuple[Point, ...]
    baseline: tuple[Point, ...]
    current_price_estimated: bool = False

    @property
    def changed_intervals(self) -> int:
        return sum(
            abs(raw.value - filtered.value) > 1e-9 for raw, filtered in zip(self.raw, self.filtered, strict=True)
        )

    @property
    def largest_adjustment(self) -> float:
        return max(abs(raw.value - filtered.value) for raw, filtered in zip(self.raw, self.filtered, strict=True))


def parse_time(value: object) -> datetime:
    """Require an unambiguous timezone-aware timestamp."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("Invalid forecast timestamp") from error
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Forecast timestamps must include a timezone")
    return value.astimezone(UTC)


def finite_price(value: object) -> float:
    if isinstance(value, bool):
        raise ValueError("Invalid price")
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError("Invalid price") from error
    if not math.isfinite(number) or abs(number) > 1_000_000:
        raise ValueError("Nonfinite or implausibly large price")
    return number


def parse_source(state: str, attributes: Mapping, now: datetime) -> Snapshot:
    """Read the HAEO time/value format published by Amber Express."""
    units = {"$/kWh": 1.0, "AUD/kWh": 1.0, "c/kWh": 0.01, "¢/kWh": 0.01}
    unit = attributes.get("unit_of_measurement")
    if not isinstance(unit, str) or unit not in units:
        raise ValueError("Source must use $/kWh, AUD/kWh, c/kWh or ¢/kWh")
    scale = units[unit]
    current = finite_price(state) * scale
    forecast = attributes.get("forecast")
    if not isinstance(forecast, (list, tuple)) or not 1 <= len(forecast) <= MAX_POINTS:
        raise ValueError(f"Source needs 1–{MAX_POINTS} forecast points")
    values = []
    for item in forecast:
        if not isinstance(item, Mapping) or "time" not in item or "value" not in item:
            raise ValueError("Source forecast needs time/value records")
        values.append((parse_time(item["time"]), finite_price(item["value"]) * scale, item.get("end_time")))
    values.sort(key=lambda item: item[0])
    if any(left[0] >= right[0] for left, right in zip(values, values[1:])):
        raise ValueError("Duplicate forecast timestamps")
    points = []
    for index, (start, value, explicit_end) in enumerate(values):
        if explicit_end is not None:
            end = parse_time(explicit_end)
        elif index + 1 < len(values):
            end = values[index + 1][0]
        elif attributes.get("forecast_end") is not None:
            end = parse_time(attributes["forecast_end"])
        elif len(values) > 1:
            end = start + (start - values[index - 1][0])
        elif attributes.get("end_time") is not None:
            end = parse_time(attributes["end_time"])
        else:
            raise ValueError("A single forecast point needs an interval end")
        if end <= start:
            raise ValueError("Forecast interval has no positive duration")
        points.append(Point(start, end, value))

    estimated = False
    # Use an observation only inside the interval it describes. After rollover,
    # a still-fresh source forecast can cover now while Amber publishes its update.
    if attributes.get("start_time") is not None and attributes.get("end_time") is not None:
        current_start = parse_time(attributes["start_time"])
        current_end = parse_time(attributes["end_time"])
        if current_end <= current_start:
            raise ValueError("Source current-price interval is invalid")
        if current_start <= now < current_end:
            remaining = []
            for point in points:
                if point.end <= current_start or point.start >= current_end:
                    remaining.append(point)
                elif point.end > current_end:
                    remaining.append(Point(current_end, point.end, point.value))
            points = [Point(current_start, current_end, current), *remaining]
            points.sort(key=lambda point: point.start)
        else:
            active = next((point for point in points if point.start <= now < point.end), None)
            if active is None:
                if now < current_start <= now + timedelta(minutes=1) and all(
                    left.end == right.start for left, right in zip(points, points[1:])
                ):
                    raise EarlyObservationError("Source observation arrived before its interval starts")
                raise ValueError("Source forecast does not cover the current time during interval rollover")
            current = active.value
            estimated = True
    else:
        points = [
            Point(point.start, point.end, current) if point.start <= now < point.end else point for point in points
        ]
    points = [point for point in points if point.end > now]
    if not points:
        raise ValueError("Source forecast has expired")
    if not points[0].start <= now < points[0].end:
        raise ValueError("Source forecast does not cover the current time")
    if any(left.end != right.start for left, right in zip(points, points[1:])):
        raise ValueError("Source forecast has gaps or overlapping intervals")
    return Snapshot(current, tuple(points), estimated)


def weighted_median(values: list[tuple[float, float]]) -> float:
    """Compute a duration-weighted median without averaging an extreme outlier."""
    ordered = sorted(values)
    halfway = sum(weight for _, weight in ordered) / 2
    accumulated = 0.0
    for value, weight in ordered:
        accumulated += weight
        if accumulated >= halfway:
            return value
    return ordered[-1][0]


def filter_forecast(snapshot: Snapshot, now: datetime, settings: Settings) -> Result:
    """Filter future deviations around a robust local baseline."""
    half_window = timedelta(hours=settings.baseline_window_hours / 2)
    raw = snapshot.points
    baselines = []
    filtered = []
    for point in raw:
        center = point.start + (point.end - point.start) / 2
        left, right = center - half_window, center + half_window
        neighbors = [
            (other.value, (min(right, other.end) - max(left, other.start)).total_seconds())
            for other in raw
            if other.start < right and other.end > left
        ]
        baseline = weighted_median(neighbors)
        baselines.append(Point(point.start, point.end, baseline))
        hours = (point.start - now).total_seconds() / 3600
        value = point.value
        if settings.enabled and hours > settings.preserve_hours:

            def logistic(lead: float) -> float:
                exponent = max(-700, min(700, (lead - settings.midpoint_hours) / settings.transition_hours))
                return 1 / (1 + math.exp(exponent))

            retention = settings.minimum_retention + (1 - settings.minimum_retention) * (
                logistic(hours) / logistic(settings.preserve_hours)
            )
            deviation = value - baseline
            eligible = (
                settings.spike_direction == "both"
                or settings.spike_direction == "positive"
                and deviation > 0
                or settings.spike_direction == "negative"
                and deviation < 0
            )
            if eligible:
                magnitude = min(27.0, abs(deviation) / settings.spike_scale)
                spike = -math.expm1(-magnitude * magnitude)
                ramp = -math.expm1(-(hours - settings.preserve_hours) / settings.transition_hours)
                retention *= 1 - settings.max_suppression * spike * ramp
            value = baseline + retention * deviation
        filtered.append(Point(point.start, point.end, value))
    return Result(snapshot.current_price, raw, tuple(filtered), tuple(baselines), snapshot.current_price_estimated)
