from __future__ import annotations

import requests

from agent_side.input_data import collect_task_and_data
from agent_side.runner import run_agent_task
from he_common.config import SERVER_URL


def main() -> None:
    print("\n" + "#" * 72)
    print("Generalizable Homomorphic Encryption Agent")
    print("#" * 72)
    print("The LLM plans the operation schema. Raw data stays local and encrypted.")

    try:
        _, redacted_prompt, data, input_metadata = collect_task_and_data()
        print("\n[Agent] Asking planner for an HE operation schema without raw data...")
        run_agent_task(redacted_prompt, data, input_metadata=input_metadata)
    except requests.ConnectionError:
        print(f"\n[Agent] Could not reach server at {SERVER_URL}. Start it with: python server.py")
    except Exception as exc:
        print(f"\n[Agent] Error: {exc}")
