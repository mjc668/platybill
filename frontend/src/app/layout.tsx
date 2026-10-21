import type { Metadata, Viewport } from "next";
import { headers } from "next/headers";
import { connection } from "next/server";
import { Geist, Geist_Mono } from "next/font/google";
import { AuthProvider } from "@/context/auth-context";
import { LocaleProvider } from "@/context/locale-context";
import PwaRegister from "@/components/pwa-register";
import AppFooter from "@/components/AppFooter";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  viewportFit: "cover",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
    { media: "(prefers-color-scheme: dark)", color: "#0f172a" },
  ],
};

export const metadata: Metadata = {
  title: "Platybill",
  description: "Household bill tracking made simple",
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "Platybill",
  },
  icons: {
    icon: "/platybill-logo.png",
    apple: "/icon-192.png",
  },
};

function serializeForInlineScript(value: string): string {
  return JSON.stringify(value).replace(/</g, "\\u003c");
}

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  await connection();
  const nonce = (await headers()).get("x-nonce") ?? undefined;
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${geistSans.variable} ${geistMono.variable} h-full`}
    >
      <head>
        {/* Prevent flash of wrong theme */}
        <script
          nonce={nonce}
          dangerouslySetInnerHTML={{
            __html: `(function(){var t=localStorage.getItem('theme');if(t!=='light')document.documentElement.classList.add('dark');})();`,
          }}
        />
        {(() => {
          // Injected at request time from the container's .env (API_URL /
          // API_PREFIX) so the same image works anywhere without being
          // rebuilt. window.__PT_API_URL__ may be the empty string, which
          // means same-origin (Caddy) mode.
          const apiBaseUrl = process.env.API_URL?.trim() ?? "";
          const apiPrefix = process.env.API_PREFIX?.trim() ?? "";
          return (
            <script
              nonce={nonce}
              dangerouslySetInnerHTML={{
                __html: `window.__PT_API_URL__=${serializeForInlineScript(apiBaseUrl)};window.__PT_API_PREFIX__=${serializeForInlineScript(apiPrefix)};`,
              }}
            />
          );
        })()}
      </head>
      <body className="min-h-full flex flex-col bg-slate-50 dark:bg-slate-900 antialiased">
        <PwaRegister />
        <AuthProvider>
          <LocaleProvider>{children}</LocaleProvider>
        </AuthProvider>
        <AppFooter />
      </body>
    </html>
  );
}
