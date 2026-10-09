from .base import BaseCollector, Fetched, SchemaDriftError  # noqa: F401
from .br_agrofit import BrAgrofitCollector  # noqa: F401
from .ca_ppid import CaPpidCollector  # noqa: F401
from .fr_ephy import FrEphyCollector  # noqa: F401
from .us_epa_ppls import UsEpaPplsCollector  # noqa: F401

COLLECTORS = {
    "ca_ppid": CaPpidCollector,
    "us_epa_ppls": UsEpaPplsCollector,
    "fr_ephy": FrEphyCollector,
    "br_agrofit": BrAgrofitCollector,
}
