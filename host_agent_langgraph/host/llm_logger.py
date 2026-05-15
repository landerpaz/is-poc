import json
from typing import Any, List

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import BaseMessage
from langchain_core.outputs import LLMResult

from ._step import step


class LLMLogger(BaseCallbackHandler):
    """Logs LLM request/response payloads with token counts to stdout."""

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: List[List[BaseMessage]],
        **kwargs: Any,
    ) -> None:
        model_name = serialized.get("kwargs", {}).get("model", "unknown")
        flat = [m for batch in messages for m in batch]
        est_tokens = sum(len(str(m.content)) for m in flat) // 4
        print(
            f"[Step {step():>3}] LLM REQUEST  ── model={model_name} │ messages={len(flat)} │ ~{est_tokens} tokens (estimated)"
        )
        for i, m in enumerate(flat):
            print(f"  [{i}] {m.type}: {m.content}")

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        usage: dict = {}
        msg = None
        try:
            msg = response.generations[0][0].message  # type: ignore[attr-defined]
            usage = msg.usage_metadata or {}
        except (IndexError, AttributeError):
            pass

        prompt_tokens = usage.get("input_tokens", "?")
        output_tokens = usage.get("output_tokens", "?")
        total_tokens = usage.get("total_tokens", "?")

        print(
            f"[Step {step():>3}] LLM RESPONSE ── prompt={prompt_tokens} │ output={output_tokens} │ total={total_tokens} tokens"
        )

        if msg is None:
            return

        # Text content (plain reply)
        if isinstance(msg.content, str) and msg.content.strip():
            preview = msg.content[:300] + ("…" if len(msg.content) > 300 else "")
            print(f"  content : {preview}")
        elif isinstance(msg.content, list):
            for part in msg.content:
                if isinstance(part, dict) and part.get("text", "").strip():
                    text = part["text"]
                    preview = text[:300] + ("…" if len(text) > 300 else "")
                    print(f"  content : {preview}")

        # Tool calls (Gemini returns these when invoking a tool)
        for tc in getattr(msg, "tool_calls", []) or []:
            print(
                f"  tool    : {tc.get('name', '?')}\n"
                f"  args    : {json.dumps(tc.get('args', {}), indent=4)}"
            )
