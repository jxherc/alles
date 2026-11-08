import SwiftUI

/// plan's 3 tabs from decision 0064: today (the next seven days), calendar, tasks.
/// 3 options, so a pill switch (0050), here the system's segmented control.
struct PlanView: View {
    @Environment(Session.self) private var session
    @State private var part: Part = .today
    @State private var days: [AgendaDay] = []
    @State private var tasks: [TaskItem] = []
    @State private var finished: Set<String> = []
    @State private var picked = Calendar.current.startOfDay(for: .now)
    @State private var problem: String?
    @State private var adding = false

    enum Part: String, CaseIterable { case today, calendar, tasks }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: Space.xl) {
                    Picker("view", selection: $part) {
                        ForEach(Part.allCases, id: \.self) { Text($0.rawValue).tag($0) }
                    }
                    .pickerStyle(.segmented)
                    .frame(maxWidth: 420)

                    if let problem {
                        Text(problem).font(.subheadline).foregroundStyle(Color.danger)
                    }

                    switch part {
                    case .today: agenda
                    case .calendar: calendar
                    case .tasks: taskList
                    }
                }
                .readableWidth(760)
                .pageGutter()
                .padding(.bottom, 96)
            }
            .refreshable { await load() }
            .pageBackground()
            .navigationTitle("plan")
            .overlay(alignment: .bottomTrailing) {
                GlassCircleButton(systemImage: "plus", label: "add a task", prominent: true) { adding = true }
                    .padding(Space.l)
            }
            .sheet(isPresented: $adding) {
                AddTaskSheet(day: part == .calendar ? picked : nil) { await load() }
            }
            .task { await load() }
        }
    }

    // MARK: today: the next seven days

    private var agenda: some View {
        VStack(alignment: .leading, spacing: Space.xl) {
            let week = days.prefix(7).filter { !$0.events.isEmpty || !$0.tasks.isEmpty }
            if week.isEmpty && problem == nil {
                QuietNote(text: "nothing in the next seven days")
            }
            ForEach(week) { day in
                VStack(alignment: .leading, spacing: Space.s) {
                    SectionTitle(dayTitle(day.date))
                    dayRows(day)
                }
            }
        }
    }

    // MARK: calendar: pick a day on the strip

    private var calendar: some View {
        VStack(alignment: .leading, spacing: Space.l) {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: Space.s) {
                    ForEach(0..<21, id: \.self) { offset in
                        let date = Calendar.current.date(byAdding: .day, value: offset, to: Calendar.current.startOfDay(for: .now))!
                        DayPill(date: date, picked: Calendar.current.isDate(date, inSameDayAs: picked), busy: hasItems(date)) {
                            withAnimation(.snappy) { picked = date }
                        }
                    }
                }
                .padding(.vertical, 2)
            }
            .scrollClipDisabled()

            let day = days.first { $0.date == Day.key(picked) }
            SectionTitle(dayTitle(Day.key(picked)))
            if let day, !day.events.isEmpty || !day.tasks.isEmpty {
                dayRows(day)
            } else {
                QuietNote(text: "nothing planned")
            }
        }
    }

    // MARK: tasks

    private var taskList: some View {
        let open = tasks
        let groups: [(String, [TaskItem])] = [
            ("overdue", open.filter(\.overdue)),
            ("today", open.filter { $0.dueDate == Day.key() && !$0.overdue }),
            ("upcoming", open.filter { ($0.dueDate ?? "") > Day.key() }),
            ("no date", open.filter { $0.dueDate == nil }),
        ]
        return VStack(alignment: .leading, spacing: Space.xl) {
            if open.isEmpty && problem == nil { QuietNote(text: "no open tasks") }
            ForEach(groups.filter { !$0.1.isEmpty }, id: \.0) { title, items in
                VStack(alignment: .leading, spacing: Space.s) {
                    SectionTitle(title, trailing: "\(items.count)")
                    VStack(spacing: 0) {
                        ForEach(items) { task in taskRow(task) }
                    }
                }
            }
        }
    }

    // MARK: rows

    private func dayRows(_ day: AgendaDay) -> some View {
        VStack(spacing: 0) {
            ForEach(day.events.sorted { $0.startDt < $1.startDt }) { event in
                HStack(alignment: .firstTextBaseline, spacing: Space.l) {
                    Text(event.allDay ? "all day" : (event.start?.formatted(date: .omitted, time: .shortened).lowercased() ?? ""))
                        .font(.subheadline)
                        .monospacedDigit()
                        .foregroundStyle(Color.inkMuted)
                        .frame(width: 76, alignment: .leading)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(event.title).foregroundStyle(Color.ink)
                        if let place = event.location, !place.isEmpty {
                            Text(place).font(.footnote).foregroundStyle(Color.inkMuted)
                        }
                    }
                    Spacer(minLength: 0)
                }
                .padding(.vertical, Space.s)
                .frame(minHeight: 44)
            }
            ForEach(day.tasks) { task in
                taskRow(id: task.id, title: task.title, priority: task.priority ?? 0, due: nil, overdue: false)
            }
        }
    }

    private func taskRow(_ task: TaskItem) -> some View {
        taskRow(id: task.id, title: task.title, priority: task.priority, due: task.dueDate, overdue: task.overdue)
    }

    /// one row for both task shapes; done state is kept here (the agenda sends no `done`)
    private func taskRow(id: String, title: String, priority: Int, due: String?, overdue: Bool) -> some View {
        let done = finished.contains(id)
        return HStack(spacing: Space.xs) {
            CheckCircle(done: done, label: title) {
                Task { await toggle(id) }
            }
            .padding(.leading, -Space.m)
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .foregroundStyle(done ? Color.inkMuted : Color.ink)
                    .strikethrough(done, color: Color.inkMuted)
                if let due, due != Day.key() {
                    Text(dueText(due))
                        .font(.footnote)
                        .foregroundStyle(overdue ? Color.danger : Color.inkMuted)
                }
            }
            Spacer(minLength: 0)
            if priority >= 3 {
                Image(systemName: "exclamationmark")
                    .font(.footnote.weight(.bold))
                    .foregroundStyle(Color.danger)
                    .accessibilityLabel("high priority")
            }
        }
        .frame(minHeight: 44)
    }

    // MARK: data

    private func load() async {
        let api = session.api
        do {
            async let agenda: Agenda = api.get("/api/calendar/agenda", query: ["days": "21"])
            async let open: [TaskItem] = api.get("/api/tasks")
            let (a, t) = try await (agenda, open)
            days = a.days
            tasks = t
            finished = []
            problem = nil
        } catch {
            problem = session.handle(error)
        }
    }

    private func toggle(_ id: String) async {
        let now = !finished.contains(id)
        mark(id, now)
        do {
            let _: TaskItem = try await session.api.send("PATCH", "/api/tasks/\(id)", TaskPatch(done: now))
        } catch {
            mark(id, !now)
            problem = session.handle(error)
        }
    }

    private func mark(_ id: String, _ done: Bool) {
        withAnimation(.snappy) {
            if done { finished.insert(id) } else { finished.remove(id) }
        }
    }

    private func hasItems(_ date: Date) -> Bool {
        guard let day = days.first(where: { $0.date == Day.key(date) }) else { return false }
        return !day.events.isEmpty || !day.tasks.isEmpty
    }

    private func dayTitle(_ key: String) -> String {
        guard let date = Day.date(key) else { return key }
        if Calendar.current.isDateInToday(date) { return "today" }
        if Calendar.current.isDateInTomorrow(date) { return "tomorrow" }
        return date.formatted(.dateTime.weekday(.wide).month(.abbreviated).day()).lowercased()
    }

    private func dueText(_ key: String) -> String {
        guard let date = Day.date(key) else { return key }
        if Calendar.current.isDateInTomorrow(date) { return "tomorrow" }
        if Calendar.current.isDateInYesterday(date) { return "yesterday" }
        return date.formatted(.dateTime.month(.abbreviated).day()).lowercased()
    }
}

