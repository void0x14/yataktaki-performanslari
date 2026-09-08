# PNPM-only policy

This project uses only `pnpm` and `pnpx`.

- Install dependencies with `pnpm install`.
- Run development with `pnpm dev`.
- Build the frontend with `pnpm build`.
- Build Tauri with `pnpm tauri build`.
- Project install, development, build, and Tauri entrypoints reject npm and npx runners through `scripts/pnpm-only.sh`.
- `package-lock.json` is intentionally forbidden; the canonical lockfile is `pnpm-lock.yaml`.
- The repository does not globally modify the operating system's `npm` or `npx` binaries; commands outside this project remain under the user's shell permissions.
