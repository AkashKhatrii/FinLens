"""Dedicated AI extractor for bank KPIs from official document pages.

Does not reuse the investment-research thesis prompt. The model only sees
supplied page text; missing values stay missing.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Literal

import anthropic
import openai
from openai import OpenAI
from pydantic import BaseModel, Field

from ..config import PROVIDERS, provider_key, provider_model
from ..providers.bank_documents import BankDocument
from ..providers.bank_metrics import BANK_METRIC_KEYS
from ..providers.pdf_text import PdfPage, format_pages_for_ai
from . import analyst

log = logging.getLogger(__name__)

BANK_KPI_SYSTEM_PROMPT = """You are extracting factual bank KPIs from an official bank document.

Use only information explicitly present in the supplied document.

Do not use outside knowledge.

Do not infer missing values.

Extract facts. Do not analyze or judge them.

For every extracted metric, provide the exact supporting evidence and page number when available.

For every candidate return:
- metric
- value
- unit
- period
- basis (point_in_time, yoy, or qoq)
- measurement where applicable (average or end_of_period)
- scope where available (standalone or consolidated)
- evidence
- page where available
- confidence

Distinguish current-period values from prior-period and compared-with values.

Distinguish YoY from QoQ.

Distinguish average from end-of-period.

Distinguish headline metrics from sub-series such as ex-agri, specific PCR, PCR including write-offs/AUCA, domestic NIM, or credit cost net of recoveries.

Distinguish standalone from consolidated values.

Distinguish CASA ratio from CASA deposit growth. CASA QAB/average and CASA MEB/period-end are different measurements.

Do not map AT1, Tier 1, or Tier 2 onto CAR or CET1 unless the document identifies that figure as the requested metric.

A parenthetical prior (Mar 31, 2026: 0.33%) or an "as against" comparison is not the current metric.

Do not map a combined line item such as upgrades and recoveries onto a single requested metric.

Extract bank-level figures, not subsidiary or group-company figures, unless the document is only about that entity.

