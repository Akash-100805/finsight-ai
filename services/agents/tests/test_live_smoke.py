"""Live smoke check of the three new LLM prompts (build guide phase 4: the cheapest point to catch a bad prompt).

EXACTLY ONE real call each to the Sector agent, the Fundamental agent and the Conflict Resolver, from recorded inputs (tests/fixtures/live_smoke/).
No retry and no repair (LLMClient.complete_raw), so the raw outputs are what the model really answered. The raw text, the parsed object and the
validator's verdict are printed; read them with -s. The test fails only when there is no usable reply at all (no key / model, an error from the
provider, a non-JSON reply) - a validation problem is a finding about the prompt, printed, not a test failure.

NOT part of the normal suite and never run without the owner's go-ahead (it uses Gemini quota):

    pytest -m live_smoke --run-live-smoke -s tests/test_live_smoke.py
"""
import json
from pathlib import Path

import pytest

from finsight.data.llm import LLMClient
from finsight.flow import conflict_resolver as cr, fundamental_agent as fa, sector_agent as sa
from finsight.schemas.state import ConflictResolution
from finsight.settings import get_settings

pytestmark = pytest.mark.live_smoke
INPUTS = Path(__file__).parent / "fixtures" / "live_smoke"


def load(name: str) -> dict:
    return json.loads((INPUTS / name).read_text(encoding="utf-8"))


@pytest.fixture()
def llm() -> LLMClient:
    s = get_settings()
    s.llm_api_key()                      # raises SettingsError naming the missing key
    s.llm_model("stock"), s.llm_model("synth")
    return LLMClient(s)


def one_call(llm: LLMClient, label: str, system: str, user: str, schema, role: str):
    before = llm.calls_made
    raw = llm.complete_raw(system, user, schema, model_role=role)
    assert llm.calls_made == before + 1, "exactly one real call per agent"
    print(f"\n===== {label}: RAW OUTPUT (model role {role}, {raw.input_tokens} in / {raw.output_tokens} out) =====\n{raw.text}")
    parsed = schema.model_validate_json(raw.text.strip().removeprefix("```json").removesuffix("```").strip())
    print(f"----- {label}: parsed OK -----")
    return parsed


def test_sector_agent_prompt(llm):
    inp = load("sector_input.json")
    out = one_call(llm, "SECTOR AGENT", sa.SECTOR_SYSTEM, "Sector facts (JSON):\n" + json.dumps(inp), sa.SectorNarrative, "stock")
    print("validator problems:", sa.validate(out, inp["sector_id"], inp) or "none")


def test_fundamental_agent_prompt(llm):
    view = load("fundamental_view.json")
    out = one_call(llm, "FUNDAMENTAL AGENT", fa.FUNDAMENTAL_SYSTEM, "Computed metrics (JSON):\n" + json.dumps(view), fa.FundamentalLLMOutput, "stock")
    print("validator problems:", fa.validate(out, view["security_id"], view) or "none")


def test_conflict_resolver_prompt(llm):
    inp = load("resolver_input.json")
    out = one_call(llm, "CONFLICT RESOLVER", cr.RESOLVER_SYSTEM, "Stock reads (JSON):\n" + json.dumps(inp), ConflictResolution, "synth")
    print("validator problems:", cr.validate(out, inp) or "none")
