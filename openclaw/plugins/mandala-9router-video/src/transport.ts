/**
 * 9Router v0.5.95 compatibility path:
 * content.type = image_url with data:video/mp4;base64,...
 * Its Gemini translator turns this into inlineData and preserves MIME.
 * NOT a standardized OpenAI video contract. Regression-test on router upgrade.
 */
import { probeVideoBuffer } from "./media-metadata.js";
import { qualityReviewPrompt } from "./qa-prompt.js";

export type VideoTransportInput = {
  /** Test injection; production uses FFprobe. */
  metadataProbe?: typeof probeVideoBuffer;
  buffer: Buffer;
  mime?: string;
  baseUrl?: string;
  apiKey?: string;
  model?: string;
  prompt?: string;
  timeoutMs?: number;
  signal?: AbortSignal;
  fetchFn?: typeof fetch;
};

const MAX_INPUT_BYTES = 20 * 1024 * 1024;
const MAX_RESPONSE_BYTES = 2 * 1024 * 1024;
const DEFAULT_TIMEOUT_MS = 120_000;
const DEFAULT_PROMPT = `
You are the Video Understanding Agent for Mandala Auto.

Analyze the actual video AND its audio.
Return ONLY a valid JSON object, without Markdown fences.

Required JSON structure:
{
  "summary": "string",
  "video_structure": "single_take|multi_cut|uncertain",
  "timeline": [
    {
      "start_sec": 0,
      "end_sec": 5,
      "visual": "string",
      "audio_summary": "string",
      "confidence": "high|medium|low"
    }
  ],
  "speech": [
    {
      "speaker": "string",
      "start_sec": null,
      "end_sec": null,
      "text": "string",
      "confidence": "high|medium|low"
    }
  ],
  "hooks": [
    {
      "start_sec": 0,
      "end_sec": 5,
      "reason": "string",
      "hook_type": "dialogue|visual|curiosity",
      "score": 8
    }
  ],
  "quality_issues": [],
  "editing_notes": [],
  "timing_precision": "approximate",
  "requires_timing_alignment": true
}

Rules:
- Analyze the entire video, not just the first frame.
- Identify useful moments across beginning, middle and end.
- Capture dialogue only when actually audible.
- Never invent vehicle specifications or unseen events.
- Timestamps are estimates, not verified frame boundaries.
- Use null for unknown speech timestamps.
- Avoid cutting sentences in the middle.
- Do not recommend publishing.
`;


