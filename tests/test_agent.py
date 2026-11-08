"""ADKエージェントの配線テスト（LLMもAPIキーも使わない）。"""

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

from google.adk.models._capabilities import LlmCapabilities
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from pydantic import PrivateAttr

from app.agent import agent, run_agent

BASE_TOOLS = {"search_glossary", "get_lecture_summary"}


class _ToolCallingModel(BaseLlm):
    model: str = "gemini-2.0-flash"
    tool_name: str
    arguments: dict[str, Any]
    _call_count: int = PrivateAttr(default=0)

    @property
    def capabilities(self) -> LlmCapabilities:
        return LlmCapabilities(output_schema_and_tools=True)

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        if not llm_request.contents:
            raise AssertionError("ADK should pass the user message to the model")
        if stream:
            raise NotImplementedError("This test model does not stream")
        if self._call_count == 0:
            self._call_count += 1
            yield LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part(
                            function_call=types.FunctionCall(
                                name=self.tool_name,
                                args=self.arguments,
                            )
                        )
                    ],
                )
            )
            return
        yield LlmResponse(
            content=types.Content(
                role="model",
                parts=[types.Part(text="テスト回答")],
            )
        )


def test_base_tools_are_registered_and_called():
    model = _ToolCallingModel(tool_name="search_glossary", arguments={"query": "LoRA"})
    target = agent.model_copy(update={"model": model})
    events = asyncio.run(run_agent(target, "LoRAとは？"))

    offered = {tool.__name__ for tool in target.tools if callable(tool)}
    assert BASE_TOOLS <= offered

    calls = [
        part.function_call.name
        for event in events
        if event.content
        for part in event.content.parts
        if part.function_call
    ]
    returns = [
        part.function_response
        for event in events
        if event.content
        for part in event.content.parts
        if part.function_response
    ]
    assert calls == ["search_glossary"]
    assert len(returns) == len(calls)
    assert "LoRA" in str(returns[0].response)
    assert any(
        event.content and any(part.text == "テスト回答" for part in event.content.parts)
        for event in events
    )
