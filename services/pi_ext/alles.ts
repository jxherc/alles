// alles's extension for pi: hidden secrets, a guard on risky commands, and web search.
// it runs inside pi; alles passes its settings through env vars when it starts pi.

const PLACEHOLDER = /\{\{secret:([A-Za-z0-9_]+)\}\}/g;

// commands that can't be undone or reach past the project; pi asks the owner first
const RISKY = [
  /\brm\s+-[a-z]*r[a-z]*f?\b[^|;&]*(\s\/(\s|$)|\s~|\s\$HOME|\s\.\.?(\s|$)|\s\*)/,
  /\bgit\s+push\b[^|;&]*(--force|-f\b|--force-with-lease)/,
  /\bgit\s+(reset\s+--hard|clean\s+-[a-z]*f|checkout\s+--\s|restore\s+--source)/,
  /\bgit\s+(branch|tag)\s+-D\b/,
  /\b(mkfs|fdisk|diskutil\s+erase|shutdown|reboot|halt)\b/,
  /\bdd\s+[^|;&]*of=\/dev\//,
  /\bchmod\s+-R\s+[0-7]*7\s+\//,
  /\b(drop\s+(table|database)|truncate\s+table)\b/i,
  /:\(\)\s*\{\s*:\|:&\s*\};:/,
  /\b(curl|wget)\b[^|]*\|\s*(sudo\s+)?(ba)?sh\b/,
  /\bsudo\b/,
];

