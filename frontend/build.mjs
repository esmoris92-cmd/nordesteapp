// Compila la interfaz con esbuild y deja el resultado en frontend/dist,
// carpeta que el backend sirve en http://localhost:8000.
//   npm run build  -> compilación optimizada (una vez)
//   npm run dev    -> recompila automáticamente al guardar cambios
import * as esbuild from "esbuild";
import { cpSync, mkdirSync, rmSync } from "node:fs";

const watch = process.argv.includes("--watch");

rmSync("dist", { recursive: true, force: true });
mkdirSync("dist", { recursive: true });
cpSync("public", "dist", { recursive: true });

const options = {
  entryPoints: ["src/main.tsx"],
  bundle: true,
  outfile: "dist/app.js",
  format: "esm",
  target: ["es2020", "safari15"],
  jsx: "automatic",
  minify: !watch,
  sourcemap: watch,
  define: { "process.env.NODE_ENV": JSON.stringify(watch ? "development" : "production") },
  // Las tipografías se sirven tal cual desde public/fonts.
  external: ["/fonts/*"],
  logLevel: "info",
};

if (watch) {
  const ctx = await esbuild.context(options);
  await ctx.watch();
  console.log("Recompilando al guardar. Recarga el navegador para ver los cambios (Ctrl+C para salir).");
} else {
  await esbuild.build(options);
  console.log("Interfaz compilada en frontend/dist.");
}
