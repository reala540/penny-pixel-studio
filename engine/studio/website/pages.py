"""The website's standing pages: who we are, how we work, and the rules. Written plainly and only promising what the
system really does. A contact email is shown only if the owner has set one (config/services.yaml website.contact_email);
otherwise readers are pointed to the public social accounts."""

from __future__ import annotations

from .render import SITE_HTML, e


def _contact(email: str | None, socials: list[dict]) -> str:
    if email:
        return f'email <a href="mailto:{e(email)}">{e(email)}</a>'
    if socials:
        return "send us a message on " + ", ".join(f'<a href="{e(s["url"])}" rel="noopener">{e(s["name"])}</a>' for s in socials)
    return "send us a message through any of our social channels"


def standing_pages(email: str | None, socials: list[dict]) -> dict[str, tuple[str, str, str]]:
    """{path: (title, description, body html)}"""
    contact = _contact(email, socials)
    return {
        "/about/": ("About us", "Who Penny & Pixel are and how every article is checked.", f"""
<p>{SITE_HTML} publishes practical guides about two things that shape everyday life: <strong>AI tools</strong> and <strong>money</strong>.
We write for readers in the United States, the United Kingdom, Canada, Australia, Germany and everywhere else people want clear answers.</p>
<h2>Pixel and Penny</h2><p><strong>Pixel</strong> explains what AI tools can really do at work and at home, without the hype.
<strong>Penny</strong> explains budgeting, saving, paychecks, prices and credit with real numbers and their sources.</p>
<h2>How we work</h2><ul><li>Every article starts as one of our videos and is researched with the help of AI tools.</li>
<li>Every factual claim is checked against a named source, and the sources are listed under the article with their dates.</li>
<li>Articles with claims we couldn't back are not published.</li><li>We say when something is an opinion, a forecast or an estimate.</li>
<li>We never claim to have tested a product ourselves unless we did.</li></ul>
<p>Read our <a href="/editorial-policy/">editorial policy</a> and <a href="/ai-content-policy/">AI content policy</a>.</p>"""),
        "/contact/": ("Contact", "How to reach Penny & Pixel.", f"""
<p>To reach us, {contact}.</p><p>For mistakes in an article, please see our <a href="/corrections/">corrections policy</a>.
For partnerships, see <a href="/advertise/">advertise with us</a>.</p>"""),
        "/editorial-policy/": ("Editorial policy", "How Penny & Pixel chooses, researches and checks what it publishes.", """
<h2>What we cover</h2><p>Practical AI tools and technology, and money basics: budgeting, saving, inflation, pay and prices.
We prefer evergreen questions people actually ask over chasing every headline.</p>
<h2>Sources</h2><p>We prefer primary sources: official statistics agencies, official documentation and announcements, and reputable
reporting. Every source is listed under the article with its publication date.</p>
<h2>Accuracy</h2><ul><li>Numbers must appear in their source; sums are recalculated by code.</li>
<li>Old figures are given with their date, never presented as current.</li><li>Forecasts are attributed to whoever made them.</li>
<li>An article with a claim we couldn't back is not published.</li></ul>
<h2>Money content</h2><p>Money articles are general education, not personal financial advice. Rules, taxes and prices differ by
country; when an article is about one country it says so.</p>
<h2>Independence</h2><p>Affiliate links and sponsorships never decide what we write. Affiliate links are labeled where they
appear; see our <a href="/affiliate-disclosure/">affiliate disclosure</a>.</p>"""),
        "/ai-content-policy/": ("AI content policy", "How Penny & Pixel uses AI tools, and what we never let them do.", """
<p>We use AI tools to research topics, draft scripts and narrate our videos. Our videos use an AI voice.</p>
<h2>What checks the AI</h2><ul><li>Every factual claim is checked against the passage of the source it comes from.</li>
<li>Numbers that aren't in a source, and sums that don't add up, stop an article from being published.</li>
<li>Repeated sentences, video-only phrases and claims of tests we didn't run are removed before publishing.</li></ul>
<h2>What we never do</h2><ul><li>Invent quotes, sources, reviews, ratings or statistics.</li>
<li>Claim we personally tested something we didn't.</li><li>Present AI-generated footage as real news footage.</li></ul>
<p>Automatic checks reduce mistakes but can't remove every one. If you find one, see our <a href="/corrections/">corrections policy</a>.</p>"""),
        "/corrections/": ("Corrections policy", "How to report a mistake and how Penny & Pixel corrects articles.", f"""
<p>We want every article to be right. If you think something is wrong, {contact}, with the article's address and what you
think is wrong (a link to a better source helps).</p>
<h2>What we do</h2><ul><li>We check the claim against the sources.</li><li>If it's wrong, we correct the article, or remove it
if it can't be fixed.</li><li>Removed articles stop appearing on the site at the next update.</li></ul>"""),
        "/advertise/": ("Advertise with us", "Sponsorship and partnership options with Penny & Pixel.", f"""
<p>{SITE_HTML} publishes practical AI and money guides for readers mainly in the United States, the United Kingdom, Canada,
Australia and Germany, alongside our YouTube, Facebook and X channels.</p>
<h2>Formats</h2><ul><li>A clearly labeled sponsored segment in a relevant video or article</li>
<li>A labeled placement in an article about a related topic</li></ul>
<h2>Our rules</h2><ul><li>Sponsored content is always labeled as sponsored.</li><li>Sponsors don't review or approve our
articles, and our editorial checks apply to everything we publish.</li><li>We only work with products relevant to our readers.</li></ul>
<p>We're a new publication, so we don't publish audience statistics yet; ask us for current numbers. To get in touch, {contact}.</p>"""),
        "/privacy/": ("Privacy policy", "What this website collects (very little) and why.", f"""
<p>{SITE_HTML} is a reading website. It has no accounts and no comments, and it doesn't set cookies of its own.</p>
<h2>Hosting</h2><p>The site is hosted by Cloudflare, which processes standard technical information (such as IP address and
browser type) to deliver and protect the pages. If visitor statistics are switched on, Cloudflare Web Analytics counts visits
without cookies. See the <a href="https://www.cloudflare.com/privacypolicy/">Cloudflare privacy policy</a>.</p>
<h2>Videos</h2><p>Videos load from youtube-nocookie.com only when you press play. Once you do, YouTube's terms and the
<a href="https://policies.google.com/privacy">Google Privacy Policy</a> apply.</p>
<h2>Newsletter</h2><p>If a newsletter sign-up is offered, your email address goes to the newsletter provider named on the form,
only with your consent, and every email includes an unsubscribe link.</p>
<h2>Optional conversion measurements</h2><p>If a measurement service is connected, link clicks, downloads and newsletter form submissions may be counted with the page path. Email addresses and form values are not included in those events. A form submission does not prove a confirmed subscription or purchase.</p>
<h2>Links</h2><p>Articles link to sources and sometimes to affiliate offers. Other websites have their own privacy policies.</p>
<h2>Contact</h2><p>For privacy questions, {contact}.</p>"""),
        "/terms/": ("Terms of use", "The terms for using the Penny & Pixel website.", """
<p>By using this website you agree to these terms.</p><h2>Information only</h2><p>Our articles and videos are general education.
They are not personal financial, legal, tax or professional advice. Check important decisions with a qualified professional.</p>
<h2>Accuracy</h2><p>We check facts against their sources, but information can change after publication; each article shows the
date its facts are from.</p><h2>Optional conversion measurements</h2><p>If a measurement service is connected, link clicks, downloads and newsletter form submissions may be counted with the page path. Email addresses and form values are not included in those events. A form submission does not prove a confirmed subscription or purchase.</p>
<h2>Links</h2><p>We aren't responsible for the content of other websites we link to.</p>
<h2>Copyright</h2><p>Articles, images and videos are ours unless stated otherwise. You may share links freely.</p>"""),
        "/affiliate-disclosure/": ("Affiliate disclosure", "How affiliate links work on Penny & Pixel.", """
<p>Some articles contain affiliate links. If you buy or sign up through one, we may earn a commission at no extra cost to you.
Affiliate links are always labeled where they appear.</p>
<p>Affiliate offers never change what our articles say: articles are written from our checked research first, and an offer is
added only when it matches the topic. Money articles are general education, not personal financial advice: compare options
before you sign up for anything.</p>"""),
    }
