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
        log.warning("IA respondeu HTTP %s: %s", r.status_code, r.text[:200])
        return None
    return None


def groq(sistema: str, usuario: str, temperatura: float = 0.1):
    if not C.GROQ_API_KEY:
        return None
    for modelo in C.GROQ_MODELOS:
        r = _post("https://api.groq.com/openai/v1/chat/completions",
                  {"Authorization": f"Bearer {C.GROQ_API_KEY}"},
                  {"model": modelo, "temperature": temperatura,
                   "response_format": {"type": "json_object"},
                   "messages": [{"role": "system", "content": sistema},
                                {"role": "user", "content": usuario}]})
        if r is not None:
            _contador["groq"] += 1
            out = _json(r.json()["choices"][0]["message"]["content"])
            if out is not None:
                return out
        time.sleep(2)
    return None


def gemini(sistema: str, usuario: str, temperatura: float = 0.2):
    if not C.GEMINI_API_KEY:
        return None
    for modelo in C.GEMINI_MODELOS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
        r = _post(url, {"x-goog-api-key": C.GEMINI_API_KEY},
                  {"systemInstruction": {"parts": [{"text": sistema}]},
                   "contents": [{"role": "user", "parts": [{"text": usuario}]}],
                   "generationConfig": {"temperature": temperatura, "responseMimeType": "application/json"}})
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
    return None


def extrair(sistema: str, usuario: str):
    """Tarefas de volume (ler manchetes): Groq primeiro, Gemini de reserva."""
    return groq(sistema, usuario) or gemini(sistema, usuario)


def redigir(sistema: str, usuario: str):
    """Textos mais longos (dossiês): Gemini primeiro, Groq de reserva."""
    return gemini(sistema, usuario) or groq(sistema, usuario, temperatura=0.2)


def uso() -> dict:
    return dict(_contador)
