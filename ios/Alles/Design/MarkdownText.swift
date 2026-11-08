import SwiftUI

/// enough markdown for aide replies and docs: headings, bullets, numbered lists, quotes,
/// code fences and inline styles. anything else shows as plain text.
struct MarkdownText: View {
    let source: String
    var bodyFont: Font = .body

    var body: some View {
        VStack(alignment: .leading, spacing: Space.m) {
            ForEach(Array(Self.blocks(source).enumerated()), id: \.offset) { _, block in
                view(for: block)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    @ViewBuilder
    private func view(for block: Block) -> some View {
        switch block {
        case .heading(let level, let text):
            Text(Self.inline(text))
                .font(level == 1 ? .title2.weight(.semibold) : level == 2 ? .title3.weight(.semibold) : .headline)
                .foregroundStyle(Color.ink)
                .padding(.top, level == 1 ? 0 : Space.xs)
        case .paragraph(let text):
            Text(Self.inline(text))
                .font(bodyFont)
                .foregroundStyle(Color.ink)
                .fixedSize(horizontal: false, vertical: true)
        case .list(let items, let numbered):
            VStack(alignment: .leading, spacing: Space.s) {
                ForEach(Array(items.enumerated()), id: \.offset) { i, item in
                    HStack(alignment: .firstTextBaseline, spacing: Space.s) {
                        Text(numbered ? "\(i + 1)." : "•")
                            .font(bodyFont.monospacedDigit())
                            .foregroundStyle(Color.inkMuted)
                            .frame(minWidth: 14, alignment: .trailing)
                        Text(Self.inline(item))
                            .font(bodyFont)
                            .foregroundStyle(Color.ink)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
        case .quote(let text):
            Text(Self.inline(text))
                .font(bodyFont)
                .foregroundStyle(Color.inkSoft)
                .padding(.leading, Space.m)
                .overlay(alignment: .leading) {
                    Capsule().fill(Color.line).frame(width: 3)
                }
        case .code(let text):
            ScrollView(.horizontal, showsIndicators: false) {
                Text(text)
                    .font(.system(.callout, design: .monospaced))
                    .foregroundStyle(Color.ink)
                    .padding(Space.m)
            }
            .background(Color.ink.opacity(0.06), in: .rect(cornerRadius: 12))
        }
    }

    enum Block {
        case heading(Int, String)
        case paragraph(String)
        case list([String], numbered: Bool)
        case quote(String)
        case code(String)
    }

    static func blocks(_ text: String) -> [Block] {
        var out: [Block] = []
        var para: [String] = []
        var items: [String] = []
        var numbered = false
        var code: [String]?

        func flushPara() {
            if !para.isEmpty { out.append(.paragraph(para.joined(separator: "\n"))); para = [] }
        }
        func flushList() {
            if !items.isEmpty { out.append(.list(items, numbered: numbered)); items = [] }
        }

        for raw in text.components(separatedBy: "\n") {
            let line = raw.trimmingCharacters(in: .whitespaces)
            if line.hasPrefix("```") {
                if let open = code {
                    out.append(.code(open.joined(separator: "\n")))
                    code = nil
                } else {
                    flushPara(); flushList()
                    code = []
                }
                continue
            }
            if code != nil { code?.append(raw); continue }
            if line.isEmpty { flushPara(); flushList(); continue }

            if let level = heading(line) {
                flushPara(); flushList()
                out.append(.heading(level, String(line.drop(while: { $0 == "#" }).dropFirst())))
            } else if line.hasPrefix("- ") || line.hasPrefix("* ") {
                flushPara()
                if !items.isEmpty && numbered { flushList() }
                numbered = false
                items.append(String(line.dropFirst(2)))
            } else if let item = numberedItem(line) {
                flushPara()
                if !items.isEmpty && !numbered { flushList() }
                numbered = true
                items.append(item)
            } else if line.hasPrefix("> ") {
                flushPara(); flushList()
                out.append(.quote(String(line.dropFirst(2))))
            } else {
                flushList()
                para.append(line)
            }
        }
        if let open = code { out.append(.code(open.joined(separator: "\n"))) }
        flushPara(); flushList()
        return out
    }

    private static func heading(_ line: String) -> Int? {
        let hashes = line.prefix(while: { $0 == "#" }).count
        guard (1...4).contains(hashes), line.dropFirst(hashes).first == " " else { return nil }
        return hashes
    }

    private static func numberedItem(_ line: String) -> String? {
        let digits = line.prefix(while: \.isNumber)
        guard !digits.isEmpty, line.dropFirst(digits.count).hasPrefix(". ") else { return nil }
        return String(line.dropFirst(digits.count + 2))
    }

    static func inline(_ text: String) -> AttributedString {
        let options = AttributedString.MarkdownParsingOptions(interpretedSyntax: .inlineOnlyPreservingWhitespace)
        var out = (try? AttributedString(markdown: text, options: options)) ?? AttributedString(text)
        for run in out.runs where run.inlinePresentationIntent?.contains(.code) == true {
            out[run.range].font = .system(.callout, design: .monospaced)
            out[run.range].backgroundColor = Color.ink.opacity(0.08)
        }
        for run in out.runs where run.link != nil {
            out[run.range].foregroundColor = Color.linkText
        }
        return out
    }
}
