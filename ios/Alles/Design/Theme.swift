import SwiftUI

// colours come from design-system/FOUNDATIONS.md (Assets.xcassets holds both themes)
extension Color {
    static let page = Color("Page")
    static let panel = Color("Panel")
    static let raised = Color("Raised")
    static let ink = Color("Ink")
    static let inkSoft = Color("InkSoft")
    static let inkMuted = Color("InkMuted")
    static let line = Color("Line")
    static let danger = Color("Danger")
    static let success = Color("Success")
    static let linkText = Color("Link")
    static let active = Color.accentColor
    /// text and icons on the accent: the page colour reads on both the dark-theme light purple
    /// and the light-theme deep purple (white on #aaa6ff is about 2:1)
    static let onActive = Color("Page")
}

enum Space {
    static let xs: CGFloat = 4
    static let s: CGFloat = 8
    static let m: CGFloat = 12
    static let l: CGFloat = 16
    static let xl: CGFloat = 24
    static let xxl: CGFloat = 32
}

extension View {
    /// warm page colour behind a whole screen, so glass bars have something to sit on
    func pageBackground() -> some View {
        background(Color.page.ignoresSafeArea())
    }

    /// keeps reading text at a comfortable measure on ipad. pages with a large title keep it
    /// on the title's edge (leading); a chat sits in the middle
    func readableWidth(_ width: CGFloat = 680, alignment: Alignment = .leading) -> some View {
        frame(maxWidth: width, alignment: .leading).frame(maxWidth: .infinity, alignment: alignment)
    }

    /// the large title's inset: 16 on iphone, 20 on ipad
    func pageGutter() -> some View {
        modifier(PageGutter())
    }
}

private struct PageGutter: ViewModifier {
    @Environment(\.horizontalSizeClass) private var width
    func body(content: Content) -> some View {
        content.padding(.horizontal, width == .regular ? 20 : Space.l)
    }
}

struct SectionTitle: View {
    let text: String
    var trailing: String?

    init(_ text: String, trailing: String? = nil) {
        self.text = text
        self.trailing = trailing
    }

    var body: some View {
        HStack(alignment: .firstTextBaseline) {
            Text(text)
                .font(.headline)
                .foregroundStyle(Color.ink)
            Spacer()
            if let trailing {
                Text(trailing)
                    .font(.subheadline)
                    .foregroundStyle(Color.inkMuted)
                    .monospacedDigit()
            }
        }
    }
}
