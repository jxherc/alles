import Foundation

// field names copied from the routes (routes/today.py, tasks.py, habits.py, sessions.py, chat.py,
// vault_md.py, andromeda.py)

nonisolated struct TodayFeed: Decodable {
    let date: String
    let events: [TodayEvent]
    let tasks: TodayTasks
    let recentDocs: [DocRef]?

    enum CodingKeys: String, CodingKey {
        case date, events, tasks
        case recentDocs = "recent_docs"
    }
}

nonisolated struct TodayEvent: Decodable, Identifiable, Hashable {
    let id: String
    let title: String
    let time: String?
    let end: String?
    let allDay: Bool?

    enum CodingKeys: String, CodingKey {
        case id, title, time, end
        case allDay = "all_day"
    }
}

nonisolated struct TodayTasks: Decodable {
    let overdue: [TodayTask]
    let dueToday: [TodayTask]
    let openCount: Int

    enum CodingKeys: String, CodingKey {
        case overdue
        case dueToday = "due_today"
        case openCount = "open_count"
    }
}

nonisolated struct TodayTask: Decodable, Identifiable, Hashable {
    let id: String
    let title: String
    let due: String?
    let priority: Int?
}

nonisolated struct DocRef: Decodable, Identifiable, Hashable {
    let path: String
    let name: String
    var id: String { path }
}

nonisolated struct TaskItem: Codable, Identifiable, Hashable {
    let id: String
    var title: String
    var done: Bool
    var priority: Int
    var dueDate: String?
    var dueTime: String?
    var overdue: Bool
    var notes: String?

    enum CodingKeys: String, CodingKey {
        case id, title, done, priority, overdue, notes
        case dueDate = "due_date"
        case dueTime = "due_time"
    }
}

nonisolated struct NewTask: Encodable {
    let title: String
    let nl: Bool
    var dueDate: String?

    enum CodingKeys: String, CodingKey {
        case title, nl
        case dueDate = "due_date"
    }
}

nonisolated struct TaskPatch: Encodable { let done: Bool }

nonisolated struct Agenda: Decodable {
    let days: [AgendaDay]
}

nonisolated struct AgendaDay: Decodable, Identifiable {
    let date: String
    let events: [CalendarEvent]
    /// the agenda sends the short task shape (id, title, due, priority)
    let tasks: [TodayTask]
    var id: String { date }
}

nonisolated struct CalendarEvent: Decodable, Identifiable, Hashable {
    let id: String
    let title: String
    let location: String?
    let startDt: String
    let endDt: String?
    let allDay: Bool

    enum CodingKeys: String, CodingKey {
        case id, title, location
        case startDt = "start_dt"
        case endDt = "end_dt"
        case allDay = "all_day"
    }

    var start: Date? { Day.local(startDt) }
    var finish: Date? { endDt.flatMap(Day.local) }
}

nonisolated struct HabitOverview: Decodable { let habits: [Habit] }

nonisolated struct Habit: Decodable, Identifiable, Hashable {
    let id: String
    let name: String
    let kind: String
    var doneToday: Bool
    let streak: Int

    enum CodingKeys: String, CodingKey {
        case id, name, kind, streak
        case doneToday = "done_today"
    }
}

nonisolated struct HabitToggle: Encodable {
    let date: String
    let done: Bool
}

nonisolated struct SessionGroups: Decodable {
    let today: [ChatSession]
    let yesterday: [ChatSession]
    let earlier: [ChatSession]
}

nonisolated struct ChatSession: Decodable, Identifiable, Hashable {
    let id: String
    let name: String
    let primary: Bool?
    let messageCount: Int?
    let lastMessageAt: String?

    enum CodingKeys: String, CodingKey {
        case id, name, primary
        case messageCount = "message_count"
        case lastMessageAt = "last_message_at"
    }
}

nonisolated struct NewSession: Encodable { let name: String }

nonisolated struct ChatHistory: Decodable {
    let session: ChatSession
    let messages: [ChatMessage]
    let answering: Bool?
}

nonisolated struct ChatMessage: Decodable, Identifiable, Hashable {
    let id: String
    let role: String
    var content: String
    let timestamp: String?
}

nonisolated struct ChatSend: Encodable {
    let sessionId: String
    let message: String
    let turnToken: String

    enum CodingKeys: String, CodingKey {
        case message
        case sessionId = "session_id"
        case turnToken = "turn_token"
    }
}

nonisolated struct ChatStop: Encodable {
    let turnToken: String
    enum CodingKeys: String, CodingKey { case turnToken = "turn_token" }
}

/// one sse chunk from POST /api/chat. agent-mode extras (tool_start and so on) are ignored:
/// the chat stays a chat
nonisolated struct ChatEvent: Decodable, Sendable {
    struct Turn: Decodable, Sendable {
        let userId: String?
        let assistantId: String?
        enum CodingKeys: String, CodingKey {
            case userId = "user_id"
            case assistantId = "assistant_id"
        }
    }

    struct Saved: Decodable, Sendable {
        let id: String?
        let content: String?
    }

    let turn: Turn?
    let delta: String?
    let error: String?
    let done: Bool?
    let savedMessage: Saved?

    enum CodingKeys: String, CodingKey {
        case turn, delta, error, done
        case savedMessage = "saved_message"
    }
}

nonisolated struct DocTree: Decodable {
    let items: [DocNode]
}

nonisolated struct DocNode: Decodable, Identifiable, Hashable {
    let type: String
    let name: String
    let path: String
    let mtime: Double?
    let children: [DocNode]?
    var id: String { path }
    var isFolder: Bool { type == "dir" }
}

nonisolated struct DocFile: Decodable {
    let path: String
    let content: String
    let hash: String?
    let editable: Bool?
}

nonisolated struct DocSave: Encodable {
    let path: String
    let content: String
    let expectedHash: String?

    enum CodingKeys: String, CodingKey {
        case path, content
        case expectedHash = "expected_hash"
    }
}

nonisolated struct DocSaved: Decodable {
    let ok: Bool?
    let hash: String?
}

nonisolated struct SearchRequest: Encodable {
    let query: String
    let overview: Bool
}

nonisolated struct SearchResponse: Decodable {
    let query: String
    let correctedFrom: String?
    let status: String?
    let error: String?
    let results: [SearchResult]

    enum CodingKeys: String, CodingKey {
        case query, status, error, results
        case correctedFrom = "corrected_from"
    }
}

nonisolated struct SearchResult: Decodable, Identifiable, Hashable {
    let rank: Int?
    let title: String
    let url: String
    let snippet: String?
    let publisher: String?
    var id: String { url }
}
