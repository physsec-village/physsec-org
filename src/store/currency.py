import json
from urllib.request import urlopen


USD_CAD_RATE_URL = "https://www.bankofcanada.ca/valet/observations/FXUSDCAD/json?recent=1"


def get_usd_cad_rate() -> float:
    with urlopen(USD_CAD_RATE_URL, timeout=5) as response:
        payload = json.load(response)

    observations = payload.get("observations") or []
    if not observations:
        raise ValueError("No USD/CAD observations returned by Bank of Canada")

    latest = observations[-1].get("FXUSDCAD") or {}
    value = latest.get("v")
    if not value:
        raise ValueError("USD/CAD observation missing value")

    return float(value)


def convert_usd_cents_to_cad_cents(usd_cents: int, usd_cad_rate: float) -> int:
    return round(usd_cents * usd_cad_rate)
