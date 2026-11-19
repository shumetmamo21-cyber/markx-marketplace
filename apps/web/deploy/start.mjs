// The production image's command (D-091): check the environment, then start
// Next.js's standalone server. A refused setting exits with status 2 before
// anything listens.
import { webEnvironmentProblems } from "./check-env.mjs";

const problems = webEnvironmentProblems(process.env);
if (problems.length > 0) {
  console.error(`MarkX web: unsafe configuration for ${process.env.MARKX_ENV}:`);
  for (const problem of problems) console.error(`  - ${problem}`);
  process.exit(2);
}

// server.js is written by `next build` with output "standalone" next to this
// folder; it reads PORT and HOSTNAME.
await import("../server.js");
