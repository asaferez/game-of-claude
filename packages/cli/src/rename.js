import { createInterface } from "readline";
import fetch from "node-fetch";
import { readConfig, writeConfig, API_BASE } from "./config.js";

function prompt(q) {
  const rl = createInterface({ input: process.stdin, output: process.stdout });
  return new Promise((resolve) => { rl.question(q, (a) => { rl.close(); resolve(a.trim()); }); });
}

export async function rename() {
  const config = readConfig();
  if (!config?.device_id) { console.log("Not installed. Run: npx game-of-claude install"); return; }

  const newName = await prompt(`New character name (current: ${config.character_name}): `);
  if (!newName) { console.log("Cancelled."); return; }

  const res = await fetch(`${API_BASE}/api/profile/${config.device_id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${config.device_id}` },
    body: JSON.stringify({ character_name: newName }),
  });
  if (!res.ok) { console.error(`Failed: HTTP ${res.status}`); process.exit(1); }

  writeConfig({ ...config, character_name: newName });
  console.log(`Character renamed to: ${newName}`);
}
