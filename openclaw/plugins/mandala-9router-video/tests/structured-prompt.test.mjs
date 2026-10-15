import assert from "node:assert/strict";
import test from "node:test";
import { describe9RouterVideo } from "../dist/transport.js";

test("structured prompt overrides generic description", async () => {
  let requestBody;

  await describe9RouterVideo({
    buffer: Buffer.alloc(2048, 1),
    mime: "video/mp4",
    baseUrl: "https://router.example/v1",
    apiKey: "test-secret",
    model: "openclaw",
    prompt: "Describe this video in one paragraph.",
    fetchFn: async (_url, options) => {
      requestBody = JSON.parse(options.body);

      return new Response(
        JSON.stringify({
          model: "gemini-test",
          choices: [{
            message: { content: '{"summary":"test"}' }
          }]
        }),
        { status: 200 }
      );
    }
  });

  const prompt = requestBody.messages[0].content[0].text;

  assert.match(prompt, /Return ONLY a valid JSON object/);
  assert.doesNotMatch(
    prompt,
    /Describe this video in one paragraph/
  );
});
