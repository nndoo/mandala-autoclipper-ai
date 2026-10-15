import test from "node:test";
import assert from "node:assert/strict";
import { describe9RouterVideo } from "../dist/transport.js";

const base = {
  buffer: Buffer.alloc(2048, 1),
  mime: "video/mp4",
  baseUrl: "https://example.invalid/v1",
  apiKey: "test-only-key",
  model: "openclaw",
  timeoutMs: 10000
};

test("universal_v02 loads prompt and complete schema", async () => {
  const previous = process.env.MANDALA_VIDEO_ANALYSIS_MODE;
  process.env.MANDALA_VIDEO_ANALYSIS_MODE = "universal_v02";

  let requestBody;

  try {
    const expectedSource = {
      video_id: "local-sha256-test-fixture",
      duration_sec: 26.533,
      width: 1080,
      height: 1920,
      fps: 30
    };

    const result = await describe9RouterVideo({
      ...base,
      metadataProbe: async (buffer) => {
        assert.equal(buffer, base.buffer);
        return expectedSource;
      },
      fetchFn: async (_url, options) => {
        requestBody = JSON.parse(options.body);

        return new Response(JSON.stringify({
          choices: [{
            message: {
              content: '{"test":"ok"}'
            }
          }],
          model: "mock-model"
        }), {
          status: 200,
          headers: {
            "content-type": "application/json"
          }
        });
      }
    });

    const content = requestBody.messages[0].content;
    const prompt = content[0].text;

    assert.match(
      prompt,
      /Universal Video Understanding V0\.2/
    );

    assert.match(
      prompt,
      /REQUIRED JSON SCHEMA/
    );

    assert.match(
      prompt,
      /"schema_version"/
    );

    assert.match(
      prompt,
      /"content_profile"/
    );

    assert.match(
      prompt,
      /"editing_opportunities"/
    );

    assert.match(
      prompt,
      /Song vocals without spoken dialogue count as music, not speech/
    );

    assert.match(
      prompt,
      /Model inference is not external verification/
    );

    assert.match(
      prompt,
      /Do not divide a video into uniform time buckets/
    );

    assert.match(prompt, /VERIFIED SOURCE METADATA/);
    assert.ok(
      prompt.includes(JSON.stringify(expectedSource)),
      "Verified source metadata must reach Gemini prompt"
    );

    assert.equal(content[1].type, "image_url");

    assert.ok(
      content[1].image_url.url.startsWith(
        "data:video/mp4;base64,"
      )
    );

    assert.equal(result.text, '{"test":"ok"}');

  } finally {
    if (previous === undefined) {
      delete process.env.MANDALA_VIDEO_ANALYSIS_MODE;
    } else {
      process.env.MANDALA_VIDEO_ANALYSIS_MODE = previous;
    }
  }
});

test("unknown mode fails without network request", async () => {
  const previous = process.env.MANDALA_VIDEO_ANALYSIS_MODE;
  process.env.MANDALA_VIDEO_ANALYSIS_MODE = "invalid_mode";

  let called = false;

  try {
    await assert.rejects(
      describe9RouterVideo({
        ...base,
        fetchFn: async () => {
          called = true;
          throw new Error("Network must not be called");
        }
      }),
      /Unsupported Mandala video analysis mode/
    );

    assert.equal(called, false);

  } finally {
    if (previous === undefined) {
      delete process.env.MANDALA_VIDEO_ANALYSIS_MODE;
    } else {
      process.env.MANDALA_VIDEO_ANALYSIS_MODE = previous;
    }
  }
});
