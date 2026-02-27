import { readFileSync, writeFileSync, existsSync, mkdirSync } from "fs";
import { homedir } from "os";
import { join } from "path";
import { randomUUID } from "crypto";

const CONFIG_DIR = join(homedir(), ".claude");
const CONFIG_FILE = join(CONFIG_DIR, "gamify.json");

export const API_BASE = process.env.GAME_OF_CLAUDE_API ?? "https://game-of-claude-production.up.railway.app";
export const DASHBOARD_BASE = process.env.GAME_OF_CLAUDE_DASHBOARD ?? "https://game-of-claude.vercel.app";
export const SETTINGS_FILE = join(CONFIG_DIR, "settings.json");

export function readConfig() {
  if (!existsSync(CONFIG_FILE)) return null;
  try { return JSON.parse(readFileSync(CONFIG_FILE, "utf8")); } catch { return null; }
}

export function writeConfig(data) {
  if (!existsSync(CONFIG_DIR)) mkdirSync(CONFIG_DIR, { recursive: true });
  writeFileSync(CONFIG_FILE, JSON.stringify(data, null, 2));
}

export function generateDeviceId() { return randomUUID(); }
