from __future__ import annotations

import math

import httpx

from app.core.config import settings


class OllamaClient:
    def chat(self, *, question: str, context: str) -> str | None:
        payload = {
            "model": settings.ollama_model,
            "stream": False,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Eres un agente explicativo antifraude para analistas de seguros. "
                        "No acusas fraude; priorizas revision humana, explicas alertas y "
                        "respondes solo con base en el contexto entregado."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Contexto controlado del sistema:\n{context}\n\n"
                        f"Pregunta del analista:\n{question}\n\n"
                        "Responde en espanol ejecutivo, con accion sugerida y aclaracion etica."
                    ),
                },
            ],
        }
        try:
            with httpx.Client(base_url=settings.ollama_base_url, timeout=settings.ollama_timeout_seconds) as client:
                response = client.post("/api/chat", json=payload)
                response.raise_for_status()
        except httpx.HTTPError:
            return None

        data = response.json()
        message = data.get("message") or {}
        content = message.get("content")
        return content if isinstance(content, str) and content.strip() else None

    def embed(self, text: str) -> list[float] | None:
        if not text.strip():
            return None

        payload = {
            "model": settings.ollama_embedding_model,
            "input": text,
        }
        try:
            with httpx.Client(base_url=settings.ollama_base_url, timeout=settings.ollama_timeout_seconds) as client:
                response = client.post("/api/embed", json=payload)
                if response.status_code == 404:
                    response = client.post(
                        "/api/embeddings",
                        json={"model": settings.ollama_embedding_model, "prompt": text},
                    )
                response.raise_for_status()
        except httpx.HTTPError:
            return None

        data = response.json()
        if "embeddings" in data and data["embeddings"]:
            embedding = data["embeddings"][0]
        else:
            embedding = data.get("embedding")

        if not isinstance(embedding, list):
            return None
        return [float(value) for value in embedding]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0

    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)
