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
