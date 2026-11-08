"""Requested correction to the launch article; video/script history stays intact."""
from datetime import datetime, timezone

LAUNCH_ARTICLE = "9e25dbbb-3aea-4c9d-98b6-6084042898c7"
TITLE = "How to check whether your raise beats inflation (US)"
REVISED = datetime(2026, 11, 8, tzinfo=timezone.utc)
BLOCKS = [
    ("p", "A bigger paycheck does not always buy more. To compare a raise with inflation, use your old pay, your new pay and a price change covering the same period. This guide uses a made-up example, not current wage or inflation figures."),
    ("h2", "Collect three matching numbers"),
    ("p", "Write down your old hourly pay and your new hourly pay. Use the same currency and the same pay basis for both. Then choose a price index covering the dates between those pay rates. For US examples, the Bureau of Labor Statistics explains its Consumer Price Index and inflation-adjusted earnings in the sources below."),
    ("h2", "Work through an example"),
    ("p", "Assume your hourly pay rose from $20 to $21, while prices rose 2% over that same period. These are hypothetical inputs. The pay increase is ($21 / $20 - 1) × 100 = 5%. To adjust for prices, divide the new pay by 1.02: $21 / 1.02 is approximately $20.59 in old-period purchasing power."),
    ("p", "The inflation-adjusted percentage change is (($21 / $20) / 1.02 - 1) × 100, or approximately 2.94%. Under these assumptions, purchasing power rose. Subtracting the two percentage rates gives an approximation; the division above is the precise calculation for this example."),
    ("h2", "Use the worksheet"),
    ("p", "Record: old pay; new pay; start date; end date; price index; inflation rate for those dates; nominal pay change; inflation-adjusted change. Keep a link to the index and note when you checked it. Use our raise-and-inflation calculator to repeat the arithmetic with your own inputs."),
    ("h2", "Know what the answer leaves out"),
    ("p", "This example keeps hours and the pay basis unchanged. It does not calculate take-home pay, taxes, benefits or changes in working hours. A broad consumer price index also does not reproduce every household's spending. Do not compare a monthly price change with an annual raise without matching the periods."),
    ("h2", "Check the result before using it"),
    ("p", "Confirm that both pay numbers use the same units, the inflation input covers the same dates, and the source describes the index you selected. An unemployment rate cannot replace your old wage in this calculation. This is an educational comparison, not a recommendation about an employment or financial decision."),
]
SOURCES = [
    {"title": "BLS: Real Earnings technical note", "publisher": "US Bureau of Labor Statistics", "url": "https://www.bls.gov/news.release/realer.tn.htm"},
    {"title": "BLS: Consumer Price Index questions and answers", "publisher": "US Bureau of Labor Statistics", "url": "https://www.bls.gov/cpi/questions-and-answers.htm"},
]


def example():
    return ((21 / 20) / 1.02 - 1) * 100
