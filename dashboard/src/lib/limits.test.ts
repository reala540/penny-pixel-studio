import { describe, expect, it } from "vitest";
import { caption, limitProblems, parseHashtags, parseTags } from "./limits";

const p = (over = {}) => ({ title: "", body: "", tags: [] as string[], hashtags: [] as string[], ...over });

describe("platform limits", () => {
  it("X: 280 characters and no links", () => {
    expect(limitProblems("x", "text_post", p({ body: "a".repeat(281) }))).toEqual(["Text is 281 characters (limit 280)"]);
    expect(limitProblems("x", "text_post", p({ body: "see example.com" }))[0]).toMatch(/link/);
    expect(limitProblems("x", "text_post", p({ body: "fine" }))).toEqual([]);
  });
  it("YouTube: title, tags in total and hashtag count", () => {
    expect(limitProblems("youtube", "long_video", p({ title: "t".repeat(101), body: "d" }))[0]).toMatch(/Title is 101/);
    expect(limitProblems("youtube", "long_video", p({ body: "d", tags: Array(60).fill("tagtag") }))).toEqual([]);  // 419 characters fits
    expect(limitProblems("youtube", "short_video", p({ body: "d", tags: Array(80).fill("tagtag") }))[0]).toMatch(/Tags add up to 559 characters/);
  });
  it("TikTok and Reels count the hashtags in the caption", () => {
    expect(caption("Hello", ["ai", "#money"])).toBe("Hello #ai #money");
    expect(limitProblems("tiktok", "short_video", p({ body: "x", hashtags: ["a", "b", "c", "d", "e", "f"] }))).toEqual(["6 hashtags (at most 5)"]);
    expect(limitProblems("facebook", "reel", p({ body: "x".repeat(2195), hashtags: ["ai", "tips"] }))[0]).toMatch(/Caption with hashtags is 2205/);
  });
  it("reads tags and hashtags as typed", () => {
    expect(parseTags("budget, money tips ,, ai")).toEqual(["budget", "money tips", "ai"]);
    expect(parseHashtags("#ai #money,tips")).toEqual(["ai", "money", "tips"]);
  });
});
