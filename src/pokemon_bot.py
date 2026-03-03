from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import random
import time
from collections.abc import Mapping
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


class StuckDetector:
    def __init__(self, config: dict[str, Any]) -> None:
        strategy = config.get("strategy", {})
        self.enabled = bool(strategy.get("anti_stuck_enabled", True))
        self.diff_threshold = float(strategy.get("stuck_diff_threshold", 1.2))
        self.max_still_frames = int(strategy.get("stuck_max_still_frames", 6))
        self.preview_size = tuple(strategy.get("stuck_preview_size", [160, 90]))
        self._prev_gray: np.ndarray | None = None
        self._still_frames = 0

    def _prepare(self, image: Image.Image) -> np.ndarray:
        arr = np.array(image)
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        return cv2.resize(gray, self.preview_size, interpolation=cv2.INTER_AREA)

    def is_stuck(self, image: Image.Image) -> bool:
        if not self.enabled:
            return False

        current = self._prepare(image)
        if self._prev_gray is None:
            self._prev_gray = current
            return False

        diff = float(np.mean(cv2.absdiff(current, self._prev_gray)))
        self._prev_gray = current

        if diff < self.diff_threshold:
            self._still_frames += 1
        else:
            self._still_frames = 0

        if self._still_frames >= self.max_still_frames:
            LOGGER.warning(
                "Possível encravamento detectado (diff=%.3f, frames_parados=%s).",
                diff,
                self._still_frames,
            )
            self._still_frames = 0
            return True

        return False


class LocalAdaptivePolicy:
    def __init__(self, config: dict[str, Any]) -> None:
        strategy = config.get("strategy", {})
        self.enabled = bool(strategy.get("local_learning_enabled", True))
        self.learning_rate = float(strategy.get("learning_rate", 0.25))
        self.epsilon = float(strategy.get("exploration_rate", 0.35))
        self.epsilon_decay = float(strategy.get("exploration_decay", 0.995))
        self.epsilon_min = float(strategy.get("exploration_min", 0.05))
        self.action_duration_ms = int(strategy.get("learning_action_duration_ms", 500))

        configured_actions = strategy.get("learning_actions", [])
        if configured_actions:
            self.actions = [str(action) for action in configured_actions]
        else:
            fallback_script = strategy.get("fallback_script", [])
            fallback_actions = [step.get("action") for step in fallback_script if isinstance(step, dict)]
            unique_fallback = [action for action in fallback_actions if isinstance(action, str)]
            self.actions = list(dict.fromkeys(unique_fallback))

        if not self.actions:
            self.actions = ["LStickUp", "LStickLeft", "LStickRight", "LStickDown", "A", "B"]

        self.q_values = {action: 0.0 for action in self.actions}
        self.last_action: str | None = None

    def choose_actions(self) -> list[PlannedAction]:
        if not self.enabled:
            return []

        if random.random() < self.epsilon:
            action = random.choice(self.actions)
        else:
            action = max(self.actions, key=lambda item: self.q_values.get(item, 0.0))

        self.last_action = action
        return [PlannedAction(action, self.action_duration_ms)]

    @staticmethod
    def _frame_diff(before: Image.Image, after: Image.Image) -> float:
        before_gray = cv2.cvtColor(np.array(before), cv2.COLOR_RGB2GRAY)
        after_gray = cv2.cvtColor(np.array(after), cv2.COLOR_RGB2GRAY)
        before_small = cv2.resize(before_gray, (160, 90), interpolation=cv2.INTER_AREA)
        after_small = cv2.resize(after_gray, (160, 90), interpolation=cv2.INTER_AREA)
        return float(np.mean(cv2.absdiff(before_small, after_small)))

    def observe_transition(self, before: Image.Image, after: Image.Image) -> None:
        if not self.enabled or not self.last_action:
            return

        diff = self._frame_diff(before, after)
        reward = (diff / 10.0) - 0.2
        reward = max(min(reward, 2.0), -1.0)

        current_q = self.q_values.get(self.last_action, 0.0)
        updated_q = current_q + self.learning_rate * (reward - current_q)
        self.q_values[self.last_action] = updated_q

        self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)
        LOGGER.info(
            "Learning local: action=%s diff=%.3f reward=%.3f q=%.3f eps=%.3f",
            self.last_action,
            diff,
            reward,
            updated_q,
            self.epsilon,
        )

    def penalize_last_action(self, penalty: float = -1.0) -> None:
        if not self.enabled or not self.last_action:
            return

        current_q = self.q_values.get(self.last_action, 0.0)
        updated_q = current_q + self.learning_rate * (penalty - current_q)
        self.q_values[self.last_action] = updated_q
        LOGGER.info(
            "Learning local: penalidade action=%s penalty=%.3f q=%.3f",
            self.last_action,
            penalty,
            updated_q,
        )


