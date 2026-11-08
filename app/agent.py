"""Google ADK で作る学習支援エージェント。

使い方:
    uv run adk run app "AIE2026の講座で使う「lecNN-start タグ」とは何ですか？"
    uv run python -m app.agent "AIE2026の講座で使う「lecNN-start タグ」とは何ですか？"
    uv run python -m app.agent --trace "LoRAとQLoRAの違いは？"
    uv run python -m app.agent --mcp --trace "LoRAとは？"
    uv run adk web

ADK Web から読み込めるよう、root_agent を公開する。
"""

import argparse
import asyncio
import inspect
import json
import os
from pathlib import Path
from typing import Callable

from google.adk.agents import Agent
from google.adk.events import Event
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools.base_toolset import BaseToolset
from google.adk.tools.mcp_tool import (
    McpToolset,
    StdioConnectionParams,
    StreamableHTTPConnectionParams,
)
from google.genai import types
from google.genai.errors import ClientError, ServerError
from mcp import StdioServerParameters

from app import tools
from app.config import MODEL, api_error_message, get_api_key

INSTRUCTIONS = """\
あなたはAIエンジニアリング講座（AIE2026）の学習支援エージェントです。
- 用語や講座に固有のことを答える前に、必ず search_glossary で用語集を確認する。
- 回の内容を聞かれたら get_lecture_summary を使う。
- 用語集に見つからないことは、推測で断定せず「用語集にはない」と伝える。
- 回答の最後に、関係する回（第N回）を示す。
- 宿題の答えそのものは書かず、考え方のヒントで導く。
"""

APP_NAME = "aie2026"
USER_ID = "student"
MCP_CONFIG = Path(__file__).resolve().parent / "mcp_servers.json"

def build_agent(toolsets: list[BaseToolset] | None = None) -> Agent:
    """直接登録したツール、またはMCP toolsetを使うADKエージェントを作る。"""
    registered_tools: list[Callable[..., str] | BaseToolset]
    if toolsets is None:
        registered_tools = [
            tools.search_glossary,
            tools.get_lecture_summary,
            tools.make_quiz,
        ]
    else:
        registered_tools = list(toolsets)
    return Agent(
        name="aie2026_learning_agent",
        description="AIE2026講座の用語と講義内容を案内する学習支援エージェント。",
        model=MODEL,
        instruction=INSTRUCTIONS,
        tools=registered_tools,
    )


agent = build_agent()
root_agent = agent


def load_mcp_servers(config_path: Path = MCP_CONFIG) -> list[McpToolset]:
    """MCP設定ファイルからADKのMCP toolsetを作る。"""
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))["mcpServers"]
    toolsets = []
    for name, spec in config.items():
        if "url" in spec:
            connection = StreamableHTTPConnectionParams(url=spec["url"])
        else:
            connection = StdioConnectionParams(
                server_params=StdioServerParameters(
                    command=spec["command"],
                    args=spec.get("args", []),
                    env=spec.get("env"),
                )
            )
        toolsets.append(McpToolset(connection_params=connection, tool_name_prefix=name))
    return toolsets


def build_mcp_agent(config_path: Path = MCP_CONFIG) -> Agent:
    """MCPサーバーからツールを受け取るADKエージェントを作る。"""
    return build_agent(load_mcp_servers(config_path))


async def _close_toolsets(target: Agent) -> None:
    for tool in target.tools:
        if isinstance(tool, BaseToolset):
            await tool.close()


def _print_tool(tool: object) -> None:
    name = getattr(tool, "name", getattr(tool, "__name__", type(tool).__name__))
    description = getattr(tool, "description", None) or inspect.getdoc(tool) or ""
    print(f"\n[{name}]")
    print("  " + inspect.cleandoc(description).replace("\n", "\n  "))
    if callable(tool):
        print(f"  引数: {inspect.signature(tool)}")
    else:
        get_declaration = getattr(tool, "_get_declaration", None)
        if get_declaration:
            declaration = get_declaration()
            parameters = declaration.parameters_json_schema or declaration.parameters
            if parameters:
                if hasattr(parameters, "model_dump"):
                    parameters = parameters.model_dump(exclude_none=True)
                print(f"  引数: {json.dumps(parameters, ensure_ascii=False)}")


