import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Nexus AI — Enterprise RAG Platform",
  description: "Upload documents and ask questions with cited AI answers",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="h-full">
      <body className="h-full">{children}</body>
    </html>
  );
}
