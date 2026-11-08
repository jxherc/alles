import SwiftUI

/// the alles mark: the purple dot from the app icon. it breathes while aide is working.
struct AllesDot: View {
    var size: CGFloat = 10
    var working = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var pulse = false

    var body: some View {
        Circle()
            .fill(Color.active)
            .frame(width: size, height: size)
            .scaleEffect(working && pulse && !reduceMotion ? 0.72 : 1)
            .opacity(working && pulse ? 0.55 : 1)
            .animation(
                working ? .easeInOut(duration: 0.7).repeatForever(autoreverses: true) : .default,
                value: pulse
            )
            .onAppear { pulse = working }
            .onChange(of: working) { _, now in pulse = now }
            .accessibilityHidden(true)
    }
}

/// three dots that rise one after another, the "typing" in a chat
struct TypingDots: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        TimelineView(.animation(minimumInterval: 1 / 30, paused: reduceMotion)) { context in
            let t = context.date.timeIntervalSinceReferenceDate
            HStack(spacing: 4) {
                ForEach(0..<3, id: \.self) { i in
                    let lift = reduceMotion ? 0 : rise(t, i)
                    Circle()
                        .fill(Color.inkMuted)
                        .frame(width: 7, height: 7)
                        .offset(y: -3 * lift)
                        .opacity(0.45 + 0.55 * (reduceMotion ? 1 : lift))
                }
            }
        }
        .accessibilityLabel("aide is typing")
    }

    private func rise(_ t: Double, _ i: Int) -> Double {
        let angle: Double = t * 2 * Double.pi / 1.1 - Double(i) * 0.7
        return max(0, sin(angle))
    }
}

/// a round glass button for floating actions (add a task, jump to latest)
struct GlassCircleButton: View {
    let systemImage: String
    let label: String
    var prominent = false
    var size: CGFloat = 52
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Image(systemName: systemImage)
                .font(.system(size: size * 0.38, weight: .semibold))
                .foregroundStyle(prominent ? Color.onActive : Color.ink)
                .frame(width: size, height: size)
                .contentShape(Circle())
        }
        .buttonStyle(.plain)
        .glassEffect(prominent ? .regular.tint(.active).interactive() : .regular.interactive(), in: .circle)
        .accessibilityLabel(label)
    }
}

/// a soft line of status text under a list or on an empty screen
struct QuietNote: View {
    let text: String
    var body: some View {
        Text(text)
            .font(.subheadline)
            .foregroundStyle(Color.inkMuted)
            .frame(maxWidth: .infinity, alignment: .center)
            .padding(.vertical, Space.xl)
    }
}
