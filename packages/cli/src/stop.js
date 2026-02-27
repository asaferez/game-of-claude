import { readFileSync, writeFileSync, existsSync } from "fs";
import { SETTINGS_FILE } from "./config.js";

export function stop() {
  if (!existsSync(SETTINGS_FILE)) { console.log("No Claude settings file found."); return; }
  let settings;
  try { settings = JSON.parse(readFileSync(SETTINGS_FILE, "utf8")); } catch { console.error("Could not parse settings.json."); process.exit(1); }

  if (!settings.hooks) { console.log("No hooks found. Already stopped."); return; }

  let removed = 0;
  for (const [event, entries] of Object.entries(settings.hooks)) {
    const before = entries.length;
    settings.hooks[event] = entries.filter((e) => !e.hooks?.some((h) => h.url?.includes("gameofclaude.dev")));
    removed += before - settings.hooks[event].length;
    if (settings.hooks[event].length === 0) delete settings.hooks[event];
  }
  if (Object.keys(settings.hooks).length === 0) delete settings.hooks;

  writeFileSync(SETTINGS_FILE, JSON.stringify(settings, null, 2));
  console.log(`Removed ${removed} hook entries. Run \`game-of-claude delete-data\` to erase server data.`);
}