class AIPlanner:
    def __init__(self, config: dict[str, Any]) -> None:
        self.enabled = bool(config["strategy"].get("use_ai_planner", True))
        self.provider = config["ai"]["provider"]
        self.model = config["ai"]["model"]
        self.temperature = float(config["ai"].get("temperature", 0.1))
        self.max_tokens = int(config["ai"].get("max_tokens", 200))
        self.cooldown_seconds = int(config["ai"].get("cooldown_seconds_after_error", 120))
        self.max_consecutive_failures = int(config["ai"].get("max_consecutive_failures", 3))
        self._cooldown_until = 0.0
        self._consecutive_failures = 0
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

    def _is_insufficient_quota_error(self, exc: Exception) -> bool:
        code = getattr(exc, "code", None)
        if code == "insufficient_quota":
            return True

        body = getattr(exc, "body", None)
        if isinstance(body, Mapping):
            err = body.get("error")
            if isinstance(err, Mapping) and err.get("code") == "insufficient_quota":
                return True

        return "insufficient_quota" in str(exc)

    def _enter_cooldown(self, reason: str) -> None:
        self._cooldown_until = time.time() + max(self.cooldown_seconds, 10)
        LOGGER.warning(
            "Planner IA em cooldown por %ss (%s). Usando fallback local.",
            self.cooldown_seconds,
            reason,
        )

    @staticmethod
    def _image_to_data_url(image: Image.Image) -> str:
        buf = BytesIO()
        image.save(buf, format="JPEG", quality=80)
        payload = base64.b64encode(buf.getvalue()).decode("utf-8")
        return f"data:image/jpeg;base64,{payload}"

    def next_actions(self, image: Image.Image, mode: str, state: str) -> list[PlannedAction]:
        if not self.enabled or not self.client:
            return []

        now = time.time()
        if now < self._cooldown_until:
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
        try:
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
            self._consecutive_failures = 0
        except Exception as exc:
            self._consecutive_failures += 1
            if self._is_insufficient_quota_error(exc):
                self._enter_cooldown("quota insuficiente")
                return []

            if self._consecutive_failures >= self.max_consecutive_failures:
                self._enter_cooldown("falhas consecutivas")
                self._consecutive_failures = 0
            raise

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
        self.stuck_detector = StuckDetector(config)
        self.mode = config["strategy"]["default_mode"]
        self.fallback = [PlannedAction(**step) for step in config["strategy"]["fallback_script"]]
        recovery_script = config["strategy"].get("recovery_script", [{"action": "B", "duration_ms": 250}, {"action": "LStickDown", "duration_ms": 500}, {"action": "A", "duration_ms": 200}])
        self.recovery = [PlannedAction(**step) for step in recovery_script]
        self.fallback_chunk_size = int(config["strategy"].get("fallback_chunk_size", 2))
        self.fallback_cursor = 0
        self.local_policy = LocalAdaptivePolicy(config)

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

    def _next_fallback_actions(self) -> list[PlannedAction]:
        if not self.fallback:
            return [PlannedAction("A", 200)]

        chunk = max(self.fallback_chunk_size, 1)
        actions: list[PlannedAction] = []
        for _ in range(chunk):
            idx = self.fallback_cursor % len(self.fallback)
            actions.append(self.fallback[idx])
            self.fallback_cursor += 1
        return actions

    def decide_actions(self, frame: Image.Image) -> tuple[list[PlannedAction], str]:
        if self.stuck_detector.is_stuck(frame):
            self.local_policy.penalize_last_action(-1.0)
            return self.recovery, "recovery"

        state = self.heuristics.classify_state(frame)
        LOGGER.info("Estado detectado: %s", state)

        ai_actions = []
        try:
            ai_actions = self.ai.next_actions(frame, self.mode, state)
        except Exception as exc:
            LOGGER.warning("Planner IA falhou, usando fallback: %s", exc)

        if ai_actions:
            return ai_actions, "ai"

        if state == "battle":
            return [PlannedAction("A", 250), PlannedAction("A", 250)], "battle"
        if state == "menu":
            return [PlannedAction("B", 200), PlannedAction("B", 200)], "menu"

        learned_actions = self.local_policy.choose_actions()
        if learned_actions:
            return learned_actions, "adaptive"
        return self._next_fallback_actions(), "fallback"

    def run(self) -> None:
        if not self.focus_window(self.config["window_title"]):
            return

        interval = self.config["loop_interval_ms"] / 1000
        LOGGER.info("Bot iniciado. Pressione Ctrl+C para parar.")
        try:
            while True:
                frame = self.capture.grab()
                actions, source = self.decide_actions(frame)
                for action in actions:
                    self.input.press(action.action, action.duration_ms)
                    time.sleep(0.03)

                if source == "adaptive":
                    after_frame = self.capture.grab()
                    self.local_policy.observe_transition(frame, after_frame)

                time.sleep(interval)
        except KeyboardInterrupt:
            LOGGER.info("Bot parado pelo utilizador (Ctrl+C).")


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
