from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import time
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

import cv2
import mss
import numpy as np
import pygetwindow as gw
import pydirectinput
import yaml
from dotenv import load_dotenv
from openai import OpenAI
from PIL import Image


LOGGER = logging.getLogger("pokemon_bot")


@dataclass
class PlannedAction:
    action: str
    duration_ms: int = 200


class InputController:
    def __init__(self, keymap: dict[str, str]) -> None:
        self.keymap = keymap
        pydirectinput.PAUSE = 0
        pydirectinput.FAILSAFE = True

    def press(self, action: str, duration_ms: int = 120) -> None:
        key = self.keymap.get(action)
        if not key:
            LOGGER.warning("Ação desconhecida: %s", action)
            return
        LOGGER.info("Executando ação=%s key=%s duração=%sms", action, key, duration_ms)
        pydirectinput.keyDown(key)
        time.sleep(max(duration_ms, 40) / 1000)
        pydirectinput.keyUp(key)


class ScreenCapture:
    def __init__(self, monitor_index: int = 1) -> None:
        self.sct = mss.mss()
        self.monitor_index = monitor_index

    def grab(self) -> Image.Image:
        monitor = self.sct.monitors[self.monitor_index]
        frame = self.sct.grab(monitor)
        return Image.frombytes("RGB", frame.size, frame.rgb)


class VisionHeuristics:
    @staticmethod
    def classify_state(image: Image.Image) -> str:
        arr = np.array(image)
        hsv = cv2.cvtColor(arr, cv2.COLOR_RGB2HSV)

        # Heurística simples para detectar tela de batalha (predomínio de caixas UI)
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        edges = cv2.Canny(gray, 50, 150)
        edge_ratio = float(np.mean(edges > 0))

        # Em batalhas geralmente há elementos escuros/caixas com alta saturação em regiões fixas
        sat = hsv[:, :, 1]
        sat_ratio = float(np.mean(sat > 80))

        if edge_ratio > 0.12 and sat_ratio > 0.25:
            return "battle"
        if sat_ratio < 0.18:
            return "menu"
        return "overworld"


class AIPlanner:
    def __init__(self, config: dict[str, Any]) -> None:
        self.enabled = bool(config["strategy"].get("use_ai_planner", True))
        self.provider = config["ai"]["provider"]
        self.model = config["ai"]["model"]
        self.temperature = float(config["ai"].get("temperature", 0.1))
        self.max_tokens = int(config["ai"].get("max_tokens", 200))
        self.client = self._build_client()

    def _build_client(self) -> OpenAI | None:
        if not self.enabled or self.provider != "openai":
            return None

        if not os.getenv("OPENAI_API_KEY"):
            LOGGER.warning(
                "OPENAI_API_KEY não definido; planner de IA desativado. "
                "Defina a variável de ambiente (ou .env) para habilitar IA."
            )
            return None

        return OpenAI()

    @staticmethod
    def _image_to_data_url(image: Image.Image) -> str:
        buf = BytesIO()
        image.save(buf, format="JPEG", quality=80)
        payload = base64.b64encode(buf.getvalue()).decode("utf-8")
        return f"data:image/jpeg;base64,{payload}"

    def next_actions(self, image: Image.Image, mode: str, state: str) -> list[PlannedAction]:
        if not self.enabled or not self.client:
            return []

        prompt = (
            "Você controla um jogo Pokémon no emulador Ryujinx. "
            "Responda SOMENTE em JSON com a chave actions, uma lista de até 3 objetos "
            "no formato {action: string, duration_ms: int}. "
            "Ações válidas: A,B,X,Y,Plus,Minus,DpadUp,DpadDown,DpadLeft,DpadRight,"
            "LStickUp,LStickDown,LStickLeft,LStickRight,L,R,ZL,ZR. "
            f"Modo atual: {mode}. Estado detectado: {state}. "
            "Objetivo: progredir no jogo e lutar automaticamente sem travar em menus."
        )

        data_url = self._image_to_data_url(image)
        resp = self.client.chat.completions.create(
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "Você é um planner de ações curtas para automação de jogo."},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                },
            ],
        )

        text = resp.choices[0].message.content or "{}"
        payload = json.loads(text)
        actions = payload.get("actions", [])
        return [
            PlannedAction(action=item["action"], duration_ms=int(item.get("duration_ms", 200)))
            for item in actions[:3]
            if isinstance(item, dict) and "action" in item
        ]


class PokemonBot:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.input = InputController(config["actions"])
        self.capture = ScreenCapture(config["capture"]["monitor_index"])
        self.heuristics = VisionHeuristics()
        self.ai = AIPlanner(config)
        self.mode = config["strategy"]["default_mode"]
        self.fallback = [PlannedAction(**step) for step in config["strategy"]["fallback_script"]]

    def focus_window(self, title: str) -> bool:
        matches = gw.getWindowsWithTitle(title)
        if not matches:
            LOGGER.error("Janela não encontrada com título contendo: %s", title)
            return False
        window = matches[0]
        try:
            window.activate()
            time.sleep(0.5)
        except Exception as exc:  # pragma: no cover
            LOGGER.warning("Não foi possível focar janela automaticamente: %s", exc)
        return True

    def decide_actions(self, frame: Image.Image) -> list[PlannedAction]:
        state = self.heuristics.classify_state(frame)
        LOGGER.info("Estado detectado: %s", state)

        ai_actions = []
        try:
            ai_actions = self.ai.next_actions(frame, self.mode, state)
        except Exception as exc:
            LOGGER.warning("Planner IA falhou, usando fallback: %s", exc)

        if ai_actions:
            return ai_actions

        if state == "battle":
            return [PlannedAction("A", 250), PlannedAction("A", 250)]
        if state == "menu":
            return [PlannedAction("B", 200), PlannedAction("B", 200)]
        return self.fallback

    def run(self) -> None:
        if not self.focus_window(self.config["window_title"]):
            return

        interval = self.config["loop_interval_ms"] / 1000
        LOGGER.info("Bot iniciado. Pressione Ctrl+C para parar.")
        while True:
            frame = self.capture.grab()
            actions = self.decide_actions(frame)
            for action in actions:
                self.input.press(action.action, action.duration_ms)
                time.sleep(0.03)
            time.sleep(interval)


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bot IA para Pokémon no Ryujinx")
    parser.add_argument("--config", type=Path, default=Path("config/config.yaml"))
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args()


def main() -> None:
    load_dotenv()
    args = parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )

    config = load_config(args.config)
    bot = PokemonBot(config)
    bot.run()


if __name__ == "__main__":
    main()
