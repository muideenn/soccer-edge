import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// GitHub Pages project sites live under /<repo>/; Vercel serves from /.
export default defineConfig({
  plugins: [react()],
  base: process.env.BASE_PATH ?? "/",
});