// Generated from the project's canonical prompt and schema.
// Regenerate these constants if either source file changes.
const UNIVERSAL_PROMPT_V02 = "# Mandala Auto \u2014 Universal Video Understanding V0.2\n\n## ROLE\n\nYou are a Universal Multimodal Video Analyst for\nMandala Auto Autonomous AI Autoclipper.\n\nUnderstand the actual audiovisual content of each source video.\n\nYou are not a video editor.\nYou produce structured evidence that an autonomous\nCreative Director can use to make editing decisions.\n\n## CORE PRINCIPLE\n\nNever assume that a video is cinematic, dialogue-based,\npromotional, humorous, educational, or any other fixed format.\n\nInfer its characteristics from the actual source.\n\nDifferent segments may have different characteristics.\n\nThe same video may contain:\n- Spoken dialogue or interviews\n- Voice-over or narration\n- Music-only montages\n- Product showcases\n- Vehicle demonstrations\n- Cinematic footage\n- Text-based explanations\n- Humorous moments\n- Before-and-after sequences\n- Promotional content\n- Mixed audiovisual formats\n- Other previously unseen content patterns\n\nDo not force the video into a predefined category.\n\n## SOURCE METADATA\n\nUse verified source metadata supplied by the calling system.\n\nDo not invent video IDs, duration, resolution, or frame rate.\n\nIf required verified metadata is unavailable, report\nthat limitation to the caller rather than fabricate it.\n\n## VIDEO ANALYSIS\n\nExamine the complete supplied video when possible.\n\nIdentify:\n- Visible people, vehicles, objects and actions\n- Camera movement and shot composition\n- Important visual changes\n- Scene and shot transitions\n- Product details actually visible\n- Interesting or unusual visual moments\n- On-screen text\n- Potential visual hooks\n- Low-quality or unusable footage\n\nDistinguish an observed visual transition from a\nprecisely measured frame boundary.\n\nDo not invent scenes, camera angles or vehicle details.\n\n## AUDIO ANALYSIS\n\nDetermine what audio components are actually present.\n\nPossible layers:\n- Speech\n- Music\n- Ambience\n- Sound effects\n- Silence\n- Unknown\n\nDo not assume dialogue exists.\n\nIf speech is absent, do not invent dialogue,\nspeakers or transcripts.\n\nIf music is present, describe its general characteristics,\nenergy and changes when perceptible.\n\nDo not claim exact beat positions unless supported by\na dedicated signal analysis.\n\nIf music or speech cannot be determined reliably,\nuse uncertain and explain the limitation.\n\n## AUDIO AND CLAIM GUARDRAILS\n\nSong vocals without spoken dialogue count as music, not speech.\n\nIf a video contains only music with singing:\n- content_profile.speech_presence must be \"absent\"\n- content_profile.music_presence must be \"present\"\n- segment.audio_layers should contain \"music\", not \"speech\"\n- audio_description may describe singing or vocal performance\n\nSpoken dialogue, interviews, narration, and spoken announcements\ncount as speech.\n\nIf genuine spoken dialogue and music coexist, report both.\n\nIf uncertain whether a voice is speaking or singing,\nuse \"uncertain\" and describe the uncertainty.\n\nDo not invent transcripts from song vocals.\n\nDo not contradict structured audio classifications\nin analysis_meta.limitations.\n\nModel inference is not external verification.\n\nFor claims based solely on AI audiovisual interpretation,\nset verification_status to \"unverified\".\n\nReserve \"verified\" for evidence independently verified\nby the calling system or a separate review process.\n\nDo not invent precise license plates, vehicle models,\nmodel years, specifications, or other uncertain details.\n\nIf information is partly visible or ambiguous,\ndescribe the observation and its uncertainty.\n\nDo not divide a video into uniform time buckets.\nSegment boundaries must reflect observed content changes.\nTimestamps remain approximate until separately verified.\n\n## TEMPORAL ANALYSIS\n\nDivide the video into meaningful segments based on\nactual content changes, not fixed-length intervals.\n\nDo not force a fixed number of segments.\n\nFor each relevant segment, describe:\n- What is visibly happening\n- What is audible\n- The approximate time range\n- Confidence in the observation\n\nDetect useful events such as:\n- Scene changes\n- Camera movements\n- Dialogue moments\n- Visual reveals\n- Vehicle detail shots\n- Important gestures\n- Music changes\n- Text appearances\n- Demonstrations\n- Humorous events\n- Other content-specific moments\n\nEvent types are open-ended.\n\n## EDITING OPPORTUNITIES\n\nIdentify moments that may be useful to a Creative Director.\n\nExamples include:\n- Strong visual openings\n- Clear dialogue hooks\n- Product reveals\n- Natural pauses\n- High-energy movement\n- Emotional moments\n- Interesting transitions\n- Effective endings\n\nDo not require every video to contain every opportunity.\n\nDo not choose final cuts or prescribe a fixed editing template.\n\nA cinematic video without speech can have strong editing\nopportunities based entirely on visual events.\n\nA dialogue-heavy video may require speech-safe boundaries.\n\nA mixed video can require both approaches.\n\n## FACTUAL ACCURACY\n\nSeparate:\n- Facts directly observable in the video\n- Claims spoken by people\n- Claims shown in on-screen text\n- External information\n- Model inference\n\nDo not treat spoken marketing claims as independently verified.\n\nNever invent:\n- Vehicle prices\n- Mileage\n- Manufacturing years\n- Vehicle conditions\n- Stock quantities\n- Ownership history\n- Technical specifications\n- Customer testimonials\n\nUse uncertainty when evidence is insufficient.\n\n## TIMESTAMP PRECISION\n\nModel-generated timestamps are approximate.\n\nDo not claim frame-accurate timing without frame verification.\n\nDo not claim beat-accurate timing without signal analysis.\n\nDo not claim word-accurate timing without appropriate\nspeech alignment.\n\nThe downstream validator is responsible for checking\ntechnical timing constraints.\n\n## OUTPUT CONTRACT\n\nReturn ONLY a JSON object conforming to:\n\nuniversal-video-analysis.v0.2.schema.json\n\nSchema version: 0.2.0\n\nRequired root fields:\n- schema_version\n- analysis_status\n- source\n- analysis_meta\n- content_profile\n- segments\n- events\n- editing_opportunities\n- claims\n- quality_issues\n\nSet:\nschema_version = \"0.2.0\"\n\nSet:\nanalysis_status = \"DRAFT_UNVERIFIED\"\n\nUse only allowed values and field types from the schema.\n\nDo not add unsupported root fields.\n\nUse empty arrays when no evidence exists.\n\nDo not invent events merely to populate arrays.\n\nFor audio presence:\n- present\n- absent\n- uncertain\n\nFor confidence:\n- high\n- medium\n- low\n\nFor timing basis, use only the schema's allowed values.\n\nUse \"model_estimate\" for model-estimated timestamps.\n\nNever label model estimates as manually verified,\nframe verified or signal verified.\n\nScores between 0 and 10 represent estimated editorial\nopportunity, not measured audience retention.\n\n## RESPONSIBILITY BOUNDARIES\n\nDo not:\n- Render video\n- Select final publishing decisions\n- Publish content\n- Modify original media\n- Fabricate unavailable evidence\n- Declare a video production-ready\n\nYour output is unverified audiovisual analysis.\n\nThe Creative Director and downstream validators\nmake subsequent decisions.\n";