/// one day on the calendar strip. the picked day takes the raised fill and weight, not colour
private struct DayPill: View {
    let date: Date
    let picked: Bool
    let busy: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(spacing: Space.xs) {
                Text(date.formatted(.dateTime.weekday(.abbreviated)).lowercased())
                    .font(.caption)
                    .foregroundStyle(Color.inkMuted)
                Text(date.formatted(.dateTime.day()))
                    .font(.title3.weight(picked ? .semibold : .regular))
                    .monospacedDigit()
                    .foregroundStyle(Calendar.current.isDateInToday(date) ? Color.active : Color.ink)
                Circle()
                    .fill(busy ? Color.inkMuted : .clear)
                    .frame(width: 4, height: 4)
            }
            .frame(width: 52, height: 72)
            .background(picked ? Color.ink.opacity(0.10) : .clear, in: .rect(cornerRadius: 16))
            .contentShape(.rect)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(date.formatted(date: .complete, time: .omitted))
        .accessibilityAddTraits(picked ? .isSelected : [])
    }
}

/// one line, alles reads the date out of it ("essay friday 3pm")
private struct AddTaskSheet: View {
    @Environment(Session.self) private var session
    @Environment(\.dismiss) private var dismiss
    let day: Date?
    let added: () async -> Void
    @State private var title = ""
    @State private var busy = false
    @State private var problem: String?
    @FocusState private var focused: Bool

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: Space.m) {
                TextField("essay draft friday 3pm", text: $title, axis: .vertical)
                    .font(.title3)
                    .focused($focused)
                    .submitLabel(.done)
                    .onSubmit { Task { await save() } }
                if let problem {
                    Text(problem).font(.subheadline).foregroundStyle(Color.danger)
                }
                Spacer()
            }
            .padding(Space.l)
            .navigationTitle(day.map { "add to " + $0.formatted(.dateTime.weekday(.wide)).lowercased() } ?? "add a task")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("cancel", role: .cancel) { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("add") { Task { await save() } }
                        .disabled(title.trimmingCharacters(in: .whitespaces).isEmpty || busy)
                }
            }
            .onAppear { focused = true }
        }
        .presentationDetents([.height(220), .medium])
    }

    private func save() async {
        let text = title.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !busy else { return }
        busy = true
        defer { busy = false }
        do {
            let _: TaskItem = try await session.api.send(
                "POST", "/api/tasks", NewTask(title: text, nl: true, dueDate: day.map { Day.key($0) })
            )
            await added()
            dismiss()
        } catch {
            problem = session.handle(error)
        }
    }
}
