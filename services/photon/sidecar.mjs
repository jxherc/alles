// alles's link to Photon (spectrum-ts): iMessage in and out as one json line each.
// stdout: {"type":"ready"} once, then {"type":"message",...} per inbound message.
// stdin:  {"type":"send","space":id,"text":...,"id":n,"resolve":bool}, {"type":"typing","space":id,"on":bool} and
//         {"type":"read","space":id,"id":message id}.
//
// presence follows hermes (v0.22.2+canary 20acba0, plugins/platforms/photon/sidecar/index.mjs, spectrum-ts 12.7.0
// there, 12.11.0 here; both have `typing` and `message.read()`):
// - typing is the documented `typing("start" | "stop")` content builder sent with `space.send`
//   (hermes index.mjs:1224-1231). the sidecar holds no timer: the bubble expires after about 5s,
//   so alles sends "start" again every few seconds from services/channel_runs.py (hermes does the same
//   from gateway/platforms/base.py:3350 `_keep_typing`, 2s ticks, 5s cooldown per chat in photon/adapter.py:81).
// - read receipts are `message.read()` once the message has reached alles (hermes index.mjs:619-640).
//   alles asks for it after the owner check, so a stranger who texts the shared line gets no receipt.
import { createInterface } from "node:readline";

const out = (record) => process.stdout.write(JSON.stringify(record) + "\n");
// `id` ties an error to the send command that caused it. shared and free-tier Photon lines refuse a
// first message with "Target not allowed for this project"; hermes classes it the same way
// (plugins/platforms/photon/sidecar/index.mjs:866-873).
const fail = (message, id) => {
  const text = String(message);
  const record = { type: "error", message: text.slice(0, 300) };
  if (id) record.id = id;
  if (/target not allowed/i.test(text)) record.class = "target_not_allowed";
  out(record);
};

let Spectrum, imessage, spectrumTyping;
try {
  ({ Spectrum, typing: spectrumTyping } = await import("spectrum-ts"));
  ({ imessage } = await import("spectrum-ts/providers/imessage"));
} catch (error) {
  fail(`spectrum-ts is not installed: ${error.message}`);
  process.exit(2);
}

const projectId = process.env.PHOTON_PROJECT_ID;
const projectSecret = process.env.PHOTON_PROJECT_SECRET;
delete process.env.PHOTON_PROJECT_SECRET;

const spaces = new Map();
// recent inbound messages by id, so a read command can find the one to mark
const recent = new Map();

let app;
try {
  app = await Spectrum({ projectId, projectSecret, providers: [imessage.config()] });
} catch (error) {
  fail(`photon refused the connection: ${error.message}`);
  process.exit(3);
}
out({ type: "ready" });

// a bare phone number is a DM: space.create(phone); any other id comes back through space.get.
// copied from hermes resolveSpace (plugins/platforms/photon/sidecar/index.mjs:962-1005); `any;-;+1...`
// is how Photon names a DM chat (same file, DM_CHAT_GUID_RE, line 93).
const PHONE = /^\+\d{6,}$/;
const DM_GUID = /^any;-;(\+\d{6,})$/;
async function resolveSpace(id) {
  const known = spaces.get(id);
  if (known) return known;
  const im = imessage(app);
  const phone = PHONE.test(id) ? id : (id.match(DM_GUID) || [])[1];
  let space = null;
  if (phone) space = await im.space.create(phone).catch(() => null);
  if (!space) space = await im.space.get(id).catch(() => null);
  if (!space) throw new Error(`unable to resolve space id ${id}`);
  spaces.set(id, space);
  spaces.set(space.id, space);
  return space;
}

// the reader is plain readline: alles never sends unicode line separators in these records
createInterface({ input: process.stdin }).on("line", async (line) => {
  let command;
  try { command = JSON.parse(line); } catch { return; }
  try {
    // a send with `resolve` may name a space this process has not seen since it started
    // (alles texting first, after a restart); the others only act on live inbound spaces
    const space = command.type === "send" && command.resolve
      ? await resolveSpace(command.space)
      : spaces.get(command.space);
    if (!space) return fail(`unknown space ${command.space}`, command.id);
    if (command.type === "send") {
      const sent = await space.send(String(command.text || "").slice(0, 6000));
      out({ type: "sent", id: command.id || "", space: space.id, message: sent?.id || "" });
    } else if (command.type === "typing") {
      // presence is polish, never an error the owner has to see (hermes treats it the same way)
      await space.send(spectrumTyping(command.on ? "start" : "stop")).catch(() => {});
    } else if (command.type === "read") {
      const message = recent.get(command.id);
      if (message && typeof message.read === "function") await message.read().catch(() => {});
    }
  } catch (error) {
    fail(error.message, command.id);
  }
});

for await (const [space, message] of app.messages) {
  if (message.direction !== "inbound") continue;
  spaces.set(space.id, space);
  recent.set(message.id, message);
  if (recent.size > 200) recent.delete(recent.keys().next().value);
  let content = message.content || {};
  if (content.type === "effect" && content.content) content = content.content; // text sent with an effect
  // typing bubbles, reactions, renames... aren't messages
  if (!["text", "markdown", "richlink", "attachment", "voice", "contact", "poll"].includes(content.type)) continue;
  const text = content.type === "richlink" ? content.url || "" : ["text", "markdown"].includes(content.type) ? content.text || "" : "";
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
