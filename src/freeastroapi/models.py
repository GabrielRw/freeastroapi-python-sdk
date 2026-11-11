from __future__ import annotations

from collections.abc import Hashable, Mapping
from functools import cache
from typing import Any, Literal, Self, TypeVar, cast

from pydantic import BaseModel, ConfigDict, Field, ModelWrapValidatorHandler, TypeAdapter, model_validator
from pydantic import ValidationError as PydanticValidationError

M = TypeVar("M", bound="ResponseModel")


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


@cache
def _adapter(annotation: Hashable) -> TypeAdapter[Any]:
    return TypeAdapter(cast(Any, annotation))


class ResponseModel(BaseModel):
    """Base class of the response models.

    Decoding is lenient: unknown fields are kept (``model_extra``), and a response that breaks
    the declared types (a missing or null required field, an unknown enum value) still decodes.
    Fields that validate are converted as usual; a missing required field is ``None`` and any
    other value that does not validate is kept as received.
    """

    model_config = ConfigDict(extra="allow")

    @model_validator(mode="wrap")
    @classmethod
    def _decode_leniently(cls, data: Any, handler: ModelWrapValidatorHandler[Self]) -> Self:
        try:
            return handler(data)
        except PydanticValidationError:
            # Only objects become models: re-raising for other values lets ``Model | None``
            # unions keep ``None`` and lets the parent model keep the raw value.
            if not isinstance(data, Mapping):
                raise
            return cls._construct_leniently(data)

    @classmethod
    def _construct_leniently(cls, data: Mapping[str, Any]) -> Self:
        values: dict[str, Any] = {}
        for name, info in cls.model_fields.items():
            if name in data:
                try:
                    values[name] = _adapter(cast(Hashable, info.annotation)).validate_python(data[name])
                except PydanticValidationError:
                    values[name] = data[name]
            elif info.is_required():
                values[name] = None
        extra = {key: value for key, value in data.items() if key not in cls.model_fields}
        return cast(Self, cls.model_construct(**values, **extra))


def decode(model: type[M], data: Any) -> M:
    """Decode a response body into ``model`` without raising (see :class:`ResponseModel`).

    A body that is not a JSON object at all gives a model whose fields are all ``None``.
    """
    try:
        return model.model_validate(data)
    except PydanticValidationError:
        return model._construct_leniently({})


class GeoSearchParams(RequestModel):
    q: str = Field(min_length=2, max_length=100)
    limit: int = Field(default=10, ge=1, le=50)
    country: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")


class City(ResponseModel):
    name: str
    country: str
    state: str | None = None
    district: str | None = None
    lat: float
    lng: float
    timezone: str
    population: int


class CitySearchResponse(ResponseModel):
    results: list[City]
    count: int


class MoonLocationParams(RequestModel):
    city: str | None = Field(default=None, min_length=1, max_length=200)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    tz_str: str = "AUTO"
    include_eclipse: bool = False
    include_forecast: bool = False


class MoonPhaseParams(MoonLocationParams):
    date: str | None = None


class MoonMonthParams(MoonLocationParams):
    year: int = Field(ge=1, le=9999)
    month: int = Field(ge=1, le=12)


MoonPhaseName = Literal[
    "New Moon",
    "Waxing Crescent",
    "First Quarter",
    "Waxing Gibbous",
    "Full Moon",
    "Waning Gibbous",
    "Last Quarter",
    "Waning Crescent",
]

SignId = Literal[
    "aries",
    "taurus",
    "gemini",
    "cancer",
    "leo",
    "virgo",
    "libra",
    "scorpio",
    "sagittarius",
    "capricorn",
    "aquarius",
    "pisces",
]


class MoonPhaseData(ResponseModel):
    name: MoonPhaseName
    phase_angle_deg: float
    illumination: float
    age_days: float
    distance_km: float
    is_waxing: bool


class ZodiacData(ResponseModel):
    sign: str
    sign_id: SignId
    degree: float
    zodiac_type: str = "tropical"


class RiseSetData(ResponseModel):
    rise: str | None
    set: str | None
    rise_local: str | None = None
    set_local: str | None = None
    location: str | None = None
    timezone: str = "UTC"
    timezone_local: str | None = None


class MoonVisualData(ResponseModel):
    type: str = "svg"
    svg: str
    shadow_ratio: float
    waxing: bool


class SpecialMoonData(ResponseModel):
    is_supermoon: bool = False
    is_micromoon: bool = False
    is_blue_moon: bool = False
    is_black_moon: bool = False
    is_harvest_moon: bool = False
    is_hunter_moon: bool = False
    labels: list[str] = Field(default_factory=list)


class MaximumLocation(ResponseModel):
    lat: float
    lon: float


