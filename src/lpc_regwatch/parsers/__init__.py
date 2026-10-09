from .base import BaseParser, Batch  # noqa: F401
from .br_agrofit import BrAgrofitParser  # noqa: F401
from .ca_ppid import CaPpidParser  # noqa: F401
from .fr_ephy import FrEphyParser  # noqa: F401
from .us_epa_ppls import UsEpaPplsParser  # noqa: F401

PARSERS = {
    "ca_ppid": CaPpidParser,
    "us_epa_ppls": UsEpaPplsParser,
    "fr_ephy": FrEphyParser,
    "br_agrofit": BrAgrofitParser,
}
