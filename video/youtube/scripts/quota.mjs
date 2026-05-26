import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import dotenv from "dotenv";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, "..");

dotenv.config({ path: join(ROOT, ".env") });
dotenv.config({ path: resolve(ROOT, "..", ".env") });

const apiKey = process.env.ELEVENLABS_API_KEY;
if (!apiKey) {
  console.error("ELEVENLABS_API_KEY missing. Add it to .env");
  process.exit(1);
}

const r = await fetch("https://api.elevenlabs.io/v1/user/subscription", {
  headers: { "xi-api-key": apiKey },
});

if (!r.ok) {
  console.error(`failed: ${r.status} ${await r.text()}`);
  process.exit(1);
}

const data = await r.json();
const used = data.character_count;
const limit = data.character_limit;
const remaining = limit - used;
const pct = ((remaining / limit) * 100).toFixed(1);

const fmt = (n) => n.toLocaleString();
console.log("");
console.log(`  Tier       ${data.tier}`);
console.log(`  Used       ${fmt(used)} chars`);
console.log(`  Limit      ${fmt(limit)} chars`);
console.log(`  Remaining  ${fmt(remaining)} chars  (${pct}%)`);
if (data.next_character_count_reset_unix) {
  const reset = new Date(data.next_character_count_reset_unix * 1000);
  console.log(`  Resets     ${reset.toLocaleString()}`);
}
console.log("");
