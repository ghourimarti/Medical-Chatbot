import { forward } from "@/lib/proxy";

/** Never prerender or cache: every one of these is per-session and, for the stream, live. */
export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export const fetchCache = "force-no-store";

type Ctx = { params: Promise<{ path: string[] }> };

async function handle(request: Request, ctx: Ctx): Promise<Response> {
  const { path } = await ctx.params;
  return forward(request, path.join("/"));
}

export const GET = handle;
export const POST = handle;
