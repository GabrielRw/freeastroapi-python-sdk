from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResponseModel(BaseModel):
    # Additive API response fields remain forward compatible and are preserved.
    model_config = ConfigDict(extra="allow")


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


class MoonPhaseData(ResponseModel):
    name: MoonPhaseName
    phase_angle_deg: float
    illumination: float
    age_days: float
    distance_km: float
    is_waxing: bool


class MaximumLocation(ResponseModel):
    lat: float
    lon: float


class EclipseData(ResponseModel):
    is_eclipse: bool
    is_blood_moon: bool
    kind: Literal["solar", "lunar"] | None = None
    type: Literal["total", "annular", "hybrid", "partial", "penumbral"] | None = None
    date: str | None = None
    starts_at: str | None = None
    ends_at: str | None = None
    central_phase_starts_at: str | None = None
    central_phase_ends_at: str | None = None
    visibility: str | None = None
    visible_at_location: bool | None = None
    type_at_location: Literal["total", "annular", "partial"] | None = None
    days_from_query: float | None = None
    magnitude: float | None = None
    obscuration: float | None = Field(default=None, ge=0, le=1)
    maximum_location: MaximumLocation | None = None
    local_starts_at: str | None = None
    local_maximum_at: str | None = None
    local_ends_at: str | None = None
    magnitude_at_location: float | None = None
    obscuration_at_location: float | None = Field(default=None, ge=0, le=1)


class NextMoonPhases(ResponseModel):
    new_moon: str
    first_quarter: str
    full_moon: str
    last_quarter: str


class MoonPhaseResponse(ResponseModel):
    timestamp: str
    phase: MoonPhaseData
    eclipse: EclipseData | None = None
    next_phases: NextMoonPhases


class MoonMonthDay(MoonPhaseResponse):
    calendar_date: str


class MoonMonthResponse(ResponseModel):
    year: int
    month: int
    month_name: str
    days_in_month: int
    calendar_basis: Literal["local", "utc"]
    calendar_timezone: str
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
    angle: Literal[0, 60, 90, 120, 180] | None = None
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
    sign_id: Literal[
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
    degree: float
    abs_pos: float
    house: int
    interpretation: None = None


class ErrorResponse(ResponseModel):
    detail: Any | None = None
    error: str | None = None
    message: str | None = None
    code: str | None = None
    trace_id: str | None = None
