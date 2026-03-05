"""
LLM Client for Clara Answers pipeline.
Supports: Groq free-tier (primary), Ollama local (secondary), rule-based fallback (guaranteed zero-cost).
"""

import os
import json
import re
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class LLMClient:
    """Multi-backend LLM client with automatic fallback."""

    def __init__(self):
        self.groq_api_key = os.environ.get("GROQ_API_KEY", "")
        self.ollama_url = os.environ.get("OLLAMA_URL", "http://localhost:11434")
        self.backend = self._detect_backend()
        logger.info(f"LLM backend selected: {self.backend}")

    def _detect_backend(self) -> str:
        """Detect the best available LLM backend."""
        if self.groq_api_key:
            try:
                import httpx
                resp = httpx.get(
                    "https://api.groq.com/openai/v1/models",
                    headers={"Authorization": f"Bearer {self.groq_api_key}"},
                    timeout=5
                )
                if resp.status_code == 200:
                    return "groq"
            except Exception as e:
                logger.warning(f"Groq API check failed: {e}")

        # Try Ollama
        try:
            import httpx
            resp = httpx.get(f"{self.ollama_url}/api/tags", timeout=3)
            if resp.status_code == 200:
                models = resp.json().get("models", [])
                if models:
                    return "ollama"
        except Exception:
            pass

        return "rule_based"

    def generate(self, prompt: str, system_prompt: str = "") -> str:
        """Generate text using the best available backend."""
        if self.backend == "groq":
            return self._groq_generate(prompt, system_prompt)
        elif self.backend == "ollama":
            return self._ollama_generate(prompt, system_prompt)
        else:
            return self._rule_based_generate(prompt, system_prompt)

    def _groq_generate(self, prompt: str, system_prompt: str) -> str:
        """Use Groq free-tier API."""
        import httpx

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            resp = httpx.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.groq_api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": messages,
                    "temperature": 0.1,
                    "max_tokens": 4096,
                    "response_format": {"type": "json_object"}
                },
                timeout=60
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            logger.warning(f"Groq generation failed: {e}. Falling back to rule-based.")
            return self._rule_based_generate(prompt, system_prompt)

    def _ollama_generate(self, prompt: str, system_prompt: str) -> str:
        """Use local Ollama instance."""
        import httpx

        full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
        try:
            resp = httpx.post(
                f"{self.ollama_url}/api/generate",
                json={
                    "model": "llama3.2:3b",
                    "prompt": full_prompt,
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0.1}
                },
                timeout=120
            )
            resp.raise_for_status()
            return resp.json()["response"]
        except Exception as e:
            logger.warning(f"Ollama generation failed: {e}. Falling back to rule-based.")
            return self._rule_based_generate(prompt, system_prompt)

    def _rule_based_generate(self, prompt: str, system_prompt: str) -> str:
        """
        Rule-based extraction from transcripts. Zero-cost, no API needed.
        Parses transcript text using regex and heuristics.
        """
        # This is used as a fallback — the actual extraction logic
        # lives in processor.py's rule-based methods.
        # Return empty JSON to signal the processor should use its own extraction.
        return '{"_use_rule_based": true}'


def extract_json_from_response(text: str) -> Dict[str, Any]:
    """Extract JSON from LLM response, handling markdown code blocks."""
    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code block
    json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    # Try finding JSON object in text
    brace_match = re.search(r'\{.*\}', text, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass

    return {"_parse_error": True, "raw_text": text}
