from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import requests

from .config import AppConfig
from .tools import call_tool, tool_schemas


class OpenAIClientError(RuntimeError):
    pass


class EmptyTranscriptionError(OpenAIClientError):
    pass


@dataclass(frozen=True)
class HistoryMessage:
    role: str
    text: str


class OpenAIClient:
    MAX_TOOL_ROUNDS = 16

    def __init__(self, api_key: str, config: AppConfig) -> None:
        self.api_key = api_key
        self.config = config
        self.session = requests.Session()
        self.base_headers = {"Authorization": f"Bearer {api_key}"}

    def transcribe(self, audio_path: Path) -> str:
        with audio_path.open("rb") as handle:
            response = self.session.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers=self.base_headers,
                files={"file": (audio_path.name, handle, "audio/wav")},
                data={
                    "model": self.config.stt_model,
                    "language": self.config.language,
                    "response_format": "text",
                    "prompt": "Transcribe exactamente voz en espanol. Si no hay habla clara, no inventes texto.",
                },
                timeout=self.config.request_timeout_seconds,
            )
        self._raise_for_status(response, "transcripcion")
        text = response.text.strip()
        if not text:
            raise EmptyTranscriptionError("La transcripcion llego vacia.")
        return text

    def reply(self, user_text: str, history: Iterable[HistoryMessage]) -> str:
        current_input: list[dict[str, Any]] = [
            {"role": item.role, "content": item.text} for item in history
        ]
        current_input.append({"role": "user", "content": user_text})
        tools = tool_schemas()
        body = self._create_response(current_input, tools)

        for _ in range(self.MAX_TOOL_ROUNDS):
            calls = self._extract_function_calls(body)
            if not calls:
                break

            response_items = self._extract_response_items(body)
            tool_items: list[dict[str, Any]] = []
            for call in calls:
                output = call_tool(
                    str(call.get("name", "")),
                    call.get("arguments", "{}"),
                )
                tool_items.append(self._function_call_output(call, output))

            current_input = [*current_input, *response_items, *tool_items]
            body = self._create_response(current_input, tools)

        if self._extract_function_calls(body):
            raise OpenAIClientError("El modelo excedio el limite de llamadas a herramientas.")

        text = self._extract_output_text(body).strip()
        if not text:
            raise OpenAIClientError("La respuesta del modelo llego vacia.")
        return text

    def synthesize(self, text: str, output_path: Path) -> Path:
        payload = {
            "model": self.config.tts_model,
            "voice": self.config.tts_voice,
            "input": text,
            "response_format": "wav",
            "instructions": self.config.tts_instructions,
        }
        response = self.session.post(
            "https://api.openai.com/v1/audio/speech",
            headers={
                **self.base_headers,
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.config.request_timeout_seconds,
        )
        self._raise_for_status(response, "sintesis")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(response.content)
        return output_path

    def _create_response(
        self,
        input_items: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.chat_model,
            "instructions": self.config.system_prompt,
            "input": input_items,
            "tools": tools,
        }
        response = self.session.post(
            "https://api.openai.com/v1/responses",
            headers={
                **self.base_headers,
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.config.request_timeout_seconds,
        )
        self._raise_for_status(response, "respuesta")
        return response.json()

    @staticmethod
    def _function_call_output(call: dict[str, Any], output: str) -> dict[str, Any]:
        call_id = call.get("call_id")
        if not call_id:
            raise OpenAIClientError("La llamada de herramienta no incluyo call_id.")
        return {
            "type": "function_call_output",
            "call_id": call_id,
            "output": output,
        }

    @staticmethod
    def _extract_response_items(body: dict[str, Any]) -> list[dict[str, Any]]:
        output = body.get("output", [])
        if not isinstance(output, list):
            return []
        return [item for item in output if isinstance(item, dict)]

    @staticmethod
    def _extract_function_calls(body: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            item
            for item in OpenAIClient._extract_response_items(body)
            if item.get("type") == "function_call"
        ]

    @staticmethod
    def _extract_output_text(body: dict[str, Any]) -> str:
        if isinstance(body.get("output_text"), str):
            return body["output_text"]
        output = body.get("output", [])
        pieces: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            for content in item.get("content", []):
                if content.get("type") == "output_text" and content.get("text"):
                    pieces.append(content["text"])
        return "\n".join(pieces)

    @staticmethod
    def _raise_for_status(response: requests.Response, operation: str) -> None:
        if response.ok:
            return
        message = response.text.strip()
        raise OpenAIClientError(
            f"Fallo la {operation} con OpenAI ({response.status_code}): {message}"
        )
