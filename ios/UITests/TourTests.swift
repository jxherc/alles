import XCTest

/// walks every screen against a throwaway test alles and saves a screenshot per step.
/// run with TEST_RUNNER_ALLES_SERVER, TEST_RUNNER_ALLES_PW and TEST_RUNNER_SHOTS set.
final class TourTests: XCTestCase {
    private var app: XCUIApplication!
    private var shots = ""
    private var tag = ""

    override func setUp() {
        continueAfterFailure = true
        let env = ProcessInfo.processInfo.environment
        shots = env["SHOTS"] ?? NSTemporaryDirectory()
        tag = env["SHOT_TAG"] ?? (UIDevice.current.userInterfaceIdiom == .pad ? "ipad" : "iphone")
        app = XCUIApplication()
        if env["ORIENT"] == "landscape" {
            XCUIDevice.shared.orientation = .landscapeLeft
            tag += "-land"
        } else {
            XCUIDevice.shared.orientation = .portrait
        }
    }

    private func shot(_ name: String) {
        let data = XCUIScreen.main.screenshot().pngRepresentation
        try? data.write(to: URL(fileURLWithPath: shots).appendingPathComponent("\(tag)-\(name).png"))
    }

    private func dismissKeyboardTip() {
        let tip = app.buttons["Continue"]
        if tip.waitForExistence(timeout: 1) { tip.tap() }
    }

    private func tab(_ name: String) {
        let button = app.tabBars.buttons[name].firstMatch
        if button.waitForExistence(timeout: 3) {
            button.tap()
        } else {
            app.buttons[name].firstMatch.tap()
        }
    }

    func test1SignIn() throws {
        let env = ProcessInfo.processInfo.environment
        let server = try XCTUnwrap(env["ALLES_SERVER"])
        let password = try XCTUnwrap(env["ALLES_PW"])
        app.launchArguments = ["-AppleLanguages", "(en)"]
        app.launch()

        if app.tabBars.firstMatch.waitForExistence(timeout: 3) || app.buttons["home"].waitForExistence(timeout: 1) {
            return // already signed in from an earlier run
        }
        let address = app.textFields.firstMatch
        XCTAssertTrue(address.waitForExistence(timeout: 5))
        dismissKeyboardTip()
        address.tap()
        dismissKeyboardTip()
        address.typeText(server)
        shot("01-connect")
        app.buttons["continue"].tap()

        let field = app.secureTextFields.firstMatch
        XCTAssertTrue(field.waitForExistence(timeout: 8), "password step never showed")
        shot("02-password")
        field.tap()
        field.typeText(password)
        app.buttons["sign in"].tap()
        XCTAssertTrue(app.staticTexts["schedule"].waitForExistence(timeout: 10), "home never loaded")
    }

    func test2Home() {
        app.launch()
        XCTAssertTrue(app.staticTexts["schedule"].waitForExistence(timeout: 10))
        sleep(1)
        shot("03-home")

        let task = app.buttons["chem lab report"]
        if task.waitForExistence(timeout: 3) {
            task.tap()
            sleep(1)
        }
        let habit = app.buttons["gym"]
        if habit.waitForExistence(timeout: 2) {
            habit.tap()
            sleep(1)
        }
        shot("04-home-checked")
        app.swipeUp()
        sleep(1)
        shot("05-home-scrolled")
    }

    func test3Aide() {
        app.launch()
        tab("aide")
        let field = app.textFields["message aide"].firstMatch
        XCTAssertTrue(field.waitForExistence(timeout: 8))
        sleep(1)
        shot("06-aide")
        field.tap()
        dismissKeyboardTip()
        field.typeText("what's on today?")
        shot("07-aide-typing")
        app.buttons["composer.send"].tap()
        usleep(700_000)
        shot("08-aide-waiting")
        sleep(3)
        shot("09-aide-streaming")
        // leave mid reply: the live reply rides under the tab bar
        dismissKeyboardTip()
        let list = app.scrollViews["aide.thread"]
        list.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.15))
            .press(forDuration: 0.05, thenDragTo: list.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.45)))
        usleep(500_000)
        tab("home")
        usleep(600_000)
        shot("10-accessory")
        sleep(14)
        tab("aide")
        sleep(1)
        shot("11-aide-done")
        app.swipeDown()
        sleep(1)
        shot("12-aide-scrolled")
    }

    func test4Plan() {
        app.launch()
        tab("plan")
        sleep(2)
        shot("13-plan-today")
        app.segmentedControls.buttons["calendar"].firstMatch.tap()
        sleep(1)
        shot("14-plan-calendar")
        app.segmentedControls.buttons["tasks"].firstMatch.tap()
        sleep(1)
        shot("15-plan-tasks")
        app.buttons["add a task"].tap()
        let field = app.textFields.firstMatch
        XCTAssertTrue(field.waitForExistence(timeout: 4))
        field.typeText("buy milk tomorrow")
        shot("16-plan-add")
        app.buttons["add"].tap()
        sleep(2)
        shot("17-plan-added")
    }

    func test5Apps() {
        app.launch()
        tab("apps")
        sleep(1)
        shot("18-apps")
        app.buttons["docs"].firstMatch.tap()
        sleep(2)
        shot("19-docs")
        let folder = app.buttons["school"].firstMatch
        if folder.waitForExistence(timeout: 2) { folder.tap(); sleep(1) }
        let note = app.buttons["ics4u notes"].firstMatch
        if note.waitForExistence(timeout: 3) {
            note.tap()
            sleep(2)
            shot("20-doc")
            app.buttons["edit"].firstMatch.tap()
            sleep(1)
            shot("21-doc-edit")
            app.buttons["cancel"].firstMatch.tap()
        }
        // back out to the apps list
        for _ in 0..<4 where !app.navigationBars["apps"].exists {
            app.navigationBars.buttons.firstMatch.tap()
            sleep(1)
        }
        app.buttons["files"].firstMatch.tap()
        sleep(4)
        shot("22-files-web")
    }

    func test6Search() {
        app.launch()
        tab("andromeda")
        sleep(1)
        var field = app.searchFields.firstMatch
        if !field.waitForExistence(timeout: 3) {
            field = app.textFields["search the web"].firstMatch
        }
        if !field.waitForExistence(timeout: 3) {
            shot("23-search-nofield")
            print(app.debugDescription)
        }
        XCTAssertTrue(field.exists)
        field.tap()
        field.typeText("liquid glass swiftui\n")
        sleep(5)
        shot("23-search")
    }
}
