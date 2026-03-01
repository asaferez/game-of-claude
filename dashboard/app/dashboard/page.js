import { notFound } from "next/navigation";
import Link from "next/link";
import LevelRing from "@/components/LevelRing";
import XPBar from "@/components/XPBar";
import QuestCard from "@/components/QuestCard";
import ActivityHeatmap from "@/components/ActivityHeatmap";
import AutoRefresh from "@/components/AutoRefresh";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ??
  "https://game-of-claude-production.up.railway.app";

async function fetchProfile(deviceId) {
  const res = await fetch(`${API_BASE}/api/profile/${deviceId}`, {
    next: { revalidate: 10 },
  });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error("Failed to load profile");
  return res.json();
}

async function fetchActivity(deviceId) {
  try {
    const res = await fetch(`${API_BASE}/api/activity/${deviceId}`, {
      next: { revalidate: 60 },
    });
    if (!res.ok) return {};
    const data = await res.json();
    return data.activity ?? {};
  } catch {
    return {};
  }
}

async function fetchStats(deviceId) {
  try {
    const res = await fetch(`${API_BASE}/api/stats/${deviceId}`, {
      next: { revalidate: 60 },
    });
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

export async function generateMetadata({ searchParams }) {
  const id = (await searchParams).id;
  if (!id) return { title: "Game of Claude" };
  try {
    const profile = await fetchProfile(id);
    if (!profile) return { title: "Profile not found — Game of Claude" };
    return {
      title: `${profile.character_name} · Lvl ${profile.level} ${profile.level_title}`,
      description: `${profile.total_xp.toLocaleString()} XP · ${profile.current_streak}d streak · ${profile.total_commits} commits`,
    };
  } catch {
    return { title: "Game of Claude" };
  }
}

function formatNum(n) {
  if (n == null) return "0";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

function formatHours(minutes) {
  if (!minutes) return "0h";
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (h === 0) return `${m}m`;
  if (m === 0) return `${h}h`;
  return `${h}h ${m}m`;
}

export default async function DashboardPage({ searchParams }) {
  const id = (await searchParams).id;
  if (!id) return <MissingId />;

  const [profile, activity, stats] = await Promise.all([
    fetchProfile(id),
    fetchActivity(id),
    fetchStats(id),
  ]);

  if (!profile) notFound();

  const dailyQuests = profile.quests.filter((q) => q.type === "daily");
  const progressiveQuests = profile.quests.filter(
    (q) => q.type === "progressive" && !q.completed
  );
  const completedProgressiveQuests = profile.quests.filter(
    (q) => q.type === "progressive" && q.completed
  );

  return (
    <main className="min-h-screen bg-surface px-4 py-8 max-w-2xl mx-auto">
      <AutoRefresh intervalMs={30_000} />

      {/* Header */}
      <div className="flex items-center gap-4 mb-6">
        <div className="flex-1">
          <h1 className="text-2xl font-bold text-white">{profile.character_name}</h1>
          <p className="text-xs text-muted mt-0.5">
            Member since{" "}
            {new Date(profile.member_since).toLocaleDateString("en-US", {
              month: "long",
              year: "numeric",
            })}
          </p>
        </div>
        <div className="text-right">
          <div className="text-2xl font-bold text-gold">{profile.total_xp.toLocaleString()}</div>
          <div className="text-xs text-muted uppercase tracking-wide">Total XP</div>
        </div>
      </div>

      {/* ── TODAY ── live stats for phone-while-coding use */}
      <section className="mb-6">
        <SectionLabel>Today</SectionLabel>
        <div className="grid grid-cols-3 gap-3">
          <LiveCard icon="⚡" value={profile.sessions_today ?? 0} label="Sessions" />
          <LiveCard icon="📦" value={profile.commits_today ?? 0} label="Commits" />
          <LiveCard
            icon="🔥"
            value={`${profile.current_streak}d`}
            label="Streak"
            glow={profile.current_streak > 0}
          />
        </div>
      </section>

      {/* ── XP / LEVEL ── game mechanic */}
      <div className="bg-card border border-border rounded-2xl p-6 mb-6 flex flex-col items-center gap-5">
        <LevelRing
          level={profile.level}
          xpInLevel={profile.xp_in_level}
          xpToNextLevel={profile.xp_to_next_level}
          levelTitle={profile.level_title}
        />
        <div className="w-full max-w-sm">
          <XPBar
            xpInLevel={profile.xp_in_level}
            xpToNextLevel={profile.xp_to_next_level}
          />
        </div>
      </div>

      {/* ── CAREER STATS ── all real data */}
      <section className="mb-6">
        <SectionLabel>Career Stats</SectionLabel>
        <div className="grid grid-cols-3 gap-3">
          <StatCard label="Sessions" value={profile.total_sessions} />
          <StatCard label="Commits" value={profile.total_commits} />
          <StatCard label="Branches" value={profile.total_branches ?? 0} />
          <StatCard label="PRs merged" value={profile.total_merged_prs ?? 0} />
          <StatCard label="Tests passed" value={profile.total_test_passes} />
          <StatCard label="Languages" value={profile.unique_extensions ?? 0} />
          <StatCard
            label="Lines shipped"
            value={formatNum(profile.total_insertions ?? 0)}
          />
          <StatCard
            label="Coding time"
            value={formatHours(profile.total_session_minutes ?? 0)}
          />
          <StatCard
            label="Best streak"
            value={`${profile.longest_streak}d`}
          />
        </div>
        <div className="grid grid-cols-2 gap-3 mt-3">
          <Link
            href="/leaderboard"
            className="bg-card border border-border hover:border-brand/50 rounded-xl p-3 text-center transition-colors"
          >
            <div className="text-xl font-bold text-brand-light">↗</div>
            <div className="text-xs text-muted mt-0.5">Leaderboard</div>
          </Link>
          <a
            href="https://claude.ai/settings/usage"
            target="_blank"
            rel="noopener noreferrer"
            className="bg-card border border-border hover:border-brand/50 rounded-xl p-3 flex items-center justify-between transition-colors"
          >
            <div className="flex items-center gap-2">
              <span className="text-sm">⚡</span>
              <div>
                <div className="text-xs font-semibold text-white text-left">Claude Usage</div>
                <div className="text-xs text-muted">Plan limits</div>
              </div>
            </div>
            <div className="text-xs text-brand-light">↗</div>
          </a>
        </div>
      </section>

      {/* ── DAILY QUESTS ── XP game */}
      <section className="mb-6">
        <SectionLabel>Daily Quests</SectionLabel>
        <div className="flex flex-col gap-2">
          {dailyQuests.map((q) => (
            <QuestCard key={q.id} quest={q} />
          ))}
        </div>
      </section>

      {/* ── ACTIVE QUESTS ── XP game */}
      {progressiveQuests.length > 0 && (
        <section className="mb-6">
          <SectionLabel>Active Quests</SectionLabel>
          <div className="flex flex-col gap-2">
            {progressiveQuests.map((q) => (
              <QuestCard key={q.id} quest={q} />
            ))}
          </div>
        </section>
      )}

      {/* ── ACTIVITY HEATMAP ── */}
      <section className="mb-6">
        <SectionLabel>Activity</SectionLabel>
        <div className="bg-card border border-border rounded-2xl p-4">
          <ActivityHeatmap activity={activity} />
        </div>
      </section>

      {/* ── CODING STATS ── from raw events */}
      {stats && (stats.top_projects.length > 0 || stats.tool_usage.length > 0) && (
        <section className="mb-6">
          <SectionLabel>
            Coding Stats{" "}
            <span className="normal-case font-normal text-muted">(last 30 days)</span>
          </SectionLabel>
          <div className="grid grid-cols-2 gap-3">
            {stats.top_projects.length > 0 && (
              <div className="bg-card border border-border rounded-2xl p-4">
                <div className="text-xs text-muted mb-2">Top Projects</div>
                <MiniBarList
                  items={stats.top_projects.map((p) => ({ label: p.name, count: p.count }))}
                />
              </div>
            )}
            {stats.tool_usage.length > 0 && (
              <div className="bg-card border border-border rounded-2xl p-4">
                <div className="text-xs text-muted mb-2">Tools Used</div>
                <MiniBarList
                  items={stats.tool_usage.map((t) => ({ label: t.tool, count: t.count }))}
                />
              </div>
            )}
          </div>
          {stats.peak_hour != null && (
            <div className="mt-3 bg-card border border-border rounded-2xl p-4 flex items-center gap-3">
              <span className="text-2xl">⏰</span>
              <div>
                <div className="text-sm font-semibold text-white">
                  Peak hour: {formatHour(stats.peak_hour)}
                </div>
                <div className="text-xs text-muted">Most active coding time (UTC)</div>
              </div>
            </div>
          )}
        </section>
      )}

      {/* ── COMPLETED QUESTS ── */}
      {completedProgressiveQuests.length > 0 && (
        <section>
          <SectionLabel>Completed</SectionLabel>
          <div className="flex flex-col gap-2 opacity-60">
            {completedProgressiveQuests.map((q) => (
              <QuestCard key={q.id} quest={q} />
            ))}
          </div>
        </section>
      )}
    </main>
  );
}

function SectionLabel({ children }) {
  return (
    <h2 className="text-xs font-semibold text-muted uppercase tracking-wider mb-3">
      {children}
    </h2>
  );
}

function LiveCard({ icon, value, label, glow }) {
  return (
    <div
      className={`rounded-xl p-3 text-center border ${
        glow ? "bg-gold/10 border-gold/40" : "bg-card border-border"
      }`}
    >
      <div className="text-base mb-0.5">{icon}</div>
      <div className={`text-2xl font-bold ${glow ? "text-gold" : "text-white"}`}>
        {value}
      </div>
      <div className="text-xs text-muted mt-0.5">{label}</div>
    </div>
  );
}

function StatCard({ label, value }) {
  return (
    <div className="bg-card border border-border rounded-xl p-3 text-center">
      <div className="text-xl font-bold text-white">{value}</div>
      <div className="text-xs text-muted mt-0.5">{label}</div>
    </div>
  );
}

function MiniBarList({ items }) {
  const max = Math.max(...items.map((i) => i.count), 1);
  return (
    <div className="flex flex-col gap-1.5">
      {items.map(({ label, count }) => (
        <div key={label}>
          <div className="flex justify-between text-xs mb-0.5">
            <span className="text-white truncate max-w-[80%]">{label}</span>
            <span className="text-muted">{count}</span>
          </div>
          <div className="h-1 bg-border rounded-full overflow-hidden">
            <div
              className="h-full bg-brand rounded-full"
              style={{ width: `${(count / max) * 100}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

function formatHour(h) {
  const ampm = h >= 12 ? "PM" : "AM";
  const display = h % 12 || 12;
  return `${display}:00 ${ampm}`;
}

function MissingId() {
  return (
    <main className="min-h-screen bg-surface flex items-center justify-center px-4">
      <div className="text-center max-w-sm">
        <div className="text-4xl mb-4">🎮</div>
        <h1 className="text-xl font-bold text-white mb-2">No profile ID</h1>
        <p className="text-muted text-sm mb-4">
          Add <code className="text-brand-light">?id=your-device-id</code> to
          the URL, or{" "}
          <Link href="/install" className="text-brand-light underline">
            install game-of-claude
          </Link>{" "}
          to get yours.
        </p>
      </div>
    </main>
  );
}
