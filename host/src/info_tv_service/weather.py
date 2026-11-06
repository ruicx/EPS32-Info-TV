"""Retrieve Open-Meteo weather without extending old model data's freshness."""

import asyncio
import logging
import time
from datetime import UTC, datetime

import httpx
from pydantic import BaseModel, ConfigDict, Field

from info_tv_service.config import WeatherSettings
from info_tv_service.device.generated import device_pb2 as pb
from info_tv_service.device.session import DeviceSession


class CurrentWeather(BaseModel):
    """Validate the requested current model values and their UTC epoch."""

    model_config = ConfigDict(strict=True)
    time: int = Field(gt=0)
    temperature_2m: float = Field(ge=-100, le=100, allow_inf_nan=False)
    weather_code: int


class DailyWeather(BaseModel):
    """Require today's paired extrema instead of silently dropping missing data."""

    model_config = ConfigDict(strict=True)
    time: list[int] = Field(min_length=1, max_length=1)
    temperature_2m_min: list[float] = Field(min_length=1, max_length=1)
    temperature_2m_max: list[float] = Field(min_length=1, max_length=1)


class Forecast(BaseModel):
    """Select the bounded current/daily portion of an Open-Meteo response."""

    current: CurrentWeather
    daily: DailyWeather


def weather_condition(code: int) -> pb.WeatherCondition:
    """Map documented WMO codes into the device's existing weather icons.

    Parameters
    ----------
    code : int
        Open-Meteo WMO weather interpretation code.

    Returns
    -------
    WeatherCondition
        Device enum; unrecognized codes remain unknown.
    """
    if code in (0, 1):
        return pb.WEATHER_CONDITION_CLEAR
    if code in (2, 3):
        return pb.WEATHER_CONDITION_CLOUDY
    if code in (45, 48):
        return pb.WEATHER_CONDITION_FOG
    if code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82):
        return pb.WEATHER_CONDITION_RAIN
    if code in (71, 73, 75, 77, 85, 86):
        return pb.WEATHER_CONDITION_SNOW
    if code in (95, 96, 97, 99):
        return pb.WEATHER_CONDITION_STORM
    return pb.WEATHER_CONDITION_UNKNOWN


def build_weather(forecast: Forecast, settings: WeatherSettings, now: float) -> pb.Weather:
    """Convert validated model data using freshness measured from source time.

    Parameters
    ----------
    forecast : Forecast
        Parsed provider response.
    settings : WeatherSettings
        Location label and freshness policy.
    now : float
        Current UTC Unix timestamp.

    Returns
    -------
    Weather
        Existing device representation with remaining validity.

    Raises
    ------
    ValueError
        If timestamps, freshness, or the daily range are invalid.

    Notes
    -----
    Current conditions are weather model values, not station observations.
    Successful retrieval of the same data never renews its original validity.
    """
    remaining = int(min(settings.valid_for_seconds, forecast.current.time + settings.valid_for_seconds - now))
    if remaining <= 0 or forecast.current.time > now + 300:
        raise ValueError("Weather source timestamp is stale or in the future")
    # Daily timestamps identify local midnight in UTC, including 23/25-hour days.
    if not forecast.daily.time[0] <= now < forecast.daily.time[0] + 25 * 3600:
        raise ValueError("Weather daily range is not for the current day")
    low, high = forecast.daily.temperature_2m_min[0], forecast.daily.temperature_2m_max[0]
    if not -100 <= low <= high <= 100:
        raise ValueError("Weather daily range is invalid")
    return pb.Weather(location=settings.location, temperature_c=round(forecast.current.temperature_2m),
                      condition=weather_condition(forecast.current.weather_code),
                      daily_low_c=round(low), daily_high_c=round(high), valid_for_ms=remaining * 1000)


class WeatherUpdater:
    """Own automatic retrieval status independently of device delivery feedback."""

    def __init__(self, settings: WeatherSettings, device: DeviceSession) -> None:
        """Retain explicit configuration and the existing weather publisher.

        Parameters
        ----------
        settings : WeatherSettings
            Validated location and polling policy.
        device : DeviceSession
            Application-owned downstream publisher.
        """
        self.settings = settings
        self.device = device
        self.last_attempt: str | None = None
        self.last_success: str | None = None
        self.source_time: int | None = None
        self.last_error: str | None = None

    def status(self) -> dict[str, object]:
        """Report retrieval health separately from weather and delivery state.

        Returns
        -------
        dict[str, object]
            Provider attribution, location, and latest attempt outcome.
        """
        return {"enabled": True, "provider": "Open-Meteo", "attribution": "https://open-meteo.com/",
                "location": self.settings.location, "last_attempt": self.last_attempt,
                "last_success": self.last_success, "source_time": self.source_time,
                "last_error": self.last_error}

    async def refresh(self, client: httpx.AsyncClient) -> bool:
        """Attempt one bounded fetch, retaining existing weather on failure.

        Parameters
        ----------
        client : AsyncClient
            Lifespan-owned HTTP client or a mock provider client.

        Returns
        -------
        bool
            Whether fresh, valid data was published.
        """
        self.last_attempt = datetime.now(UTC).isoformat()
        try:
            response = await client.get("https://api.open-meteo.com/v1/forecast", params={
                "latitude": self.settings.latitude, "longitude": self.settings.longitude,
                "current": "temperature_2m,weather_code",
                "daily": "temperature_2m_min,temperature_2m_max",
                "timezone": "auto", "timeformat": "unixtime", "forecast_days": 1,
                "temperature_unit": "celsius",
            }, timeout=10)
            response.raise_for_status()
            forecast = Forecast.model_validate(response.json())
            weather = build_weather(forecast, self.settings, time.time())
        except (httpx.HTTPError, ValueError) as error:
            self.last_error = str(error)
            logging.getLogger(__name__).warning("Weather refresh failed: %s", error)
            return False
        self.device.set_weather(weather)
        self.last_success = datetime.now(UTC).isoformat()
        self.source_time = forecast.current.time
        self.last_error = None
        return True

    async def run(self) -> None:
        """Fetch on startup, then refresh or retry until lifespan cancellation."""
        async with httpx.AsyncClient() as client:
            while True:
                success = await self.refresh(client)
                await asyncio.sleep(self.settings.refresh_seconds if success else self.settings.retry_seconds)
