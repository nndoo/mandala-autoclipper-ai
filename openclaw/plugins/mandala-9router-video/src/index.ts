import { describe9RouterVideo } from "./transport.js";
import { PROVIDER_ID } from "./provider-id.generated.js";

type VideoDescriptionRequest = {
  buffer: Buffer;
  fileName: string;
  mime?: string;
  apiKey: string;
  baseUrl?: string;
  model?: string;
  prompt?: string;
  timeoutMs: number;
  signal?: AbortSignal;
  fetchFn?: typeof fetch;
};
type Api = {
  registerMediaUnderstandingProvider: (provider: {
    id: string;
    capabilities: Array<"video">;
    defaultModels: { video: string };
    describeVideo: (request: VideoDescriptionRequest) => Promise<{ text: string; model?: string }>;
  }) => void;
};

export default {
  id: "mandala-9router-video",
  name: "Mandala 9Router Video Understanding",
  register(api: Api) {
    api.registerMediaUnderstandingProvider({
      // Reuse the existing OpenClaw 9Router provider ID, auth profile and baseUrl.
      id: PROVIDER_ID,
      capabilities: ["video"],
      defaultModels: { video: "openclaw" },
      async describeVideo(request: VideoDescriptionRequest) {
        return describe9RouterVideo(request);
      }
    });
  }
};
