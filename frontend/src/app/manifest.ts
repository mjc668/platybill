import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Platybill",
    short_name: "Platybill",
    description: "Household bill tracking made simple",
    start_url: "/dashboard",
    display: "standalone",
    orientation: "portrait-primary",
    background_color: "#ffffff",
    theme_color: "#2563eb",
    icons: [
      {
        src: "/icon-192.png",
        sizes: "192x192",
        type: "image/png",
        purpose: "any",
      },
      {
        src: "/icon-192.png",
        sizes: "192x192",
        type: "image/png",
        purpose: "maskable",
      },
      {
        src: "/icon-512.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "any",
      },
      {
        src: "/icon-512.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "maskable",
      },
    ],
    shortcuts: [
      {
        name: "Payments",
        short_name: "Payments",
        description: "View upcoming and paid bills",
        url: "/dashboard/payments",
        icons: [{ src: "/icon-192.png", sizes: "192x192" }],
      },
      {
        name: "Bills",
        short_name: "Bills",
        description: "Manage bill templates",
        url: "/dashboard/bills",
        icons: [{ src: "/icon-192.png", sizes: "192x192" }],
      },
    ],
  };
}
