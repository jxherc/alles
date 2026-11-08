import SwiftUI

struct HomeView: View {
    @Environment(Session.self) private var session
    @Environment(\.horizontalSizeClass) private var width
    let openAide: () -> Void

    @State private var feed: TodayFeed?
    @State private var habits: [Habit] = []
    @State private var finished: Set<String> = []
    @State private var problem: String?
    @State private var showSettings = false

    var body: some View {
        NavigationStack {
            ScrollView {
                Group {
                    if width == .regular {
                        HStack(alignment: .top, spacing: Space.xxl) {
                            VStack(alignment: .leading, spacing: Space.xxl) { nextUp; schedule }
                                .frame(maxWidth: .infinity, alignment: .topLeading)
                            VStack(alignment: .leading, spacing: Space.xxl) { tasks; habitGrid; docs }
                                .frame(maxWidth: .infinity, alignment: .topLeading)
                        }
                        .frame(maxWidth: 1100, alignment: .leading)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    } else {
                        VStack(alignment: .leading, spacing: Space.xxl) {
                            nextUp; schedule; tasks; habitGrid; docs
                        }
                    }
                }
                .pageGutter()
                .padding(.top, Space.s)
                .padding(.bottom, Space.xxl)
            }
            .refreshable { await load() }
            .pageBackground()
            .navigationTitle(greeting)
            .navigationSubtitle(Date.now.formatted(.dateTime.weekday(.wide).month(.abbreviated).day()).lowercased())
            .toolbar {
                ToolbarItem(placement: .primaryAction) {
                    Button { showSettings = true } label: {
                        Label("settings", systemImage: "gearshape")
                    }
                }
            }
            .navigationDestination(for: DocRef.self) { doc in
                DocView(path: doc.path)
            }
            .sheet(isPresented: $showSettings) { SettingsSheet() }
            .task { await load() }
        }
    }

    private var greeting: String {
        switch Calendar.current.component(.hour, from: .now) {
        case 5..<12: "good morning"
        case 12..<18: "good afternoon"
        default: "good evening"
        }
    }

    // the one big thing on the screen: what's next today
    @ViewBuilder private var nextUp: some View {
        if let problem, feed == nil {
            VStack(alignment: .leading, spacing: Space.m) {
                Text(problem).foregroundStyle(Color.danger)
                Button("try again") { Task { await load() } }.buttonStyle(.glass)
            }
        } else if let feed {
            let next = upcoming(feed.events)
            VStack(alignment: .leading, spacing: Space.s) {
                Text(next.map { isNow($0) ? "now" : "next" } ?? "today")
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(Color.inkMuted)
                if let next {
                    HStack(alignment: .firstTextBaseline, spacing: Space.m) {
                        BigClock(text: next.time.map(Day.clock) ?? "all day")
                        Text(next.title)
                            .font(.title2.weight(.medium))
                            .foregroundStyle(Color.inkSoft)
                            .lineLimit(2)
                    }
                } else {
                    Text(feed.events.isEmpty ? "a clear day" : "nothing else on")
                        .font(.system(size: 34, weight: .semibold))
                        .foregroundStyle(Color.ink)
                }
            }
        } else {
            ProgressView().frame(maxWidth: .infinity, minHeight: 120)
        }
    }

    @ViewBuilder private var schedule: some View {
        if let feed, !feed.events.isEmpty {
            VStack(alignment: .leading, spacing: Space.s) {
                SectionTitle("schedule", trailing: "\(feed.events.count)")
                VStack(spacing: 0) {
                    ForEach(feed.events) { event in
                        HStack(alignment: .firstTextBaseline, spacing: Space.l) {
                            Text(event.time.map(Day.clock) ?? "all day")
                                .font(.subheadline)
                                .monospacedDigit()
                                .foregroundStyle(Color.inkMuted)
                                .frame(width: 76, alignment: .leading)
                            Text(event.title)
                                .font(.body)
                                .foregroundStyle(isPast(event) ? Color.inkMuted : Color.ink)
                                .strikethrough(false)
                            Spacer(minLength: 0)
                        }
                        .frame(minHeight: 44)
                    }
                }
            }
        }
    }

