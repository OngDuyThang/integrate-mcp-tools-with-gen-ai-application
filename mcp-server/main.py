from typing import Optional, Tuple

import httpx
from mcp.server.fastmcp import FastMCP

# Initialize the MCP server
mcp = FastMCP("weather", port=8000)

# --- Helper Functions ---


async def _get_coordinates(client: httpx.AsyncClient, city: str) -> Optional[Tuple[float, float, str, str]]:
    """
    Helper to get (lat, lon, name, country) from a city name.
    Returns None if city not found.
    """
    geo_url = "https://geocoding-api.open-meteo.com/v1/search"
    try:
        response = await client.get(
            geo_url,
            params={"name": city, "count": 1,
                    "language": "en", "format": "json"}
        )
        response.raise_for_status()
        data = response.json()

        if not data.get("results"):
            return None

        location = data["results"][0]
        return (
            location["latitude"],
            location["longitude"],
            location["name"],
            location.get("country", "Unknown")
        )
    except Exception:
        return None


def _get_weather_condition(code: int) -> str:
    """Helper to convert WMO weather codes to text."""
    if code is None:
        return "Unknown"
    if code == 0:
        return "Clear sky"
    if code in [1, 2, 3]:
        return "Partly cloudy"
    if code in [45, 48]:
        return "Foggy"
    if code in [51, 53, 55]:
        return "Drizzle"
    if code in [56, 57]:
        return "Freezing Drizzle"
    if code in [61, 63, 65]:
        return "Rain"
    if code in [66, 67]:
        return "Freezing Rain"
    if code in [71, 73, 75]:
        return "Snow"
    if code in [77]:
        return "Snow grains"
    if code in [80, 81, 82]:
        return "Rain showers"
    if code in [85, 86]:
        return "Snow showers"
    if code in [95, 96, 99]:
        return "Thunderstorm"
    return "Overcast/Variable"

# --- Tools ---


@mcp.tool()
async def get_weather(city: str) -> str:
    """
    Get the current weather for a specific city.

    Args:
        city: The name of the city (e.g., "London", "New York", "Tokyo")
    """
    async with httpx.AsyncClient() as client:
        # 1. Geocoding
        coords = await _get_coordinates(client, city)
        if not coords:
            return f"Error: Could not find coordinates for city '{city}'."
        lat, lon, name, country = coords

        # 2. Fetch Weather
        weather_url = "https://api.open-meteo.com/v1/forecast"
        try:
            response = await client.get(
                weather_url,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "temperature_2m,wind_speed_10m,weather_code,relative_humidity_2m",
                    "temperature_unit": "celsius"
                }
            )
            response.raise_for_status()
            data = response.json()

            current = data.get("current", {})
            condition = _get_weather_condition(current.get("weather_code"))

            return (
                f"Current Weather in {name}, {country}:\n"
                f"Condition: {condition}\n"
                f"Temperature: {current.get('temperature_2m')}°C\n"
                f"Humidity: {current.get('relative_humidity_2m')}%\n"
                f"Wind Speed: {current.get('wind_speed_10m')} km/h"
            )
        except Exception as e:
            return f"Error fetching weather: {str(e)}"


@mcp.tool()
async def get_daily_forecast(city: str, days: int = 3) -> str:
    """
    Get a daily weather forecast for a city.

    Args:
        city: The name of the city (e.g., "London", "New York", "Tokyo")
        days: Number of days to forecast (1 to 7, default 3)
    """
    if days > 7:
        days = 7
    if days < 1:
        days = 1

    async with httpx.AsyncClient() as client:
        coords = await _get_coordinates(client, city)
        if not coords:
            return f"Error: Could not find coordinates for city '{city}'."
        lat, lon, name, country = coords

        weather_url = "https://api.open-meteo.com/v1/forecast"
        try:
            response = await client.get(
                weather_url,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "daily": "weather_code,temperature_2m_max,temperature_2m_min",
                    "forecast_days": days,
                    "timezone": "auto"
                }
            )
            response.raise_for_status()
            data = response.json()
            daily = data.get("daily", {})

            times = daily.get("time", [])
            codes = daily.get("weather_code", [])
            max_temps = daily.get("temperature_2m_max", [])
            min_temps = daily.get("temperature_2m_min", [])

            report = [f"Forecast for {name}, {country} (Next {days} days):"]
            for i in range(len(times)):
                condition = _get_weather_condition(codes[i])
                report.append(
                    f"- {times[i]}: {condition}, High: {max_temps[i]}°C, Low: {min_temps[i]}°C"
                )

            return "\n".join(report)

        except Exception as e:
            return f"Error fetching forecast: {str(e)}"


@mcp.tool()
async def get_air_quality(city: str) -> str:
    """
    Get the current air quality index (AQI) and pollutants for a city.

    Args:
        city: The name of the city (e.g., "London", "New York", "Tokyo")
    """
    async with httpx.AsyncClient() as client:
        coords = await _get_coordinates(client, city)
        if not coords:
            return f"Error: Could not find coordinates for city '{city}'."
        lat, lon, name, country = coords

        # Open-Meteo has a separate Air Quality API
        aq_url = "https://air-quality-api.open-meteo.com/v1/air-quality"
        try:
            response = await client.get(
                aq_url,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "us_aqi,pm10,pm2_5,carbon_monoxide,nitrogen_dioxide",
                    "timezone": "auto"
                }
            )
            response.raise_for_status()
            data = response.json()
            current = data.get("current", {})

            return (
                f"Air Quality in {name}, {country}:\n"
                f"US AQI: {current.get('us_aqi')} (0-50 Good, 51-100 Moderate, 101+ Unhealthy)\n"
                f"PM2.5: {current.get('pm2_5')} μg/m³\n"
                f"PM10: {current.get('pm10')} μg/m³\n"
                f"CO: {current.get('carbon_monoxide')} μg/m³\n"
                f"NO2: {current.get('nitrogen_dioxide')} μg/m³"
            )

        except Exception as e:
            return f"Error fetching air quality: {str(e)}"

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
