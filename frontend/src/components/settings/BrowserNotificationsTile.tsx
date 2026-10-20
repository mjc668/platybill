"use client";

import { Bell, BellOff } from "lucide-react";
import { useTranslations } from "next-intl";
import { useNotifications } from "@/hooks/useNotifications";
import { Switch } from "@/components/ui/Switch";
import { Tile, type TileTranslator } from "./Tile";

export function BrowserNotificationsTile({
  t,
  isCollapsed,
  onToggle,
}: {
  t: TileTranslator;
  isCollapsed?: boolean;
  onToggle?: () => void;
}) {
  const tp = useTranslations("SettingsPage");
  const { permission, isEnabled, requestPermission, setEnabled } = useNotifications();

  return (
    <Tile
      color="yellow"
      icon={Bell}
      title={tp("browserNotifications.title")}
      description={tp("browserNotifications.description")}
      t={t}
      isCollapsed={isCollapsed}
      onToggle={onToggle}
    >
      {permission === "denied" ? (
        <div className="flex items-start gap-2 rounded-lg bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-700 px-3 py-2">
          <BellOff size={15} className="text-red-600 dark:text-red-400 mt-0.5 shrink-0" />
          <p className="text-sm text-red-700 dark:text-red-300">
            {tp("browserNotifications.blockedWarning")}
          </p>
        </div>
      ) : permission === "granted" ? (
        <div className="flex flex-col gap-2">
          <Switch
            checked={isEnabled}
            onChange={setEnabled}
            label={tp("browserNotifications.toggle")}
          />
          <p className="text-xs text-slate-400 dark:text-slate-500">
            {tp("browserNotifications.osHint")}
          </p>
        </div>
      ) : (
        <button
          onClick={requestPermission}
          className="rounded-lg border border-blue-700 bg-blue-700 px-4 py-1.5 text-sm font-medium text-white shadow-sm transition-all hover:border-blue-800 hover:bg-blue-800"
        >
          {tp("browserNotifications.enable")}
        </button>
      )}
    </Tile>
  );
}
