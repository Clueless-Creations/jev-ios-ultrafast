import UIKit

private enum Palette {
    static let accent = UIColor { $0.userInterfaceStyle == .dark
        ? UIColor(red: 0.93, green: 0.48, blue: 0.28, alpha: 1)
        : UIColor(red: 0.68, green: 0.25, blue: 0.10, alpha: 1) }
    static let canvas = UIColor { $0.userInterfaceStyle == .dark
        ? UIColor(red: 0.09, green: 0.085, blue: 0.08, alpha: 1)
        : UIColor(red: 0.97, green: 0.955, blue: 0.93, alpha: 1) }
    static let surface = UIColor { $0.userInterfaceStyle == .dark
        ? UIColor(red: 0.15, green: 0.14, blue: 0.13, alpha: 1)
        : UIColor(red: 1, green: 0.995, blue: 0.98, alpha: 1) }
    static let onAccent = UIColor { $0.userInterfaceStyle == .dark ? UIColor(white: 0.08, alpha: 1) : .white }
    static let ink = UIColor.label
}

@main
final class AppDelegate: UIResponder, UIApplicationDelegate {
    var window: UIWindow?
    func application(_ application: UIApplication,
        didFinishLaunchingWithOptions options: [UIApplication.LaunchOptionsKey: Any]?) -> Bool {
        let navigation = UINavigationController(rootViewController: DaybreakScreen(.home, plan: Trip()))
        navigation.navigationBar.prefersLargeTitles = true
        navigation.navigationBar.tintColor = Palette.accent
        let appearance = UINavigationBarAppearance()
        appearance.configureWithDefaultBackground()
        appearance.backgroundColor = Palette.canvas
        appearance.titleTextAttributes = [.foregroundColor: UIColor.label]
        appearance.largeTitleTextAttributes = [.foregroundColor: UIColor.label]
        appearance.titleTextAttributes = [.foregroundColor: Palette.ink]
        appearance.largeTitleTextAttributes = [.foregroundColor: Palette.ink]
        navigation.navigationBar.standardAppearance = appearance
        navigation.navigationBar.scrollEdgeAppearance = appearance
        let window = UIWindow(frame: UIScreen.main.bounds)
        window.rootViewController = navigation
        window.tintColor = Palette.accent
        window.makeKeyAndVisible()
        self.window = window
        return true
    }
}

private final class Trip {
    var city = "Lisbon"
    var mood = "Design & coffee"
    var transport = "Tram"
    var time = "09:00"
    var summary: String { "\(mood) · \(transport) · \(time)" }
    var neighborhood: String { city == "Lisbon" ? "Príncipe Real & Chiado" : city == "Kyoto" ? "Higashiyama & Gion" : "Nørrebro & the lakes" }
}

private enum Page { case home, destination, mood, preferences, itinerary, saved }

private final class DaybreakScreen: UIViewController {
    private let page: Page
    private let plan: Trip
    private let column = UIStackView()
    private var optionButtons: [String: [UIButton]] = [:]

    init(_ page: Page, plan: Trip) {
        self.page = page
        self.plan = plan
        super.init(nibName: nil, bundle: nil)
        navigationItem.largeTitleDisplayMode = page == .home ? .always : .never
        switch page {
        case .home: title = "Daybreak"
        case .destination: title = plan.city
        case .mood: title = "Your kind of day"
        case .preferences: title = "Make it yours"
        case .itinerary: title = "Your Saturday"
        case .saved: title = "Your weekend"
        }
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = Palette.canvas
        navigationItem.backButtonTitle = "Back"
        let scroll = UIScrollView()
        scroll.translatesAutoresizingMaskIntoConstraints = false
        scroll.contentInsetAdjustmentBehavior = .automatic
        view.addSubview(scroll)
        column.axis = .vertical
        column.spacing = 16
        column.translatesAutoresizingMaskIntoConstraints = false
        scroll.addSubview(column)
        NSLayoutConstraint.activate([
            scroll.topAnchor.constraint(equalTo: view.topAnchor),
            scroll.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            scroll.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            scroll.bottomAnchor.constraint(equalTo: view.bottomAnchor),
            column.topAnchor.constraint(equalTo: scroll.contentLayoutGuide.topAnchor, constant: 16),
            column.bottomAnchor.constraint(equalTo: scroll.contentLayoutGuide.bottomAnchor, constant: -32),
            column.leadingAnchor.constraint(equalTo: scroll.contentLayoutGuide.leadingAnchor, constant: 24),
            column.trailingAnchor.constraint(equalTo: scroll.contentLayoutGuide.trailingAnchor, constant: -24),
            column.widthAnchor.constraint(equalTo: scroll.frameLayoutGuide.widthAnchor, constant: -48)
        ])
        switch page {
        case .home: home()
        case .destination: destination()
        case .mood: mood()
        case .preferences: preferences()
        case .itinerary: itinerary()
        case .saved: saved()
        }
    }

