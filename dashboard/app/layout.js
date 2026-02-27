import "./globals.css";

export const metadata = {
  title: "Game of Claude",
  description: "Level up while you ship — gamification for Claude Code",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