Do not choose between multiple legitimate interpretations unless the document context clearly identifies the requested metric. When ambiguous, return the competing candidates rather than guessing.
"""

Basis = Literal["yoy", "qoq", "point_in_time"]
Scope = Literal["standalone", "consolidated"]
Measurement = Literal["average", "end_of_period"]
Unit = Literal["percent", "%", "bps", "₹ bn"]


class BankKpiCandidate(BaseModel):
    metric: str = Field(description="Normalized BankMetrics key such as gnpa or nim.")
    value: float
    unit: str = Field(description="percent, %, bps, or ₹ bn")
    period: str | None = Field(default=None, description="e.g. Q1 FY27, or null if unknown")
    basis: Basis | None = None
    measurement: Measurement | None = Field(
        default=None,
        description="average or end_of_period when the document distinguishes them; otherwise omit.",
    )
    scope: Scope | None = None
    series: str | None = Field(
        default=None,
        description=(
            "Sub-series such as ex_agri, specific, including_writeoffs, domestic, "
            "or net_of_recoveries; omit for headline."
        ),
    )
    evidence: str = Field(description="Exact supporting text from the supplied pages.")
    page: int | None = None
    confidence: float = Field(ge=0, le=1)
    raw_label: str = ""
    uncertain: bool = False


class BankKpiAiResponse(BaseModel):
    candidates: list[BankKpiCandidate] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def build_kpi_user_prompt(
    pages: list[PdfPage],
    document: BankDocument,
    target_period: str | None,
) -> str:
    allowed = ", ".join(BANK_METRIC_KEYS)
    schema = json.dumps(BankKpiAiResponse.model_json_schema(), indent=2)
    page_block = format_pages_for_ai(pages)
    return (
        f"Ticker: {document.ticker}\n"
        f"Document title: {document.title}\n"
        f"Document type: {document.document_type}\n"
        f"Document URL: {document.url}\n"
        f"Requested period: {target_period or document.period or 'unknown'}\n\n"
        "Return JSON only. Use metric names from this vocabulary:\n"
        f"{allowed}\n\n"
        "Represent percentages as percentage points (1.42% → value 1.42, unit percent), "
        "not as 0.0142.\n"
        "If a time series is oldest-to-newest, the current period is the last value.\n"
        "Do not return duplicate candidates that have the same metric, value, unit, period, "
        "basis, and measurement.\n"
        "When average and end-of-period growth both appear, return both candidates. "
        "When YoY and QoQ both appear, return both. Do not pick one.\n"
        "Headline GNPA is not GNPA ex-agri. Headline PCR is not specific PCR or PCR including AUCA/write-offs. "
        "Headline NIM is the overall/whole-bank figure, not domestic NIM. "
        "Headline credit cost is not net credit cost or credit cost net of recoveries. "
        "CASA ratio is not CASA deposit growth. CET-1 is CET1; AT1 CAR and Tier 2 CAR are not CAR or CET1.\n"
        "A compared-with, as-against, or parenthetical prior-period number is not the current metric.\n"
        "Do not populate a metric that is not explicitly present.\n\n"
        "JSON schema:\n"
        f"{schema}\n\n"
        "Document pages:\n"
        f"{page_block}\n"
    )


def complete_bank_kpi_json(system: str, user: str) -> dict[str, Any]:
    """Call the configured AI provider. Returns {candidates: ...} or {error: ...}."""
    st = analyst.status()
    if not st.get("available"):
        return {"error": st.get("reason") or "AI is not available."}
    key = st["provider"]
    spec = PROVIDERS[key]
    model = st["model"]
    if spec["kind"] == "anthropic":
        return _claude_kpis(system, user, model)
    return _openai_kpis(spec, system, user, key, model)


def extract_kpis_from_pages(
    pages: list[PdfPage],
    document: BankDocument,
    target_period: str | None,
) -> dict[str, Any]:
    return complete_bank_kpi_json(
        BANK_KPI_SYSTEM_PROMPT,
        build_kpi_user_prompt(pages, document, target_period),
    )


def _openai_kpis(
    spec: dict[str, Any], system: str, user: str, provider: str, model: str,
) -> dict[str, Any]:
    client = OpenAI(
        api_key=os.getenv(spec["api_key_env"]),
        base_url=spec["base_url"],
        timeout=120.0,
    )
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=8192,
            response_format={"type": "json_object"},
            extra_body={"thinking": {"type": "disabled"}},
        )
    except openai.AuthenticationError:
        log.warning("%s credentials rejected during bank KPI extraction.", spec["label"])
        return {"error": f"{spec['label']} credentials were rejected."}
    except openai.RateLimitError as exc:
        log.warning("Rate limited by %s during bank KPI extraction: %s", spec["label"], exc)
        return {"error": "Rate limited by the AI provider."}
    except openai.APITimeoutError:
        log.warning("%s bank KPI extraction timed out.", spec["label"])
        return {"error": "The AI provider timed out."}
    except openai.APIStatusError as exc:
        log.warning("%s KPI API error %s: %s", spec["label"], exc.status_code, exc.message)
        return {"error": f"AI provider returned {exc.status_code}."}
    except openai.APIConnectionError:
        log.warning("Network error reaching %s for bank KPI extraction.", spec["label"])
        return {"error": "Could not reach the AI provider."}
    except Exception as exc:
        log.exception("Bank KPI extraction failed: %s", exc)
        return {"error": f"Bank KPI extraction failed: {exc}"}

    content = ""
    if response.choices:
        msg = response.choices[0].message
        content = (getattr(msg, "content", None) or getattr(msg, "reasoning_content", None) or "")
    if not str(content).strip():
        return {"error": "The AI response was empty."}
    try:
        parsed = analyst._parse_json_object(str(content))
    except (json.JSONDecodeError, ValueError) as exc:
        log.warning("Bank KPI JSON did not parse: %s", exc)
        return {"error": "The AI response did not match the expected format."}
    if not isinstance(parsed, dict):
        return {"error": "The AI response did not match the expected format."}
    parsed["provider"] = provider
    parsed["model"] = model
    return parsed


def _claude_kpis(system: str, user: str, model: str) -> dict[str, Any]:
    client = analyst._get_anthropic_client()
    if client is None:
        return {"error": "Anthropic SDK could not be initialised."}
    try:
        response = client.messages.parse(
            model=model,
            system=[{"type": "text", "text": system}],
            messages=[{"role": "user", "content": user}],
            output_format=BankKpiAiResponse,
            **analyst._claude_parse_options(),
        )
    except anthropic.AuthenticationError:
        return {"error": "Anthropic credentials were rejected."}
    except anthropic.RateLimitError:
        return {"error": "Rate limited by the AI provider."}
    except anthropic.APITimeoutError:
        return {"error": "Claude timed out."}
    except anthropic.APIStatusError as exc:
        return {"error": f"AI provider returned {exc.status_code}."}
    except anthropic.APIConnectionError:
        return {"error": "Could not reach the AI provider."}
    except Exception as exc:
        log.exception("Bank KPI extraction failed: %s", exc)
        return {"error": "The AI response did not match the expected format."}

    parsed = response.parsed_output
    if parsed is None:
        return {"error": "No structured output returned."}
    payload = parsed.model_dump()
    payload["provider"] = "claude"
    payload["model"] = model
    return payload