export default function (pi: any) {
  const secrets: Record<string, string> = {};
  const load = (raw: string | undefined) => {
    if (!raw) return;
    try { Object.assign(secrets, JSON.parse(Buffer.from(raw, "base64").toString("utf8"))); } catch { /* bad input is ignored */ }
  };
  load(process.env.PI_ALLES_SECRETS);
  // the env is gone before any tool runs, so a command can't read every secret at once
  delete process.env.PI_ALLES_SECRETS;
  const bridgeUrl = process.env.PI_ALLES_BRIDGE_URL || "";
  const bridgeToken = process.env.PI_ALLES_BRIDGE_TOKEN || "";
  const guard = process.env.PI_ALLES_GUARD !== "off";
  delete process.env.PI_ALLES_BRIDGE_TOKEN;
  // alles's own tools (docs, tasks, calendar, memory...) and whether a change needs the owner's ok
  let appTools: any[] = [];
  try { appTools = JSON.parse(Buffer.from(process.env.PI_ALLES_TOOLS || "", "base64").toString("utf8")).tools || []; } catch { appTools = []; }
  const asks = process.env.PI_ALLES_WRITES !== "allow";
  delete process.env.PI_ALLES_TOOLS;
  const changing = new Map(appTools.filter((t) => t.changes).map((t) => [t.name, t]));
  let privatePaths: string[] = [];
  try { privatePaths = JSON.parse(Buffer.from(process.env.PI_ALLES_PRIVATE || "", "base64").toString("utf8")).paths || []; } catch { privatePaths = []; }
  delete process.env.PI_ALLES_PRIVATE;
  // a call that names alles's data, its database, ssh keys or shell history is refused outright
  const PRIVATE_NAMES = /(^|[\s'"\/=])(aide\.db|alles\.db|\.bash_history|\.zsh_history|id_rsa|id_ed25519)\b/;
  const touchesPrivate = (input: any) => {
    const flat = JSON.stringify(input ?? {});
    const home = process.env.HOME || "";
    return PRIVATE_NAMES.test(flat) || privatePaths.some((p) => p && (flat.includes(p) || (home && p.startsWith(home) && flat.includes("~" + p.slice(home.length)))));
  };
  const allowed = new Set<string>();

  const reveal = (value: any): any => {
    if (typeof value === "string") return value.replace(PLACEHOLDER, (whole, name) => secrets[name] ?? whole);
    if (Array.isArray(value)) return value.map(reveal);
    if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, reveal(v)]));
    return value;
  };
  const hide = (text: string) => {
    let out = text;
    for (const [name, value] of Object.entries(secrets)) if (value) out = out.split(value).join(`{{secret:${name}}}`);
    return out;
  };

  // alles adds secrets typed while pi is already running; this never reaches the model or the session
  pi.registerCommand("alles-secret", {
    description: "internal: alles hands over hidden secrets",
    handler: async (args: string) => load(args.trim()),
  });

  pi.on("tool_call", async (event: any, ctx: any) => {
    if (!String(event.toolName).startsWith("alles_") && touchesPrivate(event.input)) {
      return { block: true, reason: "that is alles's private data (its database, keys or history). use the alles_ tools for docs, tasks, calendar and memory instead." };
    }
    const app = changing.get(event.toolName);
    if (app && asks) {
      const what = JSON.stringify(event.input ?? {}).slice(0, 400);
      const ok = await ctx.ui.confirm(`Let pi ${String(app.tool).replace(/_/g, " ")}?`, what);
      if (!ok) return { block: true, reason: "the owner said no to this change; ask what they want instead" };
      allowed.add(event.toolCallId);
    }
    const command = event.toolName === "bash" ? String(event.input?.command ?? "") : "";
    if (guard && command && RISKY.some((rule) => rule.test(command))) {
      const ok = await ctx.ui.confirm("Run a risky command?", command.slice(0, 500));
      if (!ok) return { block: true, reason: "the owner said no to this command; find a safer way or ask" };
    }
    if (event.input && JSON.stringify(event.input).includes("{{secret:")) {
      Object.assign(event.input, reveal(event.input));
    }
  });

  pi.on("tool_result", async (event: any) => {
    if (!Object.keys(secrets).length) return;
    const content = (event.content || []).map((block: any) =>
      block?.type === "text" && typeof block.text === "string" ? { ...block, text: hide(block.text) } : block,
    );
    return { content };
  });

  if (!bridgeUrl || !bridgeToken) return;
  const call = async (path: string, body: object, signal?: AbortSignal) => {
    const response = await fetch(`${bridgeUrl}${path}`, {
      method: "POST",
      headers: { "content-type": "application/json", authorization: `Bearer ${bridgeToken}` },
      body: JSON.stringify(body),
      signal,
    });
    const data: any = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || data.message || `alles said ${response.status}`);
    return data;
  };
  const text = (value: string) => ({ content: [{ type: "text", text: hide(value) }], details: {} });

  pi.registerTool({
    name: "web_search",
    label: "web search",
    description: "Search the current web through alles's search engines. Use for docs, error messages, releases and anything that may have changed.",
    promptSnippet: "web_search: search the current web",
    parameters: {
      type: "object",
      properties: { query: { type: "string" }, count: { type: "number", description: "results, 1-10" } },
      required: ["query"],
    },
    async execute(_id: string, params: any, signal?: AbortSignal) {
      const data = await call("/search", { query: params.query, count: params.count ?? 6 }, signal);
      const rows = (data.results || []).map((r: any, i: number) => `${i + 1}. ${r.title}\n${r.url}\n${r.snippet || ""}`);
      return text(rows.join("\n\n") || "no results");
    },
  });

  for (const tool of appTools) {
    pi.registerTool({
      name: tool.name,
      label: String(tool.tool).replace(/_/g, " "),
      description: `${tool.description} (an alles tool${tool.changes ? " that changes the owner's data" : ""})`,
      promptSnippet: `${tool.name}: ${String(tool.description).split(".")[0]}`,
      parameters: tool.parameters,
      async execute(id: string, params: any, signal?: AbortSignal) {
        const data = await call("/tool", { name: tool.name, args: reveal(params ?? {}), confirmed: allowed.delete(id) }, signal);
        if (data.error) throw new Error(data.output || `${tool.tool} failed`);
        return text(data.output || "done");
      },
    });
  }

  pi.registerTool({
    name: "web_fetch",
    label: "web fetch",
    description: "Read one web page as plain text through alles's safe fetcher.",
    promptSnippet: "web_fetch: read a web page",
    parameters: { type: "object", properties: { url: { type: "string" } }, required: ["url"] },
    async execute(_id: string, params: any, signal?: AbortSignal) {
      const data = await call("/fetch", { url: params.url }, signal);
      return text(data.content || "the page had no readable text");
    },
  });
}
