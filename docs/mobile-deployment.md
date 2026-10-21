# Mobile App Deployment & Installation Guide

Platybill is built as a phone-friendly, installable mobile application that can be run on iOS and Android devices.

---

## 1. Zero-Friction Method: Progressive Web App (PWA)

Platybill supports Progressive Web App (PWA) standards. It does not require app store approval, developer licenses, or manual compilation.

### Prerequisites for PWA Installation
- Browsers require an **HTTPS connection** to allow home screen installation and Service Worker registration (unless connecting to `localhost`).
- When self-hosting on Unraid, Docker, or a home server, terminate HTTPS using:
  - Caddy / Nginx reverse proxy (e.g. `caddy reverse-proxy --from platybill.lan:443 --to localhost:3010`)
  - Cloudflare Tunnel
  - Tailscale Funnel / MagicDNS with SSL certificates

### Installing on iPhone / iPad (iOS Safari)
1. Open your Platybill URL in **Safari** (iOS does not allow PWA installation from Chrome or Firefox).
2. Tap the **Share** button (⎋ with an arrow pointing up) in the bottom navigation toolbar.
3. Scroll down in the share sheet and tap **Add to Home Screen** (⊕).
4. Tap **Add** in the top-right corner.
5. Platybill will now appear on your home screen with its app icon. When opened, it runs in edge-to-edge standalone mode without Safari address bars or browser controls.

### Installing on Android (Chrome / Brave / Edge)
1. Open your Platybill URL in **Google Chrome** (or your preferred Android browser).
2. If prompted, tap the **Install** or **Add Platybill to Home screen** banner at the bottom.
3. Alternatively, tap the **three-dots menu (⋮)** in the top right and select **Install app** or **Add to Home screen**.
4. The system will create an Android WebAPK with an adaptive icon on your app drawer and home screen.

---

## 2. Native Mobile App Package (Capacitor Blueprint)

If you require an actual standalone `.apk` package for Android (e.g. to distribute internally or sideload onto phones):

### Architecture Overview
Platybill uses a Next.js frontend with a Python FastAPI backend. In a native mobile app container, Capacitor wraps the web interface and points to your self-hosted Platybill server URL.

### Quick Start for Android APK with Capacitor

1. In the `frontend/` directory, initialize Capacitor:
   ```bash
   cd frontend
   npm install @capacitor/core @capacitor/cli @capacitor/android
   npx cap init Platybill com.platybill.app
   ```

2. Configure `capacitor.config.ts` to point to your live Platybill server:
   ```typescript
   import type { CapacitorConfig } from '@capacitor/cli';

   const config: CapacitorConfig = {
     appId: 'com.platybill.app',
     appName: 'Platybill',
     webDir: 'public',
     server: {
       url: 'https://your-platybill-domain.com',
       cleartext: false, // Set to true only if testing over plain http on local LAN
     },
   };

   export default config;
   ```

3. Add the Android platform:
   ```bash
   npx cap add android
   ```

4. Build the Android project and output the APK:
   ```bash
   npx cap open android
   # In Android Studio: Build > Build Bundle(s) / APK(s) > Build APK(s)
   ```
   Or via Gradle command line:
   ```bash
   cd android && ./gradlew assembleDebug
   ```
   The generated debug APK will be located at `android/app/build/outputs/apk/debug/app-debug.apk`.
