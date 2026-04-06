"""Core agent loop — each step gets only the state it needs, not full history."""

import time
import anthropic
from tools import TOOL_DEFINITIONS, execute_tool
from run_logger import StepMetrics

AVAILABLE_MODELS = {
    "sonnet": "claude-sonnet-4-6",
    "haiku": "claude-haiku-4-5-20251001",
    "opus": "claude-opus-4-6",
}

# Default model for steps not listed in STEP_MODELS
_DEFAULT_MODEL = AVAILABLE_MODELS["sonnet"]

# Per-step model routing.
# Haiku: analytical steps with no creative generation (read + score + judge).
# Sonnet: steps that write content or require nuanced judgment under pressure.
STEP_MODELS = {
    "company_research":  AVAILABLE_MODELS["haiku"],
    "role_analysis":     AVAILABLE_MODELS["haiku"],
    "gap_analysis":      AVAILABLE_MODELS["haiku"],
    "gap_reassessment":  AVAILABLE_MODELS["haiku"],
    "critic_review":     AVAILABLE_MODELS["haiku"],
    # Sonnet (default) for all writing and revision steps:
    # gap_update, project_selection, cv_construction, cover_letter,
    # critic_revision, guardrail_fix, revision
}

# Override — set by --model flag to force a single model for all steps
_model_override: str | None = None


def set_model(name: str) -> None:
    """Force all steps to use one model (e.g. for --model haiku test runs)."""
    global _model_override
    _model_override = AVAILABLE_MODELS.get(name, name)
    print(f"  [model] All steps overridden to {_model_override}")


def _model_for_step(step_name: str | None) -> str:
    if _model_override:
        return _model_override
    if step_name:
        return STEP_MODELS.get(step_name, _DEFAULT_MODEL)
    return _DEFAULT_MODEL


MAX_RETRIES = 5
RETRY_DELAY = 5  # seconds

# Temperature per step type — analytical steps get 0, creative steps get some variance
STEP_TEMPERATURES = {
    "company_research": 0,
    "role_analysis": 0,
    "hiring_manager": 0,
    "gap_analysis": 0,
    "gap_reassessment": 0,
    "gap_update": 0,
    "project_selection": 0,
    "cv_construction": 0.3,
    "cover_letter": 0.4,
    "revision": 0.3,
    "critic_review": 0,
}
DEFAULT_TEMPERATURE = 0


def _api_call_with_retry(client, system_prompt, messages, temperature=0, metrics=None, tools=None, model=None):
    """Call the Anthropic API with retry logic for connection and rate limit errors."""
    if tools is None:
        tools = TOOL_DEFINITIONS
    if model is None:
        model = _DEFAULT_MODEL
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=4096,
                temperature=temperature,
                system=system_prompt,
                tools=tools,
                messages=messages,
            )
            if metrics:
                metrics.record_api_response(response)
            return response
        except (anthropic.RateLimitError, anthropic.OverloadedError):
            if metrics:
                metrics.record_retry()
            if attempt == MAX_RETRIES:
                raise
            wait = RETRY_DELAY * (2 ** (attempt - 1))
            print(f"  [rate limit] Waiting {wait}s... (attempt {attempt}/{MAX_RETRIES})")
            time.sleep(wait)
        except (anthropic.APIConnectionError, anthropic.APITimeoutError):
            if metrics:
                metrics.record_retry()
            if attempt == MAX_RETRIES:
                raise
            print(f"  [retry] Connection error. Waiting {RETRY_DELAY}s... (attempt {attempt}/{MAX_RETRIES})")
            time.sleep(RETRY_DELAY)


def run_step(
    client: anthropic.Anthropic,
    system_prompt: str,
    user_message: str,
    metrics: StepMetrics = None,
    step_name: str = None,
    exclude_tools: list[str] = None,
) -> str:
    """Run a single stateless step.

    Each call starts a FRESH conversation — no history carried over.
    The caller is responsible for injecting relevant state into user_message.
    step_name drives both temperature and model selection (see STEP_MODELS).
    exclude_tools filters out specific tools (e.g. ["generate_pdf"]).
    """
    temperature = STEP_TEMPERATURES.get(step_name, DEFAULT_TEMPERATURE)
    model = _model_for_step(step_name)
    messages = [{"role": "user", "content": user_message}]

    tools = TOOL_DEFINITIONS
    if exclude_tools:
        tools = [t for t in TOOL_DEFINITIONS if t["name"] not in exclude_tools]

    while True:
        response = _api_call_with_retry(client, system_prompt, messages, temperature, metrics, tools=tools, model=model)

        assistant_content = response.content
        messages.append({"role": "assistant", "content": assistant_content})

        # Check for tool calls
        tool_use_blocks = [b for b in assistant_content if b.type == "tool_use"]
        if not tool_use_blocks:
            text_parts = [b.text for b in assistant_content if b.type == "text"]
            return "\n".join(text_parts)

        # Execute tools and continue
        tool_results = []
        for tool_block in tool_use_blocks:
            result = execute_tool(tool_block.name, tool_block.input)
            input_summary = _summarize_input(tool_block.input)
            print(f"  [tool] {tool_block.name}({input_summary}) -> {len(result)} chars")
            if metrics:
                metrics.record_tool_call(tool_block.name, input_summary, len(result))
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_block.id,
                "content": result,
            })

        messages.append({"role": "user", "content": tool_results})


def _summarize_input(inp: dict) -> str:
    """Short summary of tool input for logging."""
    parts = []
    for k, v in inp.items():
        s = str(v)
        if len(s) > 60:
            s = s[:57] + "..."
        parts.append(f"{k}={s!r}")
    return ", ".join(parts)
