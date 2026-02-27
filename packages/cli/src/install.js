import { readFileSync, writeFileSync, existsSync } from "fs";
import { createInterface } from "readline";
import fetch from "node-fetch";
import { readConfig, writeConfig, generateDeviceId, API_BASE, DASHBOARD_BASE, SETTINGS_FILE } from "./config.js";

function prompt(question) {
  const rl = createInterface({ input: process.stdin, output: process.stdout });
  return new Promise((resolve) => { rl.question(question, (a) => { rl.close(); resolve(a.trim()); }); });
}

function buildHooks(deviceId) {
  const hook = { type: "http", url: `${API_BASE}/api/events`, headers: { Authorization: `Bearer ${deviceId}` }, async: true };
  return {
    SessionStart: [{ hooks: [hook] }],
    SessionEnd:   [{ hooks: [hook] }],
    PostToolUse:  [{ matcher: "Bash", hooks: [hook] }, { matcher: "Edit|Write", hooks: [hook] }],
  };
}

function mergeHooks(existing, newHooks) {
  const settings = { ...existing };
  settings.hooks = settings.hooks ?? {};
  for (const [event, entries] of Object.entries(newHooks)) {
    const filtered = (settings.hooks[event] ?? []).filter(
      (e) => !e.hooks?.some((h) => h.url?.includes("gameofclaude.dev"))
    );
    settings.hooks[event] = [...filtered, ...entries];
  }
  return settings;
}

export async function install() {
  console.log("\n🎮 Game of Claude — Installer\n");
  const existing = readConfig();
  if (existing?.device_id) {
    console.log(`Already installed. Device: ${existing.device_id}`);
    const redo = await prompt("Re-install? (y/N) ");
    if (redo.toLowerCase() !== "y") return;
  }

  const characterName = await prompt('Choose your character name (e.g. "ByteKnight"): ');
  if (!characterName) { console.error("Character name cannot be empty."); process.exit(1); }

  const deviceId = existing?.device_id ?? generateDeviceId();

  process.stdout.write("Registering... ");
  try {
    const res = await fetch(`${API_BASE}/api/devices`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device_id: deviceId, character_name: characterName }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    console.log("done.");
  } catch (err) {
    console.error(`\nFailed to reach backend: ${err.message}`);
    process.exit(1);
  }

  let settings = {};
  if (existsSync(SETTINGS_FILE)) {
    try { settings = JSON.parse(readFileSync(SETTINGS_FILE, "utf8")); } catch {}
  }
  writeFileSync(SETTINGS_FILE, JSON.stringify(mergeHooks(settings, buildHooks(deviceId)), null, 2));
  writeConfig({ device_id: deviceId, character_name: characterName, api_base: API_BASE });

  console.log(`\n✅ You're in the game, ${characterName}!`);
  console.log(`\n📊 Dashboard: ${DASHBOARD_BASE}/dashboard?id=${deviceId}`);
  console.log("   (bookmark this — it's your personal quest board)\n");
}
