// alles's link to Photon (spectrum-ts): iMessage in and out as one json line each.
// stdout: {"type":"ready"} once, then {"type":"message",...} per inbound message.
// stdin:  {"type":"send","space":id,"text":...} and {"type":"typing","space":id,"on":bool}.
import { createInterface } from "node:readline";

const out = (record) => process.stdout.write(JSON.stringify(record) + "\n");
const fail = (message) => { out({ type: "error", message: String(message).slice(0, 300) }); };

let Spectrum, imessage;
try {
  ({ Spectrum } = await import("spectrum-ts"));
  ({ imessage } = await import("spectrum-ts/providers/imessage"));
} catch (error) {
  fail(`spectrum-ts is not installed: ${error.message}`);
  process.exit(2);
}

const projectId = process.env.PHOTON_PROJECT_ID;
const projectSecret = process.env.PHOTON_PROJECT_SECRET;
delete process.env.PHOTON_PROJECT_SECRET;

const spaces = new Map();
const typing = new Map();

let app;
try {
  app = await Spectrum({ projectId, projectSecret, providers: [imessage.config()] });
} catch (error) {
  fail(`photon refused the connection: ${error.message}`);
  process.exit(3);
}
out({ type: "ready" });

// the reader is plain readline: alles never sends unicode line separators in these records
createInterface({ input: process.stdin }).on("line", async (line) => {
  let command;
  try { command = JSON.parse(line); } catch { return; }
  const space = spaces.get(command.space);
  if (!space) return fail(`unknown space ${command.space}`);
  try {
    if (command.type === "send") {
      const sent = await space.send(String(command.text || "").slice(0, 6000));
      out({ type: "sent", id: command.id || "", message: sent?.id || "" });
    } else if (command.type === "typing") {
      if (command.on && !typing.has(command.space)) {
        let stop;
        const done = new Promise((resolve) => { stop = resolve; });
        typing.set(command.space, stop);
        space.responding(() => done).catch(() => {});
      } else if (!command.on && typing.has(command.space)) {
        typing.get(command.space)();
        typing.delete(command.space);
      }
    }
  } catch (error) {
    fail(error.message);
  }
});

for await (const [space, message] of app.messages) {
  if (message.direction !== "inbound") continue;
  spaces.set(space.id, space);
  const content = message.content || {};
  const text = content.type === "text" ? content.text : content.type === "markdown" ? content.text || "" : "";
  out({
    type: "message",
    id: message.id,
    space: space.id,
    sender: message.sender?.id || "",
    text: String(text || "").slice(0, 8000),
    kind: content.type || "unknown",
    at: message.timestamp?.toISOString?.() || "",
  });
}
