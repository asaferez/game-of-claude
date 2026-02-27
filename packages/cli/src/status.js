import fetch from "node-fetch";
import { readConfig, API_BASE, DASHBOARD_BASE } from "./config.js";

function bar(current, goal, width = 20) {
  const filled = Math.round((Math.min(current, goal) / goal) * width);
  return "[" + "█".repeat(filled) + "░".repeat(width - filled) + "]";
}

export async function status() {
  const config = readConfig();
  if (!config?.device_id) { console.log("Not installed. Run: npx game-of-claude install"); return; }

  let data;
  try {
    const res = await fetch(`${API_BASE}/api/profile/${config.device_id}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    data = await res.json();
  } catch (err) { console.error(`Could not reach backend: ${err.message}`); process.exit(1); }

  const { character_name, level, level_title, total_xp, xp_in_level, xp_to_next_level,
          current_streak, total_commits, total_test_passes, quests } = data;

  console.log(`\n⚔️  ${character_name}  —  Level ${level} ${level_title}`);
  console.log(`XP  ${bar(xp_in_level, xp_to_next_level)} ${xp_in_level}/${xp_to_next_level} to Level ${level + 1}`);
  console.log(`🔥 Streak: ${current_streak} days  |  📦 Commits: ${total_commits}  |  🧪 Tests: ${total_test_passes}\n`);

  const daily = (quests ?? []).filter((q) => q.type === "daily");
  if (daily.length > 0) {
    console.log("Daily Quests:");
    for (const q of daily) {
      const done = q.completed ? "✅" : "  ";
      console.log(`  ${done} ${bar(q.current, q.goal, 10)} ${q.name} — ${q.description}`);
    }
  }
  console.log(`\n📊 ${DASHBOARD_BASE}/dashboard?id=${config.device_id}\n`);
}
