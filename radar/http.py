"""Sessão HTTP com repetição automática."""
from __future__ import annotations

import logging
import time

import requests

log = logging.getLogger("radar.http")

UA = "Mozilla/5.0 (compatible; QuartoPilar/1.0; +https://github.com)"


def sessao() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "application/json"})
    return s


def get(s: requests.Session, url: str, *, params=None, headers=None, tentativas: int = 4,
        espera: float = 4.0, timeout: int = 90, aceitar=(200,)) -> requests.Response | None:
    """GET com repetição. Devolve None se não conseguir."""
    for t in range(1, tentativas + 1):
        try:
            r = s.get(url, params=params, headers=headers, timeout=timeout)
            if r.status_code in aceitar:
                return r
            if r.status_code == 404:
                return None
            log.warning("HTTP %s em %s (tentativa %s/%s)", r.status_code, url[:90], t, tentativas)
        except requests.RequestException as e:
            log.warning("Erro em %s: %s (tentativa %s/%s)", url[:90], e, t, tentativas)
        time.sleep(espera * t)
    return None
