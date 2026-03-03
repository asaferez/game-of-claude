import { readFileSync, writeFileSync, existsSync, mkdirSync, copyFileSync } from "fs";
import { createInterface } from "readline";
import { join, dirname } from "path";
import { homedir } from "os";
import { fileURLToPath } from "url";
import fetch from "node-fetch";
import { readConfig, writeConfig, generateDeviceId, API_BASE, DASHBOARD_BASE, SETTINGS_FILE } from "./config.js";

function prompt(question) {
  const rl = createInterface({ input: process.stdin, output: process.stdout });
  return new Promise((resolve) => { rl.question(question, (a) => { rl.close(); resolve(a.trim()); }); });
}

function buildHooks(deviceId) {
  const httpHook = { type: "http", url: `${API_BASE}/api/events`, headers: { Authorization: `Bearer ${deviceId}` }, timeout: 10 };
  const scriptPath = join(homedir(), ".claude", "scripts", "process_session.py");
  const cmdHook = { type: "command", command: `python3 "${scriptPath}"`, timeout: 30 };
  return {
    SessionStart: [{ hooks: [httpHook, cmdHook] }],
    SessionEnd:   [{ hooks: [httpHook, cmdHook] }],
    PostToolUse:  [{ matcher: "Bash", hooks: [httpHook] }, { matcher: "Edit|Write", hooks: [httpHook] }],
  };
}

function mergeHooks(existing, newHooks) {
  const settings = { ...existing };
  settings.hooks = settings.hooks ?? {};
  for (const [event, entries] of Object.entries(newHooks)) {
    const filtered = (settings.hooks[event] ?? []).filter(
      (e) => !e.hooks?.some((h) =>
        h.url?.includes("gameofclaude") ||
        h.url?.includes("game-of-claude-production.up.railway.app") ||
        h.command?.includes("process_session")
      )
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

  // Install process_session.py script to ~/.claude/scripts/
  const scriptsDir = join(homedir(), ".claude", "scripts");
  if (!existsSync(scriptsDir)) mkdirSync(scriptsDir, { recursive: true });
  const __dirname = dirname(fileURLToPath(import.meta.url));
  const scriptSrc = join(__dirname, "..", "scripts", "process_session.py");
  const scriptDest = join(scriptsDir, "process_session.py");
  if (existsSync(scriptSrc)) {
    copyFileSync(scriptSrc, scriptDest);
  }

  let settings = {};
  if (existsSync(SETTINGS_FILE)) {
    try { settings = JSON.parse(readFileSync(SETTINGS_FILE, "utf8")); } catch {}
  }
  writeFileSync(SETTINGS_FILE, JSON.stringify(mergeHooks(settings, buildHooks(deviceId)), null, 2));
  writeConfig({ device_id: deviceId, character_name: characterName, api_base: API_BASE });

  console.log(`\n✅ You're in the game, ${characterName}! (+25 XP welcome bonus)`);
  console.log(`\n📊 Dashboard: ${DASHBOARD_BASE}/dashboard?id=${deviceId}`);
  console.log("   (bookmark this — it's your personal quest board)");
  console.log("\n🔄 Restart Claude Code now — hooks activate on the next session.\n");
}
