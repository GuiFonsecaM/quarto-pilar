"""Clientes das APIs gratuitas de IA (Groq e Google Gemini), sempre pedindo JSON.

Cada chamada tenta os modelos em ordem e cai para o próximo provedor se a cota acabar.
Sem nenhuma chave configurada, as funções devolvem None e o Quarto Pilar usa regras fixas.
"""
from __future__ import annotations

import json
import logging
import re
import time

import requests

from . import config as C

log = logging.getLogger("radar.llm")

_contador = {"groq": 0, "gemini": 0}
_mortos: set[str] = set()          # modelos que a API disse que não existem mais
_descobertos: dict[str, list] = {}  # modelos listados pela própria API, por provedor


class _ModeloInexistente(Exception):
    pass


def _versao(nome: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", nome)[:3]) or (0,)


def _listar_groq() -> list[str]:
    try:
        r = requests.get("https://api.groq.com/openai/v1/models",
                         headers={"Authorization": f"Bearer {C.GROQ_API_KEY}"}, timeout=30)
        ids = [m["id"] for m in r.json().get("data", [])] if r.status_code == 200 else []
    except (requests.RequestException, ValueError):
        ids = []
    fora = ("whisper", "guard", "tts", "playai", "compound", "orpheus", "safeguard")
    ids = [i for i in ids if not any(f in i.lower() for f in fora)]
    pref = lambda i: (0 if "gpt-oss-120b" in i else 1 if "70b" in i or "maverick" in i else 2, i)
    return sorted(ids, key=pref)


def _listar_gemini() -> list[str]:
    try:
        r = requests.get("https://generativelanguage.googleapis.com/v1beta/models",
                         headers={"x-goog-api-key": C.GEMINI_API_KEY}, params={"pageSize": 200}, timeout=30)
        ms = r.json().get("models", []) if r.status_code == 200 else []
    except (requests.RequestException, ValueError):
        ms = []
    fora = ("image", "tts", "live", "audio", "embedding", "exp", "preview", "thinking", "robotics", "computer")
    ids = [m["name"].split("/")[-1] for m in ms
           if "generateContent" in m.get("supportedGenerationMethods", [])
           and "flash" in m["name"] and not any(f in m["name"] for f in fora)]
    # mais nova primeiro; dentro da mesma versão, flash antes de flash-lite
    return sorted(ids, key=lambda i: (tuple(-x for x in _versao(i)), "lite" in i))


def _modelos(provedor: str) -> list[str]:
    base = C.GROQ_MODELOS if provedor == "groq" else C.GEMINI_MODELOS
    vivos = [m for m in base if m not in _mortos]
    if len(vivos) < len(base) or not vivos:  # algum foi aposentado: pergunta à API o que existe hoje
        if provedor not in _descobertos:
            _descobertos[provedor] = (_listar_groq if provedor == "groq" else _listar_gemini)()
            log.info("Modelos disponíveis (%s): %s", provedor, ", ".join(_descobertos[provedor][:6]) or "nenhum")
        vivos += [m for m in _descobertos[provedor][:4] if m not in _mortos and m not in vivos]
    return vivos


def disponivel() -> bool:
    return bool(C.GROQ_API_KEY or C.GEMINI_API_KEY)


def _json(txt: str):
    if not txt:
        return None
    txt = txt.strip()
    txt = re.sub(r"^```(?:json)?\s*|\s*```$", "", txt)
    try:
        return json.loads(txt)
    except ValueError:
        m = re.search(r"\{.*\}", txt, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except ValueError:
                return None
    return None


def _post(url, headers, body, tentativas=3):
    for t in range(tentativas):
        try:
            r = requests.post(url, headers=headers, json=body, timeout=120)
        except requests.RequestException as e:
            log.warning("Erro de rede na IA: %s", e)
            time.sleep(5 * (t + 1))
            continue
        if r.status_code == 200:
            return r
        if r.status_code == 429:
            espera = float(r.headers.get("retry-after", 0) or 0) or 20 * (t + 1)
            if espera > 90:  # cota diária esgotada: desiste deste modelo
                log.warning("Cota esgotada (%s)", url.split("/")[2])
                return None
            time.sleep(espera)
            continue
        if r.status_code == 404 or (r.status_code == 400 and "decommissioned" in r.text):
            raise _ModeloInexistente()
        log.warning("IA respondeu HTTP %s: %s", r.status_code, r.text[:200])
        return None
    return None


def groq(sistema: str, usuario: str, temperatura: float = 0.1):
    if not C.GROQ_API_KEY:
        return None
    tentados = set()
    while True:
        fila = [m for m in _modelos("groq") if m not in tentados]
        if not fila:
            return None
        modelo = fila[0]
        tentados.add(modelo)
        try:
            r = _post("https://api.groq.com/openai/v1/chat/completions",
                      {"Authorization": f"Bearer {C.GROQ_API_KEY}"},
                      {"model": modelo, "temperature": temperatura,
                       "response_format": {"type": "json_object"},
                       "messages": [{"role": "system", "content": sistema},
                                    {"role": "user", "content": usuario}]})
        except _ModeloInexistente:
            log.warning("Modelo %s não existe mais no Groq; procurando substituto.", modelo)
            _mortos.add(modelo)
            continue
        if r is not None:
            _contador["groq"] += 1
            out = _json(r.json()["choices"][0]["message"]["content"])
            if out is not None:
                return out
        time.sleep(2)


def gemini(sistema: str, usuario: str, temperatura: float = 0.2):
    if not C.GEMINI_API_KEY:
        return None
    tentados = set()
    while True:
        fila = [m for m in _modelos("gemini") if m not in tentados]
        if not fila:
            return None
        modelo = fila[0]
        tentados.add(modelo)
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
        try:
            r = _post(url, {"x-goog-api-key": C.GEMINI_API_KEY},
                      {"systemInstruction": {"parts": [{"text": sistema}]},
                       "contents": [{"role": "user", "parts": [{"text": usuario}]}],
                       "generationConfig": {"temperature": temperatura, "responseMimeType": "application/json"}})
        except _ModeloInexistente:
            log.warning("Modelo %s não está mais disponível no Gemini; procurando substituto.", modelo)
            _mortos.add(modelo)
            continue
        if r is not None:
            _contador["gemini"] += 1
            try:
                txt = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            except (KeyError, IndexError):
                txt = ""
            out = _json(txt)
            if out is not None:
                return out
        time.sleep(4)


def extrair(sistema: str, usuario: str):
    """Tarefas de volume (ler manchetes): Groq primeiro, Gemini de reserva."""
    return groq(sistema, usuario) or gemini(sistema, usuario)


def redigir(sistema: str, usuario: str):
    """Textos mais longos (dossiês): Gemini primeiro, Groq de reserva."""
    return gemini(sistema, usuario) or groq(sistema, usuario, temperatura=0.2)


def uso() -> dict:
    return dict(_contador)
