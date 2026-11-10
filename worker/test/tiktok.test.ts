import { describe, expect, it } from "vitest";
import { choiceProblem, type Creator } from "../src/tiktok";

const creator: Creator = { privacy_level_options: ["PUBLIC_TO_EVERYONE", "SELF_ONLY"], comment_disabled: false,
  duet_disabled: true, stitch_disabled: false, max_video_post_duration_sec: 600, can_post: true };
const ok = { privacy_level: "PUBLIC_TO_EVERYONE", consent: true };

describe("TikTok posting choices (Content Sharing Guidelines)", () => {
  it("needs an audience chosen by the owner, from the account's own options", () => {
    expect(choiceProblem({ consent: true }, creator)).toMatch(/who can watch/);
    expect(choiceProblem({ privacy_level: "FOLLOWER_OF_CREATOR", consent: true }, creator)).toMatch(/isn't available/);
    expect(choiceProblem(ok, creator)).toBeNull();
  });
  it("needs the music consent", () => {
    expect(choiceProblem({ privacy_level: "SELF_ONLY" }, creator)).toMatch(/Music Usage/);
  });
  it("keeps switches the creator turned off, off", () => {
    expect(choiceProblem({ ...ok, allow_duet: true }, creator)).toMatch(/turned off/);
    expect(choiceProblem({ ...ok, allow_comment: true, allow_stitch: true }, creator)).toBeNull();
  });
  it("commercial content must say what it is, and branded content can't be private", () => {
    expect(choiceProblem({ ...ok, disclose: true }, creator)).toMatch(/Your brand/);
    expect(choiceProblem({ privacy_level: "SELF_ONLY", consent: true, disclose: true, branded_content: true }, creator)).toMatch(/can't be private/);
    expect(choiceProblem({ ...ok, disclose: true, your_brand: true }, creator)).toBeNull();
  });
  it("respects the account's longest video and posting limit", () => {
    expect(choiceProblem(ok, creator, 700)).toMatch(/at most 600/);
    expect(choiceProblem(ok, { ...creator, can_post: false })).toMatch(/can't post/);
  });
});
