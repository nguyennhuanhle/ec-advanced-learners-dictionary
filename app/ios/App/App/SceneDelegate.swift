import UIKit
import Capacitor

/// UC-I02: vuốt từ mép trái để lùi bằng cử chỉ gốc của WKWebView. App ghi mỗi màn hình bằng history.pushState("#/…")
/// nên danh sách lùi/tiến của WebView chính là lịch sử tra trong app; ở màn đầu tiên không có gì để lùi thì cử chỉ tự tắt.
/// (Bắt vuốt bằng touchstart/touchend trong JS không dùng được: vùng cuộn của WebView giành cử chỉ và huỷ sự kiện chạm.)
class MainViewController: CAPBridgeViewController {
    override func capacitorDidLoad() {
        super.capacitorDidLoad()
        webView?.allowsBackForwardNavigationGestures = true
    }
}

class SceneDelegate: UIResponder, UIWindowSceneDelegate {
    var window: UIWindow?

    func scene(_ scene: UIScene, willConnectTo session: UISceneSession, options connectionOptions: UIScene.ConnectionOptions) {
        guard let windowScene = scene as? UIWindowScene else { return }

        window = UIWindow(windowScene: windowScene)
        window?.rootViewController = MainViewController()
        window?.makeKeyAndVisible()

        SceneDelegateProxy.shared.scene(scene, willConnectTo: session, options: connectionOptions)
    }

    func scene(_ scene: UIScene, openURLContexts URLContexts: Set<UIOpenURLContext>) {
        SceneDelegateProxy.shared.scene(scene, openURLContexts: URLContexts)
    }

    func scene(_ scene: UIScene, continue userActivity: NSUserActivity) {
        SceneDelegateProxy.shared.scene(scene, continue: userActivity)
    }
}
