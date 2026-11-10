from ..config import settings
from .base import BaseProvider, TaskResult
from .capmonster import CapMonsterProvider
from .capsolver import CapsolverProvider
from .nopecha import NopechaProvider
from .twocaptcha import TwoCaptchaProvider


def get_provider() -> BaseProvider:
    p = settings.provider.lower()
    if p == "twocaptcha":
        return TwoCaptchaProvider(settings.twocaptcha_key)
    if p == "capsolver":
        return CapsolverProvider(settings.capsolver_key)
    if p == "capmonster":
        return CapMonsterProvider(settings.capmonster_key)
    if p == "nopecha":
        return NopechaProvider(settings.nopecha_key)
    raise ValueError(f"Unknown provider: {p}. Use twocaptcha|capsolver|capmonster|nopecha")


__all__ = [
    "BaseProvider",
    "CapMonsterProvider",
    "CapsolverProvider",
    "NopechaProvider",
    "TaskResult",
    "TwoCaptchaProvider",
    "get_provider",
]
