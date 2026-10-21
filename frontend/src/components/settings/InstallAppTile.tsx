"use client";

import { useEffect, useState, useSyncExternalStore } from "react";
import { CheckCircle2, Download, Smartphone, Share, PlusSquare } from "lucide-react";

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

const APP_VERSION = process.env.NEXT_PUBLIC_APP_VERSION ?? "dev";

function subscribeStandalone(callback: () => void) {
  if (typeof window === "undefined") return () => {};
  const mql = window.matchMedia("(display-mode: standalone)");
  mql.addEventListener("change", callback);
  return () => mql.removeEventListener("change", callback);
}

function getStandaloneSnapshot(): boolean {
  if (typeof window === "undefined") return false;
  return (
    window.matchMedia("(display-mode: standalone)").matches ||
    (window.navigator as unknown as { standalone?: boolean }).standalone === true
  );
}

function getStandaloneServerSnapshot(): boolean {
  return false;
}

function getIosSnapshot(): boolean {
  if (typeof window === "undefined") return false;
  return /iphone|ipad|ipod/.test(window.navigator.userAgent.toLowerCase());
}

function getIosServerSnapshot(): boolean {
  return false;
}

export function InstallAppTile() {
  const isStandalone = useSyncExternalStore(
    subscribeStandalone,
    getStandaloneSnapshot,
    getStandaloneServerSnapshot,
  );
  const isIos = useSyncExternalStore(
    () => () => {},
    getIosSnapshot,
    getIosServerSnapshot,
  );

  const [installPrompt, setInstallPrompt] = useState<BeforeInstallPromptEvent | null>(null);
  const [installed, setInstalled] = useState(false);

  useEffect(() => {
    // Listen for Android / Chrome install prompt
    const handleBeforeInstallPrompt = (e: Event) => {
      e.preventDefault();
      setInstallPrompt(e as BeforeInstallPromptEvent);
    };

    window.addEventListener("beforeinstallprompt", handleBeforeInstallPrompt);
    const handleAppInstalled = () => {
      setInstalled(true);
      setInstallPrompt(null);
    };
    window.addEventListener("appinstalled", handleAppInstalled);

    return () => {
      window.removeEventListener("beforeinstallprompt", handleBeforeInstallPrompt);
      window.removeEventListener("appinstalled", handleAppInstalled);
    };
  }, []);

  async function handleInstallClick() {
    if (!installPrompt) return;
    await installPrompt.prompt();
    const choice = await installPrompt.userChoice;
    if (choice.outcome === "accepted") {
      setInstalled(true);
      setInstallPrompt(null);
    }
  }

  return (
    <div className="rounded-xl border border-slate-200 border-l-4 border-l-blue-500 bg-white shadow-sm dark:border-slate-700 dark:bg-slate-800 overflow-hidden">
      <div className="flex items-center gap-3 px-4 py-3 bg-blue-50/50 dark:bg-blue-900/20 border-b border-slate-100 dark:border-slate-700/60">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-100 text-blue-600 dark:bg-blue-900/50 dark:text-blue-400 shrink-0">
          <Smartphone size={18} />
        </div>
        <div>
          <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100">
            Phone App & Installation
          </h2>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            Install Platybill to your phone&apos;s home screen
          </p>
        </div>
      </div>

      <div className="p-4 space-y-3 text-sm text-slate-600 dark:text-slate-300">
        {isStandalone || installed ? (
          <div className="flex items-center gap-2.5 rounded-lg bg-emerald-50 px-3 py-2.5 text-emerald-800 dark:bg-emerald-900/20 dark:text-emerald-300">
            <CheckCircle2 size={18} className="shrink-0 text-emerald-600 dark:text-emerald-400" />
            <span className="font-medium text-xs sm:text-sm">
              Platybill is installed and running in standalone app mode.
            </span>
          </div>
        ) : installPrompt ? (
          <div className="space-y-3">
            <p className="text-xs sm:text-sm">
              Install Platybill on your device for fast access, full-screen viewing, and an app icon on your home screen.
            </p>
            <button
              onClick={handleInstallClick}
              className="flex items-center gap-2 rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 transition-colors"
            >
              <Download size={16} />
              Install App
            </button>
          </div>
        ) : isIos ? (
          <div className="space-y-2 text-xs sm:text-sm">
            <p className="font-medium text-slate-700 dark:text-slate-200">
              To install Platybill on your iPhone or iPad:
            </p>
            <ol className="list-decimal list-inside space-y-1.5 text-slate-600 dark:text-slate-400">
              <li className="flex items-center gap-1.5">
                <span>1. Tap the Share button in Safari</span>
                <span className="inline-flex items-center rounded border border-slate-200 bg-slate-100 px-1 py-0.5 text-xs text-slate-600 dark:border-slate-600 dark:bg-slate-700 dark:text-slate-300">
                  <Share size={12} className="inline mr-1" /> Share
                </span>
              </li>
              <li className="flex items-center gap-1.5">
                <span>2. Scroll down and tap</span>
                <span className="inline-flex items-center rounded border border-slate-200 bg-slate-100 px-1 py-0.5 text-xs text-slate-600 dark:border-slate-600 dark:bg-slate-700 dark:text-slate-300">
                  <PlusSquare size={12} className="inline mr-1" /> Add to Home Screen
                </span>
              </li>
              <li>3. Tap <strong>Add</strong> in the top-right corner.</li>
            </ol>
          </div>
        ) : (
          <div className="space-y-2 text-xs sm:text-sm">
            <p>
              To install Platybill as a phone app, open your browser menu (⋮) and tap <strong>Install app</strong> or <strong>Add to Home screen</strong>.
            </p>
          </div>
        )}

        <div className="pt-2 border-t border-slate-100 dark:border-slate-700/60 flex items-center justify-between text-xs text-slate-400 dark:text-slate-500">
          <span>Platybill PWA</span>
          <span>Version: {APP_VERSION}</span>
        </div>
      </div>
    </div>
  );
}
