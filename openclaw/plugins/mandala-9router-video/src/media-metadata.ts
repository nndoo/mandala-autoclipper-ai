import { createHash } from "node:crypto";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { mkdtemp, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

const execFileAsync = promisify(execFile);
const MAX_BYTES = 20 * 1024 * 1024;

export type VerifiedVideoSource = {
  video_id: string;
  duration_sec: number;
  width: number;
  height: number;
  fps: number;
};

type ProbeStream = {
  codec_type?: string;
  width?: number;
  height?: number;
  avg_frame_rate?: string;
};

type ProbeOutput = {
  streams?: ProbeStream[];
  format?: {
    duration?: string;
  };
};

function parseFrameRate(value: string | undefined): number {
  if (!value) {
    throw new Error("FFprobe tidak memberikan frame rate.");
  }

  const parts = value.split("/").map(Number);

  const fps = parts.length === 2
    ? parts[0] / parts[1]
    : Number(value);

  if (!Number.isFinite(fps) || fps <= 0) {
    throw new Error("Frame rate tidak valid.");
  }

  return Math.round(fps * 1000) / 1000;
}

export async function probeVideoBuffer(
  buffer: Buffer
): Promise<VerifiedVideoSource> {

  if (!Buffer.isBuffer(buffer)) {
    throw new Error("Input harus berupa Buffer.");
  }

  if (buffer.length < 1024 || buffer.length > MAX_BYTES) {
    throw new Error("Ukuran buffer video tidak valid.");
  }

  const digest = createHash("sha256")
    .update(buffer)
    .digest("hex");

  const directory = await mkdtemp(
    join(tmpdir(), "mandala-video-probe-")
  );

  const temporaryFile = join(directory, "source.mp4");

  try {
    await writeFile(temporaryFile, buffer, {
      mode: 0o600
    });

    const { stdout } = await execFileAsync(
      "ffprobe",
      [
        "-v", "error",
        "-show_entries",
        "format=duration:stream=codec_type,width,height,avg_frame_rate",
        "-of", "json",
        temporaryFile
      ],
      {
        timeout: 30000,
        maxBuffer: 2 * 1024 * 1024
      }
    );

    const probe = JSON.parse(stdout) as ProbeOutput;

    const stream = probe.streams?.find(
      item => item.codec_type === "video"
    );

    if (!stream) {
      throw new Error("Video stream tidak ditemukan.");
    }

    const duration = Number(probe.format?.duration);

    if (!Number.isFinite(duration) || duration <= 0) {
      throw new Error("Durasi video tidak valid.");
    }

    if (
      !Number.isInteger(stream.width) ||
      !Number.isInteger(stream.height) ||
      (stream.width ?? 0) <= 0 ||
      (stream.height ?? 0) <= 0
    ) {
      throw new Error("Resolusi video tidak valid.");
    }

    return {
      video_id: `local-sha256-${digest.slice(0, 32)}`,
      duration_sec: Math.round(duration * 1000) / 1000,
      width: stream.width as number,
      height: stream.height as number,
      fps: parseFrameRate(stream.avg_frame_rate)
    };

  } finally {
    await rm(directory, {
      recursive: true,
      force: true
    });
  }
}