async def print_tools(target: Agent) -> None:
    """エージェントに登録された関数ツールとMCPツールを表示する。"""
    count = 0
    try:
        for tool in target.tools:
            if isinstance(tool, BaseToolset):
                for mcp_tool in await tool.get_tools_with_prefix():
                    _print_tool(mcp_tool)
                    count += 1
            else:
                _print_tool(tool)
                count += 1
    finally:
        await _close_toolsets(target)
    print(f"\nモデルに見えているツール: {count} 個")


async def run_agent(target: Agent, question: str) -> list[Event]:
    """ADK Runnerで質問を実行し、生成されたイベントを返す。"""
    session_service = InMemorySessionService()
    session = await session_service.create_session(app_name=APP_NAME, user_id=USER_ID)
    runner = Runner(
        agent=target,
        app_name=APP_NAME,
        session_service=session_service,
    )
    return [
        event
        async for event in runner.run_async(
            user_id=USER_ID,
            session_id=session.id,
            new_message=types.Content(
                role="user",
                parts=[types.Part(text=question)],
            ),
        )
    ]


def print_trace(events: list[Event]) -> None:
    """ADKイベントからツール呼び出しと使用量を表示する。"""
    print("\n--- trace ---")
    for event in events:
        if not event.content:
            continue
        for part in event.content.parts:
            if part.function_call:
                call = part.function_call
                print(f"[tool call]   {call.name}({json.dumps(call.args, ensure_ascii=False)})")
            elif part.function_response:
                response = part.function_response
                print(f"[tool return] {response.name} -> {str(response.response)[:120]}…")
    usage = [
        event.usage_metadata.model_dump(exclude_none=True)
        for event in events
        if event.usage_metadata
    ]
    if usage:
        print(f"[usage] {json.dumps(usage, ensure_ascii=False)}")


def _answer(events: list[Event]) -> str:
    final_event = next(
        (event for event in reversed(events) if event.is_final_response()),
        None,
    )
    if final_event is None:
        raise RuntimeError("ADKから最終回答が返りませんでした。")
    if final_event.error_code:
        raise RuntimeError(f"ADKエラー: {final_event.error_code}: {final_event.error_message}")
    if final_event.content is None:
        raise RuntimeError("ADKの最終イベントに回答コンテンツがありません。")
    answer = "".join(part.text or "" for part in final_event.content.parts)
    if not answer:
        raise RuntimeError("ADKの最終イベントにテキスト回答がありません。")
    return answer


async def _run_cli(target: Agent, question: str, trace: bool) -> None:
    try:
        events = await run_agent(target, question)
        print(_answer(events))
        if trace:
            print_trace(events)
    except (ClientError, ServerError) as error:
        print(api_error_message(error.code, str(error)))
        raise SystemExit(1) from error
    finally:
        await _close_toolsets(target)


def main() -> None:
    parser = argparse.ArgumentParser(description="Google ADKで学習支援エージェントに質問する")
    parser.add_argument("question", nargs="?")
    parser.add_argument("--trace", action="store_true", help="ツール呼び出しを表示する")
    parser.add_argument("--mcp", action="store_true", help="ツールをMCPサーバーから受け取る")
    parser.add_argument("--list-tools", action="store_true", help="モデルに見えるツール一覧を表示する")
    args = parser.parse_args()
    print(1004)

    target = build_mcp_agent() if args.mcp else agent
    if args.list_tools:
        asyncio.run(print_tools(target))
        return
    if not args.question:
        parser.error("質問を指定してください")

    os.environ["GOOGLE_API_KEY"] = get_api_key()
    print(f"[model] {MODEL}")
    if args.mcp:
        print(f"[tools] MCPサーバー（{MCP_CONFIG}）")
    asyncio.run(_run_cli(target, args.question, args.trace))


if __name__ == "__main__":
    main()
