"""Channel trailers: real voices, real rendering, no factual claims — so they need no AI keys.

Useful as the first upload on each channel and as a smoke test of the video engine.
"""

from __future__ import annotations

TRAILERS = {
    "ai": {
        "title": "Meet Pixel: AI, minus the hype",
        "hook": "Hi, I'm Pixel. Every week a new AI tool promises to change your life. Most of them won't.",
        "scenes": [
            {"narration": "So here's the deal. I test the tools, read the fine print, and tell you what actually "
                          "works for normal people with normal jobs.",
             "visual": {"type": "title_card", "headline": "AI tools, tested in plain words"}},
            {"narration": "Every video gives you three things. What changed. Why it matters to you. And one thing "
                          "you can try today, usually for free.",
             "visual": {"type": "steps", "headline": "Every video, three things",
                        "items": ["What changed", "Why it matters to you", "One thing to try today"]}},
            {"narration": "No breathless headlines. If something is overhyped, I'll say so. If it's genuinely useful, "
                          "I'll show you exactly how to use it.",
             "visual": {"type": "comparison", "headline": "Our promise",
                        "items": ["Hype | Us", "Breathless headlines | Calm, tested answers", "Vague claims | Sources on screen"]}},
        ],
        "cta": "If that sounds like your kind of channel, subscribe, and I'll see you in the next one.",
    },
    "money": {
        "title": "Meet Penny: money, explained like a friend would",
        "hook": "Hi, I'm Penny. Money advice online is loud. I'd rather be useful.",
        "scenes": [
            {"narration": "On this channel we keep it calm and clear. We look at the real numbers, we name the "
                          "trade-offs, and we always say where the numbers come from.",
             "visual": {"type": "title_card", "headline": "Calm, clear money skills"}},
            {"narration": "You'll learn budgeting that survives real life, investing basics without the jargon, and "
                          "how to ask for the salary you deserve.",
             "visual": {"type": "list", "headline": "What you'll learn",
                        "items": ["Budgets that survive real life", "Investing basics, no jargon", "Salary and career moves"]}},
            {"narration": "And one promise. Fact first, then opinion, and I'll always tell you which is which. This is "
                          "general education, not personal advice.",
             "visual": {"type": "quote", "headline": "Fact first, then opinion. Always labelled."}},
        ],
        "cta": "If you want to feel more in control of your money, subscribe. Let's do the math together.",
    },
}

SHORT_TRAILERS = {
    "ai": {"title": "Free AI that actually works", "hook": "Stop paying for AI tools you can get free.",
           "scenes": [{"narration": "I'm Pixel. I test the free stuff so you don't waste your money.",
                       "visual": {"type": "title_card", "headline": "I test free AI tools for you"}},
                      {"narration": "Follow for one useful AI trick every week.",
                       "visual": {"type": "title_card", "headline": "One useful trick a week"}}],
           "caption": "Pixel tests AI so you don't have to.", "hashtags": ["AI", "AItools", "tech"]},
    "money": {"title": "Money, minus the drama", "hook": "Money advice online is loud. Let's make it useful.",
              "scenes": [{"narration": "I'm Penny. Real numbers, clear trade-offs, no get-rich-quick nonsense.",
                          "visual": {"type": "title_card", "headline": "Real numbers. No hype."}},
                         {"narration": "Follow for calm money skills every week.",
                          "visual": {"type": "title_card", "headline": "Calm money skills weekly"}}],
              "caption": "Penny explains money like a friend would.", "hashtags": ["money", "budgeting", "finance"]},
}
