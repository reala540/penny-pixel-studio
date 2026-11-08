"""Use illustrative footage for concrete tasks, preserving charts, steps and quantitative visuals."""

import re

TASKS = (
    (r"\b(document|pdf|report|summary)\b", "person reviewing document laptop desk"),
    (r"\b(spreadsheet|worksheet|budget)\b", "person checking spreadsheet laptop"),
    (r"\b(email|inbox|customer message)\b", "person writing email laptop"),
)


def plan(scenes):
    out = []
    promoted = 0
    last = -3
    for n, sc in enumerate(scenes):
        sc = {**sc, "visual": dict(sc["visual"])}
        v = sc["visual"]
        if (
            promoted < 3
            and n - last >= 3
            and 0 < n < len(scenes) - 1
            and v.get("type") == "title_card"
            and not re.search(r"\d|[$€£%]", sc.get("narration", ""))
        ):
            query = next(
                (
                    q
                    for pattern, q in TASKS
                    if re.search(pattern, sc.get("narration", ""), re.I)
                ),
                None,
            )
            if query:
                sc["visual"] = {**v, "type": "stock", "stock_query": query}
                sc["kicker"] = "Illustrative footage"
                promoted += 1
                last = n
        out.append(sc)
    return out
