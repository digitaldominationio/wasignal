import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Wasignal — AI agents on WhatsApp",
  description: "Inbound pipeline, agent runtime and scheduling for WhatsApp-native AI agents.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