const UNIVERSAL_SCHEMA_V02 = "{\n  \"$schema\": \"https://json-schema.org/draft/2020-12/schema\",\n  \"title\": \"Mandala Universal Video Analysis V0.2\",\n  \"description\": \"Content-aware audiovisual evidence for adaptive editing.\",\n  \"type\": \"object\",\n  \"additionalProperties\": false,\n  \"required\": [\n    \"schema_version\",\n    \"analysis_status\",\n    \"source\",\n    \"analysis_meta\",\n    \"content_profile\",\n    \"segments\",\n    \"events\",\n    \"editing_opportunities\",\n    \"claims\",\n    \"quality_issues\"\n  ],\n  \"properties\": {\n    \"schema_version\": {\n      \"const\": \"0.2.0\"\n    },\n    \"analysis_status\": {\n      \"enum\": [\"DRAFT_UNVERIFIED\", \"NEEDS_REVIEW\"]\n    },\n    \"source\": {\n      \"type\": \"object\",\n      \"additionalProperties\": false,\n      \"required\": [\"video_id\", \"duration_sec\"],\n      \"properties\": {\n        \"video_id\": {\"type\": \"string\", \"minLength\": 1},\n        \"duration_sec\": {\"type\": \"number\", \"exclusiveMinimum\": 0},\n        \"width\": {\"type\": [\"integer\", \"null\"], \"minimum\": 1},\n        \"height\": {\"type\": [\"integer\", \"null\"], \"minimum\": 1},\n        \"fps\": {\"type\": [\"number\", \"null\"], \"exclusiveMinimum\": 0}\n      }\n    },\n    \"analysis_meta\": {\n      \"type\": \"object\",\n      \"additionalProperties\": false,\n      \"required\": [\n        \"video_examined\",\n        \"audio_examined\",\n        \"asr_used\",\n        \"timing_precision\",\n        \"limitations\"\n      ],\n      \"properties\": {\n        \"video_examined\": {\"type\": \"boolean\"},\n        \"audio_examined\": {\"type\": \"boolean\"},\n        \"asr_used\": {\"type\": \"boolean\"},\n        \"timing_precision\": {\n          \"enum\": [\n            \"approximate\",\n            \"signal_estimated\",\n            \"frame_verified\"\n          ]\n        },\n        \"limitations\": {\n          \"type\": \"array\",\n          \"items\": {\"type\": \"string\"}\n        }\n      }\n    },\n    \"content_profile\": {\n      \"type\": \"object\",\n      \"additionalProperties\": false,\n      \"required\": [\n        \"summary\",\n        \"content_tags\",\n        \"speech_presence\",\n        \"music_presence\",\n        \"editorial_goal_suggestions\"\n      ],\n      \"properties\": {\n        \"summary\": {\"type\": \"string\"},\n        \"content_tags\": {\n          \"type\": \"array\",\n          \"items\": {\"type\": \"string\"}\n        },\n        \"speech_presence\": {\"$ref\": \"#/$defs/presence\"},\n        \"music_presence\": {\"$ref\": \"#/$defs/presence\"},\n        \"editorial_goal_suggestions\": {\n          \"type\": \"array\",\n          \"items\": {\"type\": \"string\"}\n        }\n      }\n    },\n    \"segments\": {\n      \"type\": \"array\",\n      \"items\": {\n        \"type\": \"object\",\n        \"additionalProperties\": false,\n        \"required\": [\n          \"segment_id\",\n          \"start_sec\",\n          \"end_sec\",\n          \"visual_description\",\n          \"audio_description\",\n          \"audio_layers\",\n          \"confidence\"\n        ],\n        \"properties\": {\n          \"segment_id\": {\"type\": \"string\"},\n          \"start_sec\": {\"type\": \"number\", \"minimum\": 0},\n          \"end_sec\": {\"type\": \"number\", \"minimum\": 0},\n          \"visual_description\": {\"type\": \"string\"},\n          \"audio_description\": {\"type\": \"string\"},\n          \"audio_layers\": {\n            \"type\": \"array\",\n            \"uniqueItems\": true,\n            \"items\": {\n              \"enum\": [\n                \"speech\",\n                \"music\",\n                \"ambience\",\n                \"sound_effect\",\n                \"silence\",\n                \"unknown\"\n              ]\n            }\n          },\n          \"confidence\": {\"$ref\": \"#/$defs/confidence\"}\n        }\n      }\n    },\n    \"events\": {\n      \"type\": \"array\",\n      \"items\": {\n        \"type\": \"object\",\n        \"additionalProperties\": false,\n        \"required\": [\n          \"event_type\",\n          \"modality\",\n          \"start_sec\",\n          \"end_sec\",\n          \"description\",\n          \"confidence\",\n          \"timing_basis\"\n        ],\n        \"properties\": {\n          \"event_type\": {\"type\": \"string\", \"minLength\": 1},\n          \"modality\": {\n            \"enum\": [\n              \"visual\",\n              \"audio\",\n              \"audiovisual\",\n              \"on_screen_text\"\n            ]\n          },\n          \"start_sec\": {\"type\": \"number\", \"minimum\": 0},\n          \"end_sec\": {\"type\": \"number\", \"minimum\": 0},\n          \"description\": {\"type\": \"string\"},\n          \"transcript_text\": {\"type\": [\"string\", \"null\"]},\n          \"confidence\": {\"$ref\": \"#/$defs/confidence\"},\n          \"timing_basis\": {\"$ref\": \"#/$defs/timing_basis\"}\n        }\n      }\n    },\n    \"editing_opportunities\": {\n      \"type\": \"array\",\n      \"items\": {\n        \"type\": \"object\",\n        \"additionalProperties\": false,\n        \"required\": [\n          \"opportunity_type\",\n          \"start_sec\",\n          \"end_sec\",\n          \"reason\",\n          \"score\",\n          \"confidence\",\n          \"timing_basis\"\n        ],\n        \"properties\": {\n          \"opportunity_type\": {\n            \"type\": \"string\",\n            \"minLength\": 1\n          },\n          \"start_sec\": {\"type\": \"number\", \"minimum\": 0},\n          \"end_sec\": {\"type\": \"number\", \"minimum\": 0},\n          \"reason\": {\"type\": \"string\"},\n          \"score\": {\n            \"type\": \"number\",\n            \"minimum\": 0,\n            \"maximum\": 10\n          },\n          \"confidence\": {\"$ref\": \"#/$defs/confidence\"},\n          \"timing_basis\": {\"$ref\": \"#/$defs/timing_basis\"}\n        }\n      }\n    },\n    \"claims\": {\n      \"type\": \"array\",\n      \"items\": {\n        \"type\": \"object\",\n        \"additionalProperties\": false,\n        \"required\": [\n          \"text\",\n          \"origin\",\n          \"verification_status\"\n        ],\n        \"properties\": {\n          \"text\": {\"type\": \"string\"},\n          \"origin\": {\n            \"enum\": [\n              \"spoken\",\n              \"on_screen_text\",\n              \"visually_observed\",\n              \"external\",\n              \"model_inference\"\n            ]\n          },\n          \"verification_status\": {\n            \"enum\": [\n              \"unverified\",\n              \"verified\",\n              \"contradicted\"\n            ]\n          }\n        }\n      }\n    },\n    \"quality_issues\": {\n      \"type\": \"array\",\n      \"items\": {\n        \"type\": \"object\",\n        \"additionalProperties\": false,\n        \"required\": [\"issue_type\", \"description\", \"severity\"],\n        \"properties\": {\n          \"issue_type\": {\"type\": \"string\"},\n          \"description\": {\"type\": \"string\"},\n          \"severity\": {\"enum\": [\"low\", \"medium\", \"high\"]},\n          \"start_sec\": {\"type\": [\"number\", \"null\"], \"minimum\": 0},\n          \"end_sec\": {\"type\": [\"number\", \"null\"], \"minimum\": 0}\n        }\n      }\n    }\n  },\n  \"$defs\": {\n    \"presence\": {\n      \"enum\": [\"present\", \"absent\", \"uncertain\"]\n    },\n    \"confidence\": {\n      \"enum\": [\"high\", \"medium\", \"low\"]\n    },\n    \"timing_basis\": {\n      \"enum\": [\n        \"model_estimate\",\n        \"asr_estimate\",\n        \"signal_analysis\",\n        \"frame_verified\",\n        \"manual_verified\",\n        \"unknown\"\n      ]\n    }\n  }\n}\n";