    private func text(_ content: String, _ style: UIFont.TextStyle = .body,
                      secondary: Bool = false) -> UILabel {
        let label = UILabel()
        label.text = content
        label.accessibilityLabel = content
        label.font = .preferredFont(forTextStyle: style)
        label.adjustsFontForContentSizeCategory = true
        label.textColor = secondary ? .secondaryLabel : Palette.ink
        label.numberOfLines = 0
        if [.title1, .title2, .headline].contains(style) { label.accessibilityTraits.insert(.header) }
        return label
    }
    private func add(_ view: UIView) { column.addArrangedSubview(view) }
    private func note(_ value: String) { add(text(value, .subheadline, secondary: true)) }
    private func section(_ value: String) {
        let label = text(value, .headline)
        add(label)
        column.setCustomSpacing(12, after: label)
    }
    private func button(_ title: String, subtitle: String? = nil, symbol: String? = nil,
                        primary: Bool = false, action: @escaping () -> Void) -> UIButton {
        let button = UIButton(type: .system)
        var config = UIButton.Configuration.filled()
        config.title = title
        config.subtitle = subtitle
        config.titleAlignment = .leading
        config.titlePadding = 6
        config.baseForegroundColor = primary ? Palette.onAccent : Palette.ink
        config.baseBackgroundColor = primary ? Palette.accent : Palette.surface
        config.background.cornerRadius = primary ? 14 : 20
        config.contentInsets = NSDirectionalEdgeInsets(top: 20, leading: 20, bottom: 20, trailing: 20)
        config.titleTextAttributesTransformer = UIConfigurationTextAttributesTransformer { attributes in
            var result = attributes
            result.font = .preferredFont(forTextStyle: .headline)
            return result
        }
        config.subtitleTextAttributesTransformer = UIConfigurationTextAttributesTransformer { attributes in
            var result = attributes
            result.font = .preferredFont(forTextStyle: .subheadline)
            result.foregroundColor = UIColor.secondaryLabel
            return result
        }
        if let symbol {
            config.image = UIImage(systemName: symbol, withConfiguration: UIImage.SymbolConfiguration(pointSize: 24, weight: .regular))
            config.imagePadding = 16
        }
        button.configuration = config
        button.contentHorizontalAlignment = primary ? .center : .leading
        button.titleLabel?.adjustsFontForContentSizeCategory = true
        button.titleLabel?.numberOfLines = 0
        button.layer.cornerCurve = .continuous
        button.accessibilityLabel = title
        button.accessibilityHint = subtitle
        button.heightAnchor.constraint(greaterThanOrEqualToConstant: 56).isActive = true
        button.addAction(UIAction { _ in action() }, for: .touchUpInside)
        return button
    }
    private func push(_ next: Page) {
        guard navigationController?.topViewController === self else { return }
        navigationController?.pushViewController(DaybreakScreen(next, plan: plan), animated: !UIAccessibility.isReduceMotionEnabled)
    }
    private func map(height: CGFloat = 208) {
        let map = RouteIllustration()
        map.heightAnchor.constraint(equalToConstant: height).isActive = true
        add(map)
    }
    private func home() {
        add(text("A little planning. A whole day to wander.", .title2))
        note("Thoughtful Saturdays, one neighborhood at a time.")
        section("Where will you slow down?")
        let cities = [("Lisbon", "Tiled streets, good coffee, a slower rhythm.", "sun.horizon"),
                      ("Copenhagen", "Design shops and a pause by the lakes.", "bicycle"),
                      ("Kyoto", "Quiet lanes, small gardens, tea houses.", "leaf")]
        for (city, detail, symbol) in cities {
            add(button(city, subtitle: detail, symbol: symbol) { [weak self] in
                self?.plan.city = city
                self?.push(.destination)
            })
        }
        note("Three places. Plenty of room for the unexpected.")
    }
    private func destination() {
        note("THE WEEKEND EDIT")
        map(height: 220)
        add(text("Take the scenic way.", .title1))
        note(plan.city == "Lisbon" ? "Warm light, independent shops, and coffee worth sitting down for." : "A few good places, close together. Leave the rest of the day open.")
        section(plan.neighborhood)
        note("Saturday · 3 stops · an unhurried morning")
        add(button("Plan a Saturday", symbol: "arrow.right", primary: true) { [weak self] in self?.push(.mood) })
    }
    private func mood() {
        note("SATURDAY IN \(plan.city.uppercased())")
        add(text("Follow what you love.", .title2))
        note("A small collection of places with one good thread.")
        for (name, detail, symbol) in [
            ("Design & coffee", "Beautiful things. A very good flat white.", "cup.and.saucer"),
            ("Art & gardens", "Room to look, think, and take the long way.", "leaf.circle"),
            ("Food & markets", "Something seasonal. Somewhere worth lingering.", "basket")
        ] {
            add(button(name, subtitle: detail, symbol: symbol) { [weak self] in
                self?.plan.mood = name
                self?.push(.preferences)
            })
        }
        note("No packed schedule. Just three reasons to head out.")
    }
    private func choices(_ values: [String], group: String, selected: String) {
        let row = UIStackView()
        row.axis = .horizontal
        row.spacing = 8
        row.distribution = .fillEqually
        var buttons: [UIButton] = []
        for value in values {
            let choice = UIButton(type: .system)
            var config = UIButton.Configuration.bordered()
            config.title = value
            config.cornerStyle = .medium
            config.contentInsets = NSDirectionalEdgeInsets(top: 16, leading: 4, bottom: 16, trailing: 4)
            config.titleTextAttributesTransformer = UIConfigurationTextAttributesTransformer { original in
                var attributes = original
                attributes.font = UIFont.preferredFont(forTextStyle: .subheadline)
                return attributes
            }
            choice.configuration = config
            choice.accessibilityLabel = value
            choice.titleLabel?.adjustsFontForContentSizeCategory = true
            choice.heightAnchor.constraint(greaterThanOrEqualToConstant: 52).isActive = true
            choice.addAction(UIAction { [weak self] _ in
                guard let self else { return }
                if group == "transport" { self.plan.transport = value } else { self.plan.time = value }
                self.updateChoices(group, selected: value)
                UISelectionFeedbackGenerator().selectionChanged()
            }, for: .touchUpInside)
            buttons.append(choice)
            row.addArrangedSubview(choice)
        }
        optionButtons[group] = buttons
        updateChoices(group, selected: selected)
        add(row)
    }
    private func updateChoices(_ group: String, selected: String) {
        for choice in optionButtons[group] ?? [] {
            let active = choice.accessibilityLabel == selected
            choice.configuration?.baseBackgroundColor = active ? Palette.accent : Palette.surface
            choice.configuration?.baseForegroundColor = active ? Palette.onAccent : Palette.ink
            choice.accessibilityValue = active ? "Selected" : "Not selected"
            choice.accessibilityTraits = active ? [.button, .selected] : [.button]
        }
    }
    private func preferences() {
        note("\(plan.city) · \(plan.mood)")
        add(text("A slow Saturday.", .title2))
        note("Three stops, with breathing room between them.")
        section("Getting around")
        choices(["Walking", "Tram", "Cycling"], group: "transport", selected: plan.transport)
        section("Start your morning")
        choices(["09:00", "10:00", "11:00"], group: "time", selected: plan.time)
        let detail = text("Unhurried by design\nAbout 3 hours, including time to linger.", .body, secondary: true)
        add(detail)
        add(button("Build itinerary", symbol: "map", primary: true) { [weak self] in self?.push(.itinerary) })
    }
    private func itinerary() {
        note("\(plan.city.uppercased()) · 3 STOPS · SLOW PACE")
        map(height: 190)
        add(text(plan.summary, .subheadline))
        let start = Int(plan.time.prefix(2)) ?? 10
        let names = plan.mood == "Design & coffee" ? ["Coffee, without the rush", "Small shops, good design", "A view worth the detour"] : plan.mood == "Art & gardens" ? ["A quiet gallery", "An afternoon garden", "A place to sit and sketch"] : ["The neighborhood market", "A long, local lunch", "Something sweet to finish"]
        for index in 0..<3 {
            let row = UIStackView()
            row.axis = .horizontal
            row.alignment = .top
            row.spacing = 16
            let stamp = text(String(format: "%02d:%02d", start + index, index == 1 ? 15 : 0), .subheadline)
            stamp.textColor = Palette.accent
            stamp.font = UIFontMetrics(forTextStyle: .subheadline).scaledFont(for: .monospacedDigitSystemFont(ofSize: 15, weight: .semibold))
            stamp.setContentHuggingPriority(.defaultHigh, for: .horizontal)
            stamp.widthAnchor.constraint(equalToConstant: UIFontMetrics(forTextStyle: .subheadline).scaledValue(for: 56)).isActive = true
            stamp.setContentCompressionResistancePriority(.required, for: .horizontal)
            row.addArrangedSubview(stamp)
            let words = UIStackView(arrangedSubviews: [text(names[index], .headline), text(["Settle in. Order something you love.", "A few beautiful things to bring home.", "Stay for a while. The day is still yours."][index], .subheadline, secondary: true)])
            words.axis = .vertical
            words.spacing = 4
            row.addArrangedSubview(words)
            add(row)
        }
        note("Illustrated route · \(plan.neighborhood)")
        add(button("Save weekend", symbol: "bookmark", primary: true) { [weak self] in
            guard let self, self.navigationController?.topViewController === self else { return }
            UserDefaults.standard.set(["city": self.plan.city, "mood": self.plan.mood, "transport": self.plan.transport, "time": self.plan.time], forKey: "savedWeekend")
            UINotificationFeedbackGenerator().notificationOccurred(.success)
            let saved = DaybreakScreen(.saved, plan: self.plan)
            self.navigationController?.setViewControllers([self.navigationController!.viewControllers[0], saved], animated: !UIAccessibility.isReduceMotionEnabled)
        })
    }
    private func saved() {
        navigationItem.hidesBackButton = true
        navigationItem.rightBarButtonItem = UIBarButtonItem(title: "Done", primaryAction: UIAction { [weak self] _ in
            self?.navigationController?.popToRootViewController(animated: !UIAccessibility.isReduceMotionEnabled)
        })
        let seal = UIImageView(image: UIImage(systemName: "bookmark.circle.fill", withConfiguration: UIImage.SymbolConfiguration(pointSize: 48)))
        seal.tintColor = Palette.accent
        seal.contentMode = .left
        seal.heightAnchor.constraint(equalToConstant: 64).isActive = true
        seal.isAccessibilityElement = false
        add(seal)
        add(text("\(plan.city) weekend saved", .title1))
        add(text(plan.summary, .headline))
        note("Saturday, sorted. Leave a little room for a wrong turn.")
        map(height: 240)
        section(plan.neighborhood)
        note("3 stops · slow pace · saved on this device")
    }
}

