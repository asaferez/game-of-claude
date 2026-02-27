import { createInterface } from "readline";
import fetch from "node-fetch";
import { readConfig, API_BASE } from "./config.js";
import { stop } from "./stop.js";

function prompt(q) {
  const rl = createInterface({ input: process.stdin, output: process.stdout });
  return new Promise((resolve) => { rl.question(q, (a) => { rl.close(); resolve(a.trim()); }); });
}

export async function deleteData() {
  const config = readConfig();
  if (!config?.device_id) { console.log("Not installed. Nothing to delete."); return; }

  const confirm = await prompt("This will permanently delete ALL your XP, quests, and stats. Type 'yes' to confirm: ");
  if (confirm.toLowerCase() !== "yes") { console.log("Cancelled."); return; }

  process.stdout.write("Deleting data... ");
  try {
    const res = await fetch(`${API_BASE}/api/me`, { method: "DELETE", headers: { Authorization: `Bearer ${config.device_id}` } });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    console.log("done.");
  } catch (err) { console.error(`\nFailed: ${err.message}`); process.exit(1); }

  stop();
  console.log("\nAll data deleted. Thanks for playing.");
}
