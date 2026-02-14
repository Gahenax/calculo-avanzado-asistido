from datetime import datetime, timedelta, timezone
from typing import Tuple, Dict

# ============================================================
# CONTEXT ANCHOR (Forense / Reproducible)
# ============================================================

COT = timezone(timedelta(hours=-5), name="COT")

FIXED_CONTEXT_TIME = datetime(
    2026, 2, 14, 5, 55, 28, tzinfo=COT
)

LOCATION = {
    "city": "Turbaco",
    "department": "Bolivar",
    "country": "Colombia"
}

def get_current_context() -> Tuple[datetime, Dict[str, str]]:
    """
    Contexto determinista:
    - Tiempo fijo con tz explícito
    - Ubicación serializable
    """
    return FIXED_CONTEXT_TIME, LOCATION.copy()


if __name__ == "__main__":
    ts, loc = get_current_context()
    print(ts.strftime("%A, %B %d, %Y at %I:%M:%S %p %Z"))
    print(f"{loc['city']}, {loc['department']}, {loc['country']}")
