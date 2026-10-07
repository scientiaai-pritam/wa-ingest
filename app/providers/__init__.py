from app.providers.base import IngestProvider
from app.providers.whapi import WhapiProvider
from app.providers.waha import WahaProvider
from app.providers.openwa import OpenWaProvider

_REGISTRY = {"whapi": WhapiProvider, "waha": WahaProvider, "openwa": OpenWaProvider}


def get_provider(name: str, **kwargs) -> IngestProvider:
    try:
        cls = _REGISTRY[name]
    except KeyError:
        raise ValueError(f"unknown ingestion provider: {name!r} "
                         f"(available: {sorted(_REGISTRY)})") from None
    return cls(**kwargs)
