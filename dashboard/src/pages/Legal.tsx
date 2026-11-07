import { Link } from "react-router-dom";

const UPDATED = "7 November 2026";

function Page({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <main className="mx-auto max-w-2xl px-5 py-12">
      <Link to="/" className="text-sm text-muted hover:underline">Penny &amp; Pixel</Link>
      <h1 className="mt-4 font-display text-3xl font-bold">{title}</h1>
      <p className="mt-1 text-sm text-muted">Last updated {UPDATED}</p>
      <div className="mt-8 space-y-5 leading-relaxed [&_h2]:mt-8 [&_h2]:font-display [&_h2]:text-xl [&_h2]:font-semibold">{children}</div>
      <p className="mt-12 text-sm text-muted">
        <Link to="/privacy" className="hover:underline">Privacy policy</Link> · <Link to="/terms" className="hover:underline">Terms of use</Link>
      </p>
    </main>
  );
}

export function Privacy() {
  return (
    <Page title="Privacy policy">
      <p>Penny &amp; Pixel Studio is a private tool used by one person to plan and publish videos and posts on the Penny &amp; Pixel accounts on YouTube, Facebook, TikTok and X. It is not offered to the public.</p>
      <h2>YouTube API Services</h2>
      <p>The studio uses YouTube API Services to upload videos to the owner's own YouTube channels and to read those channels' details and statistics (views, watch time, revenue reports). By using the studio you agree to be bound by the <a className="underline" href="https://www.youtube.com/t/terms">YouTube Terms of Service</a>, and Google's handling of data is described in the <a className="underline" href="https://policies.google.com/privacy">Google Privacy Policy</a>.</p>
      <h2>What we access</h2>
      <p>When the account owner connects a platform, the studio receives permission to upload videos and publish posts to that owner's own accounts, to read basic account details (channel or page name and ID), and, for YouTube, to read the channel's own statistics so the owner can see how each video performs. We do not access other people's accounts, messages or contacts.</p>
      <h2>How it is stored</h2>
      <p>Access tokens are encrypted (AES-256-GCM) and stored in a private database. They are used only to publish the owner's content and read the owner's own statistics. Statistics read from YouTube are used only for the owner's own reports and are never shown to anyone else. Research data comes from public sources and is stored with its source link.</p>
      <h2>Sharing</h2>
      <p>We do not sell or share personal data. Content is sent only to the platform it is published on. Scripts and research summaries are processed by AI services to write and check content; no private personal data is sent to them.</p>
      <h2>Viewers and commenters</h2>
      <p>The studio does not collect personal data about viewers. Comments are read and answered by the owner directly on each platform.</p>
      <h2>Deleting data</h2>
      <p>The owner can disconnect any platform at any time in the studio settings, which deletes the stored token, or in the platform's own settings. For Google and YouTube, access can be revoked at any time on the <a className="underline" href="https://security.google.com/settings/security/permissions">Google security settings page</a>; once it is revoked, the studio can no longer read anything from YouTube. To ask for deletion of any data about you, contact the account owner through the Penny &amp; Pixel channels.</p>
    </Page>
  );
}

export function Terms() {
  return (
    <Page title="Terms of use">
      <p>Penny &amp; Pixel Studio is a private publishing tool operated by the owner of the Penny &amp; Pixel accounts. Only the owner can sign in.</p>
      <h2>Content</h2>
      <p>Videos and posts are researched with the help of AI tools and checked against their sources before publishing; the owner approves sensitive topics personally. Money content is general education, not personal financial advice.</p>
      <h2>Platform rules</h2>
      <p>The studio publishes only through each platform's official API and follows each platform's terms and community guidelines. Its use of YouTube is through YouTube API Services: by using the studio you agree to be bound by the <a className="underline" href="https://www.youtube.com/t/terms">YouTube Terms of Service</a>. Media is used under its license, and the license is recorded for every item.</p>
      <h2>No warranty</h2>
      <p>Information in our content is provided as-is for education. Always check important decisions with a qualified professional.</p>
    </Page>
  );
}
