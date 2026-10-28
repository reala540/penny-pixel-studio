"""Validated structures exchanged with the AI models."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

WORDS_PER_SECOND = 2.5  # ~150 words per minute narration


def est_seconds(text: str, speed: float = 1.0) -> float:
    words = len(re.findall(r"\S+", text))
    return round(words / (WORDS_PER_SECOND * speed), 2)


class Fact(BaseModel):
    key: str = Field(description="F1, F2, ...")
    text: str = Field(description="One factual statement taken from the sources")
    source_ref: str = Field(description="Source label, e.g. S2")
    data_period: str | None = Field(default=None, description="Time period the data refers to, if any")


class FactSheet(BaseModel):
    facts: list[Fact]
    context: str = Field(default="", description="Two or three sentences of background")
    open_questions: list[str] = Field(default_factory=list)


class ChartSpec(BaseModel):
    kind: Literal["bar", "line"] = "bar"
    title: str
    labels: list[str]
    values: list[float]
    unit: str = ""
    source_note: str = ""

    @field_validator("values")
    @classmethod
    def same_length(cls, v, info):
        labels = info.data.get("labels") or []
        if labels and len(v) != len(labels):
            raise ValueError("chart labels and values must have the same length")
        return v


class Visual(BaseModel):
    type: Literal["title_card", "stat", "chart", "list", "quote", "stock", "steps", "comparison", "animated"]
    animation: Literal["budget_jars", "price_basket", "agent_handoff", "counter"] | None = Field(
        default=None, description="For type=animated: which original animation explains this sentence")
    headline: str | None = None
    items: list[str] = Field(default_factory=list)
    stat_value: str | None = None
    stat_label: str | None = None
    chart: ChartSpec | None = None
    stock_query: str | None = Field(default=None, description="Search words for a licensed stock photo")


class Scene(BaseModel):
    narration: str
    on_screen_text: str | None = None
    visual: Visual
    claim_keys: list[str] = Field(default_factory=list, description="Keys of claims made in this scene")


class Claim(BaseModel):
    key: str = Field(description="C1, C2, ...")
    text: str
    kind: Literal["fact", "opinion", "calculation"] = "fact"
    fact_refs: list[str] = Field(default_factory=list, description="Fact keys from the fact sheet (F1...)")
    expression: str = Field(default="", description="For kind=calculation: the exact arithmetic, e.g. 200*12*10")


class Script(BaseModel):
    title: str
    hook: str
    promise: str = Field(description="One sentence: what the viewer will get")
    hook_candidates: list[str] = Field(default_factory=list)
    scenes: list[Scene]
    claims: list[Claim] = Field(default_factory=list)
    cta: str

    def full_text(self) -> str:
        return " ".join(s.narration for s in self.scenes)

    def duration(self, speed: float = 1.0) -> float:
        return sum(est_seconds(s.narration, speed) for s in self.scenes)


class ClaimVerdict(BaseModel):
    key: str
    status: Literal["supported", "partially_supported", "unsupported", "contradicted", "opinion"]
    supporting_quote: str = Field(default="", description="Exact sentence copied from the fact sheet/source")
    note: str = ""


class ClaimVerdicts(BaseModel):
    verdicts: list[ClaimVerdict]


class CriticReport(BaseModel):
    hook: int = Field(ge=1, le=10)
    originality: int = Field(ge=1, le=10)
    clarity: int = Field(ge=1, le=10)
    pacing: int = Field(ge=1, le=10)
    value: int = Field(ge=1, le=10)
    fixes: list[str] = Field(default_factory=list, description="Specific changes, each naming a scene number")
    weak_scenes: list[int] = Field(default_factory=list, description="1-based scene numbers that need rewriting")

    def minimum(self) -> int:
        return min(self.hook, self.originality, self.clarity, self.pacing, self.value)


class OutlineSection(BaseModel):
    name: str = Field(description="Short section heading")
    kind: Literal["problem", "learn", "body", "limits", "wrap"] = "body"
    purpose: str = Field(description="What this section must achieve for the viewer, in one sentence")
    fact_keys: list[str] = Field(default_factory=list, description="Fact keys (F1...) this section uses")


class Outline(BaseModel):
    title: str
    hook: str
    promise: str = Field(description="One sentence: what the viewer will get")
    hook_candidates: list[str] = Field(default_factory=list)
    sections: list[OutlineSection]
    cta: str


class SectionDraft(BaseModel):
    scenes: list[Scene]
    claims: list[Claim] = Field(default_factory=list)


class SceneRewrite(BaseModel):
    scenes: list[Scene]


class ShortScript(BaseModel):
    title: str
    hook: str
    scenes: list[Scene]
    caption: str = Field(description="YouTube Shorts caption")
    hashtags: list[str] = Field(default_factory=list)
    tiktok_caption: str | None = Field(default=None, description="A different, shorter caption written for TikTok")
    reel_caption: str | None = Field(default=None, description="A different caption written for Facebook Reels")


class Package(BaseModel):
    youtube_title: str
    youtube_description: str
    tags: list[str]
    thumbnail_headlines: list[str] = Field(description="Three different 2-5 word thumbnail texts")
    x_post: str = Field(description="Under 270 characters, no links")
    facebook_post: str
    shorts: list[ShortScript] = Field(description="Two purpose-built Shorts, each 35-55 seconds")
