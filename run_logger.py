"""Run logger — tracks tokens, cost, latency, and tool calls per step.

Provides a RunLogger that accumulates metrics across steps, prints a
per-step summary to the terminal, and saves the full run to a JSON file.
"""

import json
import time
from datetime import datetime
from pathlib import Path

# Pricing per 1M tokens (Claude Sonnet 4.6, as of 2025)
# Update these if you switch models
PRICING = {
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    "claude-opus-4-6": {"input": 15.00, "output": 75.00},
}

LOGS_DIR = Path(__file__).parent / "logs"


class StepMetrics:
    """Metrics for a single agent step."""

    def __init__(self, step_name: str):
        self.step_name = step_name
        self.start_time = time.time()
        self.end_time = None
        self.input_tokens = 0
        self.output_tokens = 0
        self.api_calls = 0
        self.tool_calls: list[dict] = []
        self.retries = 0
        self.model = ""
        self.error = None

    def record_api_response(self, response):
        """Record metrics from an API response."""
        self.api_calls += 1
        if hasattr(response, "usage"):
            self.input_tokens += response.usage.input_tokens
            self.output_tokens += response.usage.output_tokens
        if hasattr(response, "model"):
            self.model = response.model

    def record_tool_call(self, tool_name: str, input_summary: str, result_length: int):
        """Record a tool call."""
        self.tool_calls.append({
            "tool": tool_name,
            "input": input_summary,
            "result_chars": result_length,
        })

    def record_retry(self):
        """Record a retry attempt."""
        self.retries += 1

    def finish(self, error: str = None):
        """Mark this step as complete."""
        self.end_time = time.time()
        self.error = error

    @property
    def latency(self) -> float:
        end = self.end_time or time.time()
        return end - self.start_time

    @property
    def cost(self) -> float:
        prices = PRICING.get(self.model, PRICING.get("claude-sonnet-4-6"))
        input_cost = (self.input_tokens / 1_000_000) * prices["input"]
        output_cost = (self.output_tokens / 1_000_000) * prices["output"]
        return input_cost + output_cost

    def to_dict(self) -> dict:
        return {
            "step": self.step_name,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "api_calls": self.api_calls,
            "tool_calls": self.tool_calls,
            "retries": self.retries,
            "latency_seconds": round(self.latency, 1),
            "cost_usd": round(self.cost, 5),
            "model": self.model,
            "error": self.error,
        }

    def summary_line(self) -> str:
        """One-line summary for terminal output."""
        tools = f", tools: {len(self.tool_calls)}" if self.tool_calls else ""
        retries = f", retries: {self.retries}" if self.retries else ""
        error = " [FAILED]" if self.error else ""
        return (
            f"  {self.input_tokens:,} in / {self.output_tokens:,} out | "
            f"${self.cost:.4f} | {self.latency:.1f}s"
            f"{tools}{retries}{error}"
        )


class RunLogger:
    """Accumulates metrics across all steps in a run."""

    def __init__(self):
        self.steps: list[StepMetrics] = []
        self.current_step: StepMetrics = None
        self.run_start = time.time()
        self.metadata: dict = {}

    def start_step(self, step_name: str) -> StepMetrics:
        """Start tracking a new step."""
        self.current_step = StepMetrics(step_name)
        self.steps.append(self.current_step)
        return self.current_step

    def finish_step(self, error: str = None):
        """Finish the current step and print its summary."""
        if self.current_step:
            self.current_step.finish(error)
            print(self.current_step.summary_line())
            self.current_step = None

    @property
    def total_input_tokens(self) -> int:
        return sum(s.input_tokens for s in self.steps)

    @property
    def total_output_tokens(self) -> int:
        return sum(s.output_tokens for s in self.steps)

    @property
    def total_cost(self) -> float:
        return sum(s.cost for s in self.steps)

    @property
    def total_latency(self) -> float:
        return time.time() - self.run_start

    @property
    def total_retries(self) -> int:
        return sum(s.retries for s in self.steps)

    @property
    def failed_steps(self) -> int:
        return sum(1 for s in self.steps if s.error)

    def print_summary(self):
        """Print a formatted run summary to the terminal."""
        print("\n" + "=" * 60)
        print("RUN SUMMARY")
        print("=" * 60)

        # Per-step breakdown
        print(f"\n{'Step':<25} {'Tokens':>14} {'Cost':>9} {'Time':>7}")
        print("-" * 60)
        for step in self.steps:
            tokens = f"{step.input_tokens:,}+{step.output_tokens:,}"
            status = " *" if step.error else ""
            print(f"  {step.step_name:<23} {tokens:>14} ${step.cost:>7.4f} {step.latency:>5.1f}s{status}")

        # Totals
        print("-" * 60)
        total_tokens = f"{self.total_input_tokens:,}+{self.total_output_tokens:,}"
        print(f"  {'TOTAL':<23} {total_tokens:>14} ${self.total_cost:>7.4f} {self.total_latency:>5.1f}s")

        # Extras
        extras = []
        if self.total_retries:
            extras.append(f"Retries: {self.total_retries}")
        if self.failed_steps:
            extras.append(f"Failed steps: {self.failed_steps}")
        if extras:
            print(f"\n  {' | '.join(extras)}")

        print()

    def save(self, filename: str = None):
        """Save the full run log to a JSON file."""
        LOGS_DIR.mkdir(exist_ok=True)

        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"run_{timestamp}.json"

        run_data = {
            "timestamp": datetime.now().isoformat(),
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_cost_usd": round(self.total_cost, 5),
            "total_latency_seconds": round(self.total_latency, 1),
            "total_retries": self.total_retries,
            "failed_steps": self.failed_steps,
            "metadata": self.metadata,
            "steps": [s.to_dict() for s in self.steps],
        }

        path = LOGS_DIR / filename
        path.write_text(json.dumps(run_data, indent=2), encoding="utf-8")
        print(f"Run log saved to {path}")
        return path
