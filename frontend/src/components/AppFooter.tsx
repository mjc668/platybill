const APP_VERSION = process.env.NEXT_PUBLIC_APP_VERSION ?? "dev";

export default function AppFooter() {
  return (
    <footer className="hidden md:block fixed bottom-3 right-4 z-50 text-xs text-slate-400 dark:text-slate-500">
      <span>{APP_VERSION}</span>
    </footer>
  );
}