class EclipseData(ResponseModel):
    is_eclipse: bool = False
    is_blood_moon: bool = False
    kind: Literal["solar", "lunar"] | None = None
    type: Literal["total", "annular", "hybrid", "partial", "penumbral"] | None = None
    date: str | None = None
    starts_at: str | None = None
    ends_at: str | None = None
    central_phase_starts_at: str | None = None
    central_phase_ends_at: str | None = None
    visibility: str | None = None
    visible_at_location: bool | None = None
    type_at_location: Literal["total", "annular", "hybrid", "partial"] | None = None
    days_from_query: float | None = None
    magnitude: float | None = None
    obscuration: float | None = None
    maximum_location: MaximumLocation | None = None
    local_starts_at: str | None = None
    local_maximum_at: str | None = None
    local_ends_at: str | None = None
    magnitude_at_location: float | None = None
    obscuration_at_location: float | None = None


class MoonInterpretationData(ResponseModel):
    key: str
    title: str
    body: str
    tone: str | None = None
    tags: list[str] = Field(default_factory=list)


class TraditionalMoonData(ResponseModel):
    name: str
    naming_system: str = "north_american_traditional"
    month: str
    applies_to_full_moon_at: str
    is_current_full_moon: bool = False


class NextMoonPhases(ResponseModel):
    """UTC instants (ISO 8601) of the next four principal phases."""

    new_moon: str
    first_quarter: str
    full_moon: str
    last_quarter: str


class MoonPhaseResponse(ResponseModel):
    timestamp: str
    phase: MoonPhaseData
    zodiac: ZodiacData | None = None
    rise_set: RiseSetData | None = None
    moon_visual: MoonVisualData | None = None
    special_moon: SpecialMoonData | None = None
    eclipse: EclipseData | None = None
    forecast: dict[str, Any] | None = None
    interpretation: MoonInterpretationData | None = None
    traditional_moon: TraditionalMoonData | None = None
    next_phases: NextMoonPhases


class MoonMonthDay(MoonPhaseResponse):
    calendar_date: str


class MoonSignTimelineSegment(ResponseModel):
    sign: str
    sign_id: str
    starts_at: str
    ends_at: str
    starts_at_local: str | None = None
    ends_at_local: str | None = None
    duration_hours: float
    duration_minutes: int
    continues_from_previous_month: bool
    continues_to_next_month: bool
    next_sign: str | None = None
    next_sign_id: str | None = None
    label: str | None = None


class MoonSignIngress(ResponseModel):
    from_sign: str
    from_sign_id: str
    to_sign: str
    to_sign_id: str
    at: str
    at_local: str | None = None
    label: str


class MoonMonthResponse(ResponseModel):
    year: int
    month: int
    month_name: str
    days_in_month: int
    #: ``"local"`` or ``"utc"``.
    calendar_basis: str
    calendar_timezone: str
    sign_timeline: list[MoonSignTimelineSegment] | None = None
    ingresses: list[MoonSignIngress] | None = None
    days: list[MoonMonthDay]


class SkyEventsParams(RequestModel):
    date: str
    timezone: str = "UTC"
    include_moon: bool = False
    include_exact_hits: bool = True
    include_moon_exact_hits: bool = False
    include_ingresses: bool = True
    include_retrogrades: bool = False
    include_lunations: bool = False
    include_formulation: bool = False


class SkyEvent(ResponseModel):
    id: str
    type: Literal["moon_ingress", "planet_ingress", "exact_aspect", "retrograde_station", "lunation"]
    title: str
    formulation: str | None = None
    exact_time: str
    importance: Literal["daily", "medium", "major"]
    body: str | None = None
    sign: str | None = None
    bodies: list[str] | None = None
    aspect: Literal["conjunction", "sextile", "square", "trine", "opposition"] | None = None
    angle: int | None = None
    orb: int | None = None
    direction: Literal["retrograde", "direct"] | None = None
    phase: Literal["new_moon", "full_moon"] | None = None


class SkyEventsResponse(ResponseModel):
    date: str
    timezone: str
    events: list[SkyEvent]


class WesternSignRequest(RequestModel):
    name: str = Field(default="Example User", max_length=200)
    year: int = Field(ge=1, le=9999)
    month: int = Field(ge=1, le=12)
    day: int = Field(ge=1, le=31)
    hour: int = Field(default=12, ge=0, le=23)
    minute: int = Field(default=0, ge=0, le=59)
    time_known: bool = True
    city: str | None = Field(default=None, min_length=1, max_length=200)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    tz_str: str = "AUTO"
    house_system: Literal["placidus", "whole_sign", "equal", "regiomontanus", "koch", "porphyry"] = "placidus"
    zodiac_type: Literal["tropical", "sidereal"] = "tropical"
    sidereal_ayanamsa: Literal["lahiri", "raman", "kp", "fagan_bradley"] = "lahiri"

    @model_validator(mode="after")
    def require_location(self) -> WesternSignRequest:
        if not self.city and (self.lat is None or self.lng is None):
            raise ValueError("provide city or both lat and lng")
        return self


class WesternSignResponse(ResponseModel):
    point: str
    sign: str
    sign_id: SignId
    degree: float
    abs_pos: float
    house: int
    interpretation: dict[str, Any] | None = None
    resolved_time: dict[str, Any] | None = None


class ErrorResponse(ResponseModel):
    detail: Any | None = None
    error: str | None = None
    message: str | None = None
    code: str | None = None
    docs: str | None = None
    retry_after_ms: int | None = None
    limit_info: dict[str, Any] | None = None
    trace_id: str | None = None
