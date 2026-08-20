import { describe, expect, it } from "vitest";
import { admitFiles, formatBytes, isImage } from "../Assistant";

const file = (name: string, size: number) => ({ name, size });
const MB = 1024 * 1024;

describe("assistant attachments", () => {
  it("takes what fits and says why the rest didn't", () => {
    expect(admitFiles([file("a.png", 10), file("b.png", 20)], 0)).toEqual({
      ok: [file("a.png", 10), file("b.png", 20)],
      error: "",
    });

    // over the size cap: nothing silently disappears, the name is in the message
    const big = admitFiles([file("huge.log", 11 * MB)], 0);
    expect(big.ok).toEqual([]);
    expect(big.error).toContain("huge.log");

    // over the count cap, counting what is ALREADY attached — not just this batch
    const many = admitFiles([file("a", 1), file("b", 1), file("c", 1)], 4);
    expect(many.ok).toEqual([file("a", 1)]);
    expect(many.error).toContain("per message");
  });

  it("keeps the good files from a batch that also has a bad one", () => {
    const { ok } = admitFiles([file("fine.txt", 5), file("huge.bin", 99 * MB)], 0);
    expect(ok).toEqual([file("fine.txt", 5)]);
  });

  it("renders an image inline and everything else as a chip", () => {
    expect(isImage({ mime: "image/png" })).toBe(true);
    expect(isImage({ mime: "application/pdf" })).toBe(false);
    expect(isImage({})).toBe(false);
  });

  it("formats sizes the way a person reads them", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2 KB");
    expect(formatBytes(3 * MB)).toBe("3.0 MB");
  });
});
