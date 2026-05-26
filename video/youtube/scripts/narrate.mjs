import { readFile, writeFile, mkdir, stat } from "node:fs/promises";
import { join, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import dotenv from "dotenv";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, "..");

// Load .env from skorpio-video/ first, then fall back to the project root
// (pre-Skorpio/Skorpio/.env) where the rest of the project's secrets live.
dotenv.config({ path: join(ROOT, ".env") });
dotenv.config({ path: resolve(ROOT, "..", ".env") });

const apiKey = process.env.ELEVENLABS_API_KEY;
if (!apiKey) {
  console.error("ELEVENLABS_API_KEY missing. Add it to skorpio-video/.env");
  process.exit(1);
}

const force = process.argv.includes("--force");

async function loadVoices() {
  const r = await fetch("https://api.elevenlabs.io/v2/voices?page_size=100", {
    headers: { "xi-api-key": apiKey },
  });
  if (!r.ok) {
    throw new Error(`failed to list voices: ${r.status} ${await r.text()}`);
  }
  const data = await r.json();
  const map = new Map();
  for (const v of data.voices ?? []) {
    // The v2 endpoint sometimes returns names like "Hale - smooth, confident
    // and persuasive" — strip the description so lookups by bare name work.
    const shortName = v.name.split(" - ")[0].trim().toLowerCase();
    map.set(shortName, v.voice_id);
  }
  return map;
}

const voiceMap = await loadVoices();

function resolveVoiceId(name) {
  const id = voiceMap.get(name.toLowerCase());
  if (id) return id;
  // assume the user passed a raw voice_id
  if (/^[A-Za-z0-9]{15,}$/.test(name)) return name;
  const available = [...voiceMap.keys()].sort().join(", ");
  throw new Error(
    `voice '${name}' not found in your library. Available: ${available}`,
  );
}

const script = JSON.parse(
  await readFile(join(ROOT, "narration.json"), "utf8"),
);

const outDir = join(ROOT, "public", "audio");
await mkdir(outDir, { recursive: true });

const model = script.model ?? "eleven_multilingual_v2";

async function exists(path) {
  try {
    await stat(path);
    return true;
  } catch {
    return false;
  }
}

async function synth(line) {
  const voiceName = line.voice ?? script.defaultVoice ?? "rachel";
  const voiceId = resolveVoiceId(voiceName);
  const outPath = join(outDir, `${line.id}.mp3`);

  if (!force && (await exists(outPath))) {
    console.log(`skip  ${line.id} (exists, use --force to regenerate)`);
    return;
  }

  const r = await fetch(
    `https://api.elevenlabs.io/v1/text-to-speech/${voiceId}`,
    {
      method: "POST",
      headers: {
        "xi-api-key": apiKey,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        text: line.text,
        model_id: model,
        voice_settings: { stability: 0.5, similarity_boost: 0.75 },
      }),
    },
  );

  if (!r.ok) {
    const body = await r.text();
    throw new Error(`${line.id} → ${r.status}: ${body.slice(0, 200)}`);
  }

  const buf = Buffer.from(await r.arrayBuffer());
  await writeFile(outPath, buf);
  console.log(`wrote ${line.id}.mp3 (${(buf.length / 1024).toFixed(1)} KB)`);
}

for (const line of script.lines) {
  await synth(line);
}
