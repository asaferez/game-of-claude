#!/usr/bin/env node
import { install }    from "../src/install.js";
import { stop }       from "../src/stop.js";
import { deleteData } from "../src/delete_data.js";
import { status }     from "../src/status.js";
import { rename }     from "../src/rename.js";

const command = process.argv[2];
const commands = { install, stop, "delete-data": deleteData, status, rename };

if (!command || command === "--help" || command === "-h") {
  console.log(`
game-of-claude — Gamification for Claude Code

Commands:
  install       Set up hooks and create your character
  stop          Pause tracking (keeps your data)
  delete-data   Permanently delete all your data
  status        Show your XP and daily quests
  rename        Change your character name
`);
  process.exit(0);
}

const fn = commands[command];
if (!fn) { console.error(`Unknown command: ${command}`); process.exit(1); }
fn().catch((err) => { console.error(err.message); process.exit(1); });
