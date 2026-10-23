import { expect, it } from "vitest";
import { decryptJson, encryptJson } from "../src/crypto";

const KEY = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=";
// Produced by engine/studio/oauth.py encrypt({"access_token": "from-python"})
const PY_BLOB = "YePwZAsxYsiun12b+rt8EweARF+FDIlTXX/r9/w9i2rbOTMwrjrhhpbnf6B5t+DJkcOR5vfPCNMxbLQ=";

it("decrypts tokens encrypted by the Python engine", async () => {
  expect(await decryptJson(KEY, PY_BLOB)).toEqual({ access_token: "from-python" });
});

it("prints a Worker-encrypted blob for the Python test", async () => {
  const blob = await encryptJson(KEY, { access_token: "from-worker" });
  console.log("TSBLOB=" + blob);
  expect(blob.length).toBeGreaterThan(20);
});
