import Foundation

/// A route the widget asks the app to open. The widget extension performs its
/// `AppIntent` in the app's process (`openAppWhenRun = true`), but the intent is
/// compiled into the widget target and therefore can't reference the app's
/// `DeepLink` / `PendingRoute` types — so it writes one of these to the App
/// Group and the app drains it on activation. Works whether the launch is cold
/// or warm.
enum WidgetRoute: String {
    case swipe
    case screenshots
    case activity
}

/// Shared App Group storage for the cross-target `WidgetSnapshot`. The main app
/// writes; the widget reads. Dependency-free (Foundation only) so it stays light
/// enough to compile into the widget extension. Compiled into BOTH targets.
/// Personal builds have no widget or App Group entitlement and use app-local
/// storage for snapshots, language preferences, and pending routes instead.
enum AppGroupStore {
#if !PERSONAL_BUILD
    static let suiteName = "group.com.sakshammittal.tidybyte.shared"
#endif
    static let snapshotKey = "widget.snapshot.v1"
    static let pendingRouteKey = "widget.pendingRoute.v1"

    static var defaults: UserDefaults {
#if PERSONAL_BUILD
        // Do not open the upstream App Group suite: a non-nil UserDefaults
        // instance does not establish that this build has its entitlement.
        return .standard
#else
        return UserDefaults(suiteName: suiteName) ?? .standard
#endif
    }

    static func save(_ snapshot: WidgetSnapshot) {
        guard let data = try? JSONEncoder().encode(snapshot) else { return }
        defaults.set(data, forKey: snapshotKey)
    }

    static func loadSnapshot() -> WidgetSnapshot? {
        guard let data = defaults.data(forKey: snapshotKey) else { return nil }
        return try? JSONDecoder().decode(WidgetSnapshot.self, from: data)
    }

    // MARK: - Widget → App Route Handoff

    static func savePendingRoute(_ route: WidgetRoute) {
        defaults.set(route.rawValue, forKey: pendingRouteKey)
    }

    /// Returns the queued route and clears it, so a single widget tap can't
    /// re-open the same destination on every subsequent activation.
    static func consumePendingRoute() -> WidgetRoute? {
        defer { defaults.removeObject(forKey: pendingRouteKey) }
        guard let raw = defaults.string(forKey: pendingRouteKey) else { return nil }
        return WidgetRoute(rawValue: raw)
    }
}