private final class RouteIllustration: UIView {
    override init(frame: CGRect) {
        super.init(frame: frame)
        backgroundColor = Palette.surface
        layer.cornerRadius = 24
        layer.cornerCurve = .continuous
        clipsToBounds = true
        isAccessibilityElement = true
        accessibilityLabel = "Illustrated neighborhood route with three stops"
        accessibilityTraits = .image
        contentMode = .redraw
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
    override func traitCollectionDidChange(_ previousTraitCollection: UITraitCollection?) {
        super.traitCollectionDidChange(previousTraitCollection)
        if traitCollection.hasDifferentColorAppearance(comparedTo: previousTraitCollection) { setNeedsDisplay() }
    }
    override func draw(_ rect: CGRect) {
        let w = rect.width, h = rect.height
        let street = UIColor { $0.userInterfaceStyle == .dark ? UIColor(white: 0.27, alpha: 1) : UIColor(red: 0.88, green: 0.86, blue: 0.82, alpha: 1) }
        street.setStroke()
        for index in -2...7 {
            let path = UIBezierPath()
            path.move(to: CGPoint(x: CGFloat(index) * w / 5, y: -20))
            path.addLine(to: CGPoint(x: CGFloat(index) * w / 5 + 80, y: h + 20))
            path.lineWidth = 10
            path.stroke()
        }
        for fraction in [0.24, 0.52, 0.8] {
            let path = UIBezierPath()
            path.move(to: CGPoint(x: -20, y: h * fraction))
            path.addCurve(to: CGPoint(x: w + 20, y: h * fraction - 25), controlPoint1: CGPoint(x: w * 0.4, y: h * fraction + 30), controlPoint2: CGPoint(x: w * 0.7, y: h * fraction - 40))
            path.lineWidth = 12
            path.stroke()
        }
        let points = [CGPoint(x: w * 0.2, y: h * 0.73), CGPoint(x: w * 0.52, y: h * 0.47), CGPoint(x: w * 0.78, y: h * 0.23)]
        Palette.accent.setStroke()
        let route = UIBezierPath()
        route.move(to: points[0])
        route.addCurve(to: points[1], controlPoint1: CGPoint(x: w * 0.18, y: h * 0.4), controlPoint2: CGPoint(x: w * 0.38, y: h * 0.7))
        route.addCurve(to: points[2], controlPoint1: CGPoint(x: w * 0.63, y: h * 0.24), controlPoint2: CGPoint(x: w * 0.68, y: h * 0.5))
        route.lineWidth = 4
        route.lineCapStyle = .round
        route.stroke()
        for (index, point) in points.enumerated() {
            Palette.surface.setFill()
            UIBezierPath(ovalIn: CGRect(x: point.x - 18, y: point.y - 18, width: 36, height: 36)).fill()
            Palette.accent.setFill()
            UIBezierPath(ovalIn: CGRect(x: point.x - 14, y: point.y - 14, width: 28, height: 28)).fill()
            let number = "\(index + 1)" as NSString
            number.draw(at: CGPoint(x: point.x - 4.5, y: point.y - 9), withAttributes: [.font: UIFont.systemFont(ofSize: 14, weight: .semibold), .foregroundColor: Palette.onAccent])
        }
    }
}
