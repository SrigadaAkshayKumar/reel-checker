import { describe, expect, it } from "vitest";

import { ApiError, apiAsset, toApiError } from "./api";
import { checkFile, formatDate, reverseSearchLinks, similarityText, whatsappLink } from "./present";

describe("similarityText", () => {
  it("shows a percentage only for real matches", () => {
    expect(similarityText(0.97)).toBe("97% frame match");
    expect(similarityText(0.8)).toBe("80% frame match");
    expect(similarityText(0.72)).toBe("frames do not match");
    expect(similarityText(undefined)).toBeNull();
  });
});

describe("reverseSearchLinks", () => {
  it("deep-links public frames into Lens, Yandex and TinEye", () => {
    const links = reverseSearchLinks("https://api.reelcheck.example/api/reports/abc/files/frames/k.jpg")!;
    expect(links.map((l) => l.name)).toEqual(["Google Lens", "Yandex", "TinEye"]);
    expect(links[0].url).toBe(
      "https://lens.google.com/uploadbyurl?url=https%3A%2F%2Fapi.reelcheck.example%2Fapi%2Freports%2Fabc%2Ffiles%2Fframes%2Fk.jpg",
    );
  });
  it("returns null for addresses the search engines cannot reach", () => {
    expect(reverseSearchLinks("http://localhost:8000/x.jpg")).toBeNull();
    expect(reverseSearchLinks("http://192.168.1.5/x.jpg")).toBeNull();
    expect(reverseSearchLinks("not a url")).toBeNull();
  });
});

describe("checkFile", () => {
  it("accepts reels and rejects other files", () => {
    expect(checkFile({ name: "reel.MP4", size: 1000, type: "video/mp4" })).toBeNull();
    expect(checkFile({ name: "screen.mov", size: 1000, type: "" })).toBeNull();
    expect(checkFile({ name: "notes.txt", size: 10, type: "text/plain" })).toMatch(/video file/);
    expect(checkFile({ name: "clip.avi", size: 10, type: "video/x-msvideo" })).toMatch(/isn't supported/);
    expect(checkFile({ name: "big.mp4", size: 60 * 1024 * 1024, type: "video/mp4" })).toMatch(/50 MB/);
    expect(checkFile({ name: "empty.mp4", size: 0, type: "video/mp4" })).toMatch(/empty/);
  });
});

describe("toApiError", () => {
  it("reads the backend's {code, message} detail", () => {
    const e = toApiError(429, { detail: { code: "rate_limited", message: "Daily limit reached." } });
    expect(e).toBeInstanceOf(ApiError);
    expect([e.status, e.code, e.message]).toEqual([429, "rate_limited", "Daily limit reached."]);
  });
  it("handles FastAPI's plain detail and network failures", () => {
    expect(toApiError(404, { detail: "job not found" }).message).toBe("job not found");
    expect(toApiError(0, null).code).toBe("network");
    expect(toApiError(500, null).message).toMatch(/Something went wrong/);
  });
});

describe("misc", () => {
  it("formats ISO dates for Indian readers without timezone drift", () => {
    expect(formatDate("2015-03-02")).toBe("2 Mar 2015");
    expect(formatDate("")).toBe("");
  });
  it("builds absolute asset URLs and WhatsApp links", () => {
    expect(apiAsset("https://cdn.example/x.jpg")).toBe("https://cdn.example/x.jpg");
    expect(apiAsset("/api/x.jpg")).toMatch(/^http:\/\/localhost:8000\/api\/x\.jpg$/);
    expect(whatsappLink("Reel check: Debunked https://x/r/1")).toBe(
      "https://wa.me/?text=Reel%20check%3A%20Debunked%20https%3A%2F%2Fx%2Fr%2F1",
    );
  });
});
