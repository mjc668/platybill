"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  HardDriveDownload,
  HardDriveUpload,
  ChevronsUpDown,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { fetchMe, UserProfile } from "@/lib/user-api";
import { useCollapsedCategories } from "@/hooks/useCollapsedCategories";
import BackupButton from "@/components/BackupButton";
import RestoreButton from "@/components/RestoreButton";
import SnapshotRecoverySection from "@/components/SnapshotRecoverySection";
import { Tile } from "@/components/settings/Tile";
import { ProfileTile } from "@/components/settings/ProfileTile";
import { EmailNotificationsTile } from "@/components/settings/EmailNotificationsTile";
import { BrowserNotificationsTile } from "@/components/settings/BrowserNotificationsTile";
import { CategoriesTile } from "@/components/settings/CategoriesTile";
import { BillImportTile } from "@/components/settings/BillImportTile";
import { UnsavedChangesDialog } from "@/components/settings/UnsavedChangesDialog";

export default function SettingsPage() {
  const t = useTranslations("SettingsPage");
  const router = useRouter();

  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [profileDirty, setProfileDirty] = useState(false);
  const [emailDirty, setEmailDirty] = useState(false);
  const [pendingHref, setPendingHref] = useState<string | null>(null);

  const TILE_KEYS = ["profile", "email-notifications", "browser-notifications", "categories", "backup", "restore"] as const;

  const { collapsed, toggle, collapseAll, expandAll, allCollapsed } =
    useCollapsedCategories("settings-collapsed-tiles", TILE_KEYS);

  const isDirtyAny = profileDirty || emailDirty;

  const onProfileDirty = useCallback((d: boolean) => setProfileDirty(d), []);
  const onEmailDirty = useCallback((d: boolean) => setEmailDirty(d), []);

  useEffect(() => {
    fetchMe().then(setProfile).catch(() => {});
  }, []);

  // Browser tab close / refresh guard
  const handleBeforeUnload = useCallback(
    (e: BeforeUnloadEvent) => {
      if (isDirtyAny) e.preventDefault();
    },
    [isDirtyAny],
  );
  useEffect(() => {
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [handleBeforeUnload]);

  // In-app navigation guard: capture all anchor clicks at document level
  const handleNavClick = useCallback(
    (e: MouseEvent) => {
      if (!isDirtyAny) return;
      const anchor = (e.target as Element).closest("a[href]");
      if (!anchor) return;
      const href = anchor.getAttribute("href");
      if (!href || href.startsWith("http") || href.startsWith("#") || href.startsWith("mailto:"))
        return;
      e.preventDefault();
      e.stopPropagation();
      setPendingHref(href);
    },
    [isDirtyAny],
  );
  useEffect(() => {
    document.addEventListener("click", handleNavClick, true);
    return () => document.removeEventListener("click", handleNavClick, true);
  }, [handleNavClick]);

  function confirmLeave() {
    if (pendingHref) {
      setPendingHref(null);
      router.push(pendingHref);
    }
  }

  if (!profile) {
    return (
      <div className="mx-auto max-w-4xl px-4 py-8 space-y-4">
        {[1, 2, 3, 4, 5].map((i) => (
          <div key={i} className="h-32 rounded-xl bg-slate-100 dark:bg-slate-700 animate-pulse" />
        ))}
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl px-4 py-8 space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-slate-800 dark:text-slate-100">
          {t("pageTitle")}
        </h1>
        <button
          onClick={allCollapsed ? expandAll : collapseAll}
          className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-500 shadow-sm transition-all hover:border-slate-300 hover:bg-slate-50 hover:text-slate-700 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-400 dark:hover:border-slate-600 dark:hover:text-slate-200"
        >
          <ChevronsUpDown size={13} />
          {allCollapsed ? t("expandAll") : t("collapseAll")}
        </button>
      </div>

      <ProfileTile
        profile={profile}
        onProfileUpdate={setProfile}
        onDirtyChange={onProfileDirty}
        t={t}
        isCollapsed={collapsed.has("profile")}
        onToggle={() => toggle("profile")}
      />

      <EmailNotificationsTile
        profile={profile}
        onProfileUpdate={setProfile}
        onDirtyChange={onEmailDirty}
        t={t}
        isCollapsed={collapsed.has("email-notifications")}
        onToggle={() => toggle("email-notifications")}
      />

      <BrowserNotificationsTile
        t={t}
        isCollapsed={collapsed.has("browser-notifications")}
        onToggle={() => toggle("browser-notifications")}
      />

      <CategoriesTile
        t={t}
        isCollapsed={collapsed.has("categories")}
        onToggle={() => toggle("categories")}
      />

      <BillImportTile
        t={t}
        isCollapsed={collapsed.has("bill-import")}
        onToggle={() => toggle("bill-import")}
      />

      <Tile
        color="blue"
        icon={HardDriveDownload}
        title={t("backup.title")}
        description={t("backup.description")}
        t={t}
        isCollapsed={collapsed.has("backup")}
        onToggle={() => toggle("backup")}
      >
        <BackupButton label="Backup" />
      </Tile>

      <Tile
        color="red"
        icon={HardDriveUpload}
        title={t("restore.title")}
        description={t("restore.description")}
        t={t}
        isCollapsed={collapsed.has("restore")}
        onToggle={() => toggle("restore")}
      >
        <RestoreButton label="Restore" />
        <SnapshotRecoverySection />
      </Tile>

      {pendingHref && (
        <UnsavedChangesDialog
          onLeave={confirmLeave}
          onStay={() => setPendingHref(null)}
          t={t}
        />
      )}
    </div>
  );
}
