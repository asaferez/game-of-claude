"use client";

const WEEKS = 20;
const DAYS_PER_WEEK = 7;

function getColorClass(count) {
  if (!count) return "bg-border";
  if (count === 1) return "bg-brand/30";
  if (count <= 3) return "bg-brand/55";
  if (count <= 6) return "bg-brand/80";
  return "bg-brand";
}

function buildGrid(activity) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  // Align to the most recent Sunday
  const dayOfWeek = today.getDay();
  const grid = [];

  for (let w = WEEKS - 1; w >= 0; w--) {
    const week = [];
    for (let d = 0; d < DAYS_PER_WEEK; d++) {
      const daysAgo = w * 7 + (dayOfWeek - d);
      const date = new Date(today);
      date.setDate(today.getDate() - daysAgo);
      const key = date.toISOString().slice(0, 10);
      week.push({ date: key, count: activity[key] || 0 });
    }
    grid.push(week);
  }

  return grid;
}

const MONTH_LABELS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

export default function ActivityHeatmap({ activity = {} }) {
  const grid = buildGrid(activity);

  // Find month label positions (week index where month changes)
  const monthMarkers = [];
  let lastMonth = null;
  grid.forEach((week, wi) => {
    const month = parseInt(week[0].date.slice(5, 7), 10) - 1;
    if (month !== lastMonth) {
      monthMarkers.push({ wi, label: MONTH_LABELS[month] });
      lastMonth = month;
    }
  });

  const CELL = 14; // px per cell + gap

  return (
    <div>
      <div className="relative" style={{ minWidth: WEEKS * CELL }}>
        {/* Month labels */}
        <div className="flex mb-1 ml-0" style={{ paddingLeft: 0 }}>
          {monthMarkers.map(({ wi, label }) => (
            <span
              key={wi}
              className="text-xs text-muted absolute"
              style={{ left: wi * CELL }}
            >
              {label}
            </span>
          ))}
        </div>
        {/* Grid */}
        <div className="flex gap-0.5 mt-4">
          {grid.map((week, wi) => (
            <div key={wi} className="flex flex-col gap-0.5">
              {week.map(({ date, count }) => (
                <div
                  key={date}
                  title={count ? `${date}: ${count} events` : date}
                  className={`w-3.5 h-3.5 rounded-sm ${getColorClass(count)}`}
                />
              ))}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