function selectAnalysisPrompt(mode: string): string {

  if (mode === "legacy") {
    return DEFAULT_PROMPT;
  }

  if (mode === "universal_v02") {
    return [
      UNIVERSAL_PROMPT_V02,
      "",
      "## REQUIRED JSON SCHEMA",
      "Return a JSON object matching this complete schema:",
      UNIVERSAL_SCHEMA_V02
    ].join("\n");
  }

  throw new Error(`Unsupported Mandala video analysis mode: ${mode}`);
}

function normalizeEndpoint(baseUrl: string): string {
  const url = new URL(baseUrl);
  const local = ["localhost", "127.0.0.1", "::1", "[::1]"].includes(url.hostname);
  if (url.protocol !== "https:" && !(local && url.protocol === "http:")) {
    throw new Error("9Router baseUrl harus HTTPS (kecuali localhost)");
  }
  if (url.username || url.password || url.search || url.hash) {
    throw new Error("9Router baseUrl tidak boleh mengandung kredensial, query, atau fragment");
  }
  let path = url.pathname.replace(/\/+$/, "");
  if (path.endsWith("/chat/completions")) {
    return url.origin + path;
  }
  return url.origin + path + "/chat/completions";
}

async function readLimited(response: Response): Promise<string> {
  const reader = response.body?.getReader();
  if (!reader) return "";
  let total = 0;
  const chunks: Uint8Array[] = [];
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > MAX_RESPONSE_BYTES) throw new Error("Respons 9Router melebihi 2 MB");
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  return new TextDecoder().decode(Buffer.concat(chunks));
}

