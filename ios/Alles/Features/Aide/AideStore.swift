import SwiftUI

/// the open conversation and its live reply. it lives above the tabs, so the reply keeps
/// streaming (and shows in the tab bar's accessory) when you leave aide.
@Observable
final class AideStore {
    var sessions: [ChatSession] = []
    var current: ChatSession?
    var messages: [ChatMessage] = []
    /// a reply is streaming
    var replying = false
    /// sent, no words back yet: the typing dots
    var waiting = false
    /// the owner message the server took (the turn started): it shows "read"
    var readID: String?
    var problem: String?

    private var turnToken: String?
    private var stream: Task<Void, Never>?

    var liveText: String {
        guard replying, let last = messages.last, last.role == "assistant" else { return "" }
        return last.content
    }

    func loadSessions(_ api: API) async {
        do {
            let groups: SessionGroups = try await api.get("/api/sessions")
            sessions = groups.today + groups.yesterday + groups.earlier
        } catch {
            problem = error.localizedDescription
        }
    }

    func open(_ chat: ChatSession?, _ api: API) async {
        guard !replying || chat?.id == current?.id else { return }
        do {
            let target: ChatSession
            if let chat {
                target = chat
            } else {
                target = try await api.get("/api/aide/conversation")
            }
            let history: ChatHistory = try await api.get("/api/sessions/\(target.id)/history")
            current = history.session
            messages = history.messages.filter { $0.role == "user" || $0.role == "assistant" }
            readID = messages.last(where: { $0.role == "user" })?.id
            problem = nil
        } catch {
            problem = error.localizedDescription
        }
    }

    func newChat(_ api: API) async {
        do {
            let made: ChatSession = try await api.send("POST", "/api/sessions", NewSession(name: "new chat"))
            current = made
            messages = []
            readID = nil
            await loadSessions(api)
        } catch {
            problem = error.localizedDescription
        }
    }

    func send(_ text: String, _ api: API) {
        let text = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !replying, let chat = current else { return }
        let token = UUID().uuidString
        let mine = ChatMessage(id: "local-\(token)", role: "user", content: text, timestamp: nil)
        let reply = ChatMessage(id: "reply-\(token)", role: "assistant", content: "", timestamp: nil)
        messages.append(mine)
        turnToken = token
        replying = true
        waiting = true
        problem = nil

        stream = Task { [weak self] in
            guard let self else { return }
            var replyIndex: Int?
            do {
                let events = try api.events("/api/chat", ChatSend(sessionId: chat.id, message: text, turnToken: token), as: ChatEvent.self)
                for try await event in events {
                    if let turn = event.turn {
                        if let i = messages.firstIndex(where: { $0.id == mine.id }), let id = turn.userId {
                            messages[i] = ChatMessage(id: id, role: "user", content: text, timestamp: nil)
                            readID = id
                        } else {
                            readID = mine.id
                        }
                    }
                    if let piece = event.delta, !piece.isEmpty {
                        if replyIndex == nil {
                            messages.append(reply)
                            replyIndex = messages.count - 1
                            waiting = false
                        }
                        if let i = replyIndex { messages[i].content += piece }
                    }
                    if let err = event.error, !err.isEmpty { problem = err }
                    if let saved = event.savedMessage, let content = saved.content, let i = replyIndex {
                        messages[i].content = content
                    }
                }
            } catch is CancellationError {
            } catch {
                problem = error.localizedDescription
            }
            waiting = false
            replying = false
            turnToken = nil
            if let i = replyIndex, messages[i].content.isEmpty { messages.remove(at: i) }
            await loadSessions(api)
        }
    }

    func stop(_ api: API) {
        guard let chat = current else { return }
        let token = turnToken
        Task {
            _ = try? await api.send("POST", "/api/chat/stop/\(chat.id)", ChatStop(turnToken: token ?? "")) as OK
            // the server ends the stream itself; cut it if it doesn't within a moment
            try? await Task.sleep(for: .milliseconds(800))
            stream?.cancel()
        }
    }
}