    @ViewBuilder private var tasks: some View {
        if let feed {
            let rows = feed.tasks.overdue.map { ($0, true) } + feed.tasks.dueToday.map { ($0, false) }
            VStack(alignment: .leading, spacing: Space.s) {
                SectionTitle("due today", trailing: rows.isEmpty ? nil : "\(rows.count - finished.count)")
                if rows.isEmpty {
                    Text("nothing due")
                        .font(.subheadline)
                        .foregroundStyle(Color.inkMuted)
                        .frame(minHeight: 44)
                }
                VStack(spacing: 0) {
                    ForEach(rows, id: \.0.id) { task, late in
                        HStack(spacing: Space.xs) {
                            CheckCircle(done: finished.contains(task.id), label: task.title) {
                                Task { await complete(task) }
                            }
                            .padding(.leading, -Space.m)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(task.title)
                                    .font(.body)
                                    .foregroundStyle(finished.contains(task.id) ? Color.inkMuted : Color.ink)
                                    .strikethrough(finished.contains(task.id), color: Color.inkMuted)
                                if late {
                                    Text("overdue")
                                        .font(.footnote)
                                        .foregroundStyle(Color.danger)
                                }
                            }
                            Spacer(minLength: 0)
                        }
                        .frame(minHeight: 44)
                    }
                }
            }
        }
    }

    @ViewBuilder private var habitGrid: some View {
        if !habits.isEmpty {
            VStack(alignment: .leading, spacing: Space.s) {
                SectionTitle("habits", trailing: "\(habits.filter(\.doneToday).count) of \(habits.count)")
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 140), spacing: Space.s)], spacing: Space.s) {
                    ForEach(habits) { habit in
                        HabitChip(habit: habit) { Task { await toggle(habit) } }
                    }
                }
            }
        }
    }

    @ViewBuilder private var docs: some View {
        if let recent = feed?.recentDocs, !recent.isEmpty {
            VStack(alignment: .leading, spacing: Space.s) {
                SectionTitle("recent docs")
                VStack(spacing: 0) {
                    ForEach(recent.prefix(5)) { doc in
                        NavigationLink(value: doc) {
                            HStack(spacing: Space.m) {
                                Image(systemName: "doc.text")
                                    .foregroundStyle(Color.inkMuted)
                                    .frame(width: 22)
                                Text(doc.name)
                                    .foregroundStyle(Color.ink)
                                Spacer(minLength: 0)
                                Image(systemName: "chevron.right")
                                    .font(.footnote.weight(.semibold))
                                    .foregroundStyle(Color.inkMuted)
                            }
                            .frame(minHeight: 44)
                            .contentShape(.rect)
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
        }
    }

    // MARK: data

    private func load() async {
        let api = session.api
        do {
            async let today: TodayFeed = api.get("/api/today", query: ["date": Day.key(), "timezone": TimeZone.current.identifier])
            async let overview: HabitOverview = api.get("/api/habits/overview", query: ["date_q": Day.key()])
            let (f, h) = try await (today, overview)
            feed = f
            habits = h.habits
            finished = []
            problem = nil
        } catch {
            problem = session.handle(error)
        }
    }

    private func complete(_ task: TodayTask) async {
        guard !finished.contains(task.id) else { return }
        withAnimation(.snappy) { _ = finished.insert(task.id) }
        do {
            let _: TaskItem = try await session.api.send("PATCH", "/api/tasks/\(task.id)", TaskPatch(done: true))
        } catch {
            withAnimation { _ = finished.remove(task.id) }
            problem = session.handle(error)
        }
    }

    private func toggle(_ habit: Habit) async {
        guard let i = habits.firstIndex(of: habit) else { return }
        let now = !habit.doneToday
        withAnimation(.snappy) { habits[i].doneToday = now }
        do {
            let _: Empty = try await session.api.send("POST", "/api/habits/\(habit.id)/toggle", HabitToggle(date: Day.key(), done: now))
        } catch {
            withAnimation { habits[i].doneToday = !now }
            problem = session.handle(error)
        }
    }

    private func minutes(_ hhmm: String?) -> Int? {
        guard let hhmm, hhmm.count >= 4 else { return nil }
        let p = hhmm.split(separator: ":").compactMap { Int($0) }
        return p.count == 2 ? p[0] * 60 + p[1] : nil
    }

    private var nowMinutes: Int {
        let c = Calendar.current.dateComponents([.hour, .minute], from: .now)
        return (c.hour ?? 0) * 60 + (c.minute ?? 0)
    }

    private func isPast(_ e: TodayEvent) -> Bool {
        guard let end = minutes(e.end) ?? minutes(e.time) else { return false }
        return end <= nowMinutes
    }

    private func isNow(_ e: TodayEvent) -> Bool {
        guard let start = minutes(e.time) else { return false }
        return start <= nowMinutes && !isPast(e)
    }

    private func upcoming(_ events: [TodayEvent]) -> TodayEvent? {
        events.first { $0.allDay != true && !isPast($0) }
    }
}

/// "10:30 am": the digits carry the screen, the am/pm sits small beside them
private struct BigClock: View {
    let text: String

    var body: some View {
        let parts = text.split(separator: " ", maxSplits: 1).map(String.init)
        HStack(alignment: .firstTextBaseline, spacing: 3) {
            Text(parts.first ?? text)
                .font(.system(size: 44, weight: .semibold))
                .monospacedDigit()
            if parts.count == 2 {
                Text(parts[1])
                    .font(.title3.weight(.medium))
            }
        }
        .foregroundStyle(Color.ink)
    }
}

/// one habit for today: tap to mark it. the fill is the state, the name stays readable
private struct HabitChip: View {
    let habit: Habit
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: Space.s) {
                Image(systemName: habit.doneToday ? "checkmark.circle.fill" : "circle")
                    .font(.system(size: 20))
                    .foregroundStyle(habit.doneToday ? Color.active : Color.inkMuted)
                    .contentTransition(.symbolEffect(.replace))
                Text(habit.name)
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(Color.ink)
                    .lineLimit(1)
                Spacer(minLength: 0)
                if habit.streak > 1 {
                    Text("\(habit.streak)")
                        .font(.footnote.monospacedDigit())
                        .foregroundStyle(Color.inkMuted)
                }
            }
            .padding(.horizontal, Space.m)
            .frame(minHeight: 48)
            .background(Color.ink.opacity(habit.doneToday ? 0.10 : 0.05), in: .rect(cornerRadius: 14))
            .contentShape(.rect)
        }
        .buttonStyle(.plain)
        .sensoryFeedback(.success, trigger: habit.doneToday) { _, now in now }
        .accessibilityLabel(habit.name)
        .accessibilityValue(habit.doneToday ? "done today" : "not done today")
    }
}

struct SettingsSheet: View {
    @Environment(Session.self) private var session
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                Section {
                    LabeledContent("address", value: session.server?.absoluteString ?? "")
                        .textSelection(.enabled)
                    LabeledContent("sign in", value: session.token == nil ? "no password" : "this device's token")
                }
                Section {
                    Button("sign out", role: .destructive) {
                        dismiss()
                        session.signOut()
                    }
                } footer: {
                    Text("the token stays listed in alles settings › tokens until you remove it there.")
                }
            }
            .navigationTitle("settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("done") { dismiss() }
                }
            }
        }
        .presentationDetents([.medium, .large])
    }
}