function collectContent(payload: unknown): { text: string; model?: string } {
  if (!payload || typeof payload !== "object") {
    throw new Error("Respons 9Router tidak berisi objek JSON");
  }
  const root = payload as { choices?: Array<{ message?: { content?: unknown } }>; model?: unknown };
  const raw = root.choices?.[0]?.message?.content;
  const text = typeof raw === "string"
    ? raw
    : Array.isArray(raw)
      ? raw.filter((p): p is { text: string } => !!p && typeof p === "object" && typeof p.text === "string").map(p => p.text).join("\n")
      : "";
  if (!text.trim()) throw new Error("Respons 9Router kosong; video mungkin tidak diteruskan");
  return { text: text.trim(), model: typeof root.model === "string" ? root.model : undefined };
}

export async function describe9RouterVideo(input: VideoTransportInput): Promise<{ text: string; model?: string }> {
  if (!Buffer.isBuffer(input.buffer) || input.buffer.length < 1024) {
    throw new Error("MP4 tidak valid atau terlalu kecil");
  }
  if (input.buffer.length > MAX_INPUT_BYTES) {
    throw new Error("MP4 melebihi batas POC 20 MiB");
  }
  const mime = input.mime?.toLowerCase() || "video/mp4";
  if (mime !== "video/mp4") throw new Error(`MIME video tidak didukung: ${mime}`);
  if (!input.baseUrl) throw new Error("OpenClaw tidak memberikan baseUrl 9Router");
  if (!input.apiKey) throw new Error("OpenClaw tidak memberikan API key provider 9Router");
  const endpoint = normalizeEndpoint(input.baseUrl);
  const model = input.model?.trim() || "openclaw";
  const controller = new AbortController();
  const ms = Math.min(Math.max(1_000, input.timeoutMs ?? DEFAULT_TIMEOUT_MS), 240_000);
  const timer = setTimeout(() => controller.abort(), ms);
  const abortOnInput = () => controller.abort();
  if (input.signal?.aborted) controller.abort();
  input.signal?.addEventListener("abort", abortOnInput, { once: true });
  try {
    const mode =
      process.env.MANDALA_VIDEO_ANALYSIS_MODE?.trim() || "legacy";

    // Legacy and Universal retain their exact prompts; only QA uses a bound request.
    const basePrompt = mode === "quality_qa_v01"
      ? await qualityReviewPrompt(input.buffer)
      : selectAnalysisPrompt(mode);

    const verifiedSource = mode === "universal_v02"
      ? await (input.metadataProbe ?? probeVideoBuffer)(input.buffer)
      : null;

    const prompt = verifiedSource === null
      ? basePrompt
      : [
          basePrompt,
          "",
          "## VERIFIED SOURCE METADATA",
          "The following source metadata was derived from the attached MP4 using FFprobe and SHA-256.",
          "Set the output source object to EXACTLY these values:",
          JSON.stringify(verifiedSource),
          "Do not invent or modify the source metadata.",
          "Visual and audio event timestamps are still estimates until independently verified."
        ].join("\n");

    const requestBody = {
      model,
      stream: false,
      messages: [{ role: "user", content: [
        { type: "text", text: prompt },
        { type: "image_url", image_url: { url: `data:video/mp4;base64,${input.buffer.toString("base64")}` } }
      ] }]
    };
    const response = await (input.fetchFn ?? fetch)(endpoint, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${input.apiKey}`,
        "Content-Type": "application/json",
        "Accept": "application/json"
      },
      body: JSON.stringify(requestBody),
      signal: controller.signal
    });
    const responseText = await readLimited(response);
    if (!response.ok) {
      // No upstream response bodies or credential values in logs.
      throw new Error(`9Router video request failed: HTTP ${response.status}`);
    }
    let responseData: unknown;
    try { responseData = JSON.parse(responseText); }
    catch { throw new Error("9Router memberikan respons non-JSON"); }
    return collectContent(responseData);
  } finally {
    clearTimeout(timer);
    input.signal?.removeEventListener("abort", abortOnInput);
  }
}
