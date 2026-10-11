import { Check, Copy, Globe, QrCode, Share, Smartphone, Wifi, X } from "lucide-react";
import { QRCodeSVG } from "qrcode.react";
import { useEffect, useState } from "react";
import type { Lang } from "../i18n";

interface Props {
  lang: Lang;
  onClose: () => void;
}

export default function MobileSheet({ lang, onClose }: Props) {
  const [copied, setCopied] = useState(false);
  const [ip, setIp] = useState(() => (typeof window !== "undefined" ? window.location.hostname : "localhost"));
  const [deferredPrompt, setDeferredPrompt] = useState<any>(null);
  const [installed, setInstalled] = useState(false);

  const isLocal = ip === "localhost" || ip === "127.0.0.1";
  // If viewing on localhost on a Mac/PC, construct the network IP URL for phone scanning
  // Default to window.location.hostname, or let user customize
  const currentPort = typeof window !== "undefined" && window.location.port ? `:${window.location.port}` : "";
  const phoneUrl = typeof window !== "undefined"
    ? `${window.location.protocol}//${ip}${currentPort}`
    : "http://localhost:5173";

  const isMobile = typeof navigator !== "undefined" && (/Android|iPhone|iPad|iPod/i.test(navigator.userAgent) || (window.innerWidth <= 768 && "ontouchstart" in window));
  const isIos = typeof navigator !== "undefined" && /iPhone|iPad|iPod/i.test(navigator.userAgent);

  useEffect(() => {
    const handleBeforeInstall = (e: Event) => {
      e.preventDefault();
      setDeferredPrompt(e);
    };
    window.addEventListener("beforeinstallprompt", handleBeforeInstall);
    window.addEventListener("appinstalled", () => setInstalled(true));
    return () => {
      window.removeEventListener("beforeinstallprompt", handleBeforeInstall);
    };
  }, []);

  const copyUrl = async () => {
    try {
      await navigator.clipboard.writeText(phoneUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // fallback
    }
  };

  const promptInstall = async () => {
    if (!deferredPrompt) return;
    deferredPrompt.prompt();
    const { outcome } = await deferredPrompt.userChoice;
    if (outcome === "accepted") {
      setInstalled(true);
    }
    setDeferredPrompt(null);
  };

  return (
    <div className="sheet mobile-sheet" role="dialog" aria-label="Mobile access">
      <header className="sheet-head">
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div className="icon-pill">
            <Smartphone size={20} color="#2563eb" />
          </div>
          <div>
            <p className="eyebrow">{lang === "hi" ? "मोबाइल अनुभव" : "Mobile Experience"}</p>
            <h2>{isMobile ? (lang === "hi" ? "ऐप इंस्टॉल करें" : "Install on Phone") : (lang === "hi" ? "फ़ोन पर खोलें" : "Open on Your Phone")}</h2>
          </div>
        </div>
        <button className="icon-btn" onClick={onClose} aria-label="Close">
          <X size={20} />
        </button>
      </header>

      {!isMobile ? (
        <div className="mobile-desktop-view">
          <p className="mobile-subtitle">
            {lang === "hi"
              ? "स्कूटर चलाते समय लाइव नेविगेशन और पानी भरने की फ़ोटो रिपोर्टिंग के लिए अपने फ़ोन पर खोलें।"
              : "Scan the QR code with your phone camera to take ScooterCross on the road with live GPS navigation."}
          </p>

          <div className="qr-container">
            <div className="qr-box">
              <QRCodeSVG
                value={phoneUrl}
                size={180}
                level="M"
                includeMargin={true}
                fgColor="#0f172a"
              />
            </div>
            <p className="qr-hint">
              <QrCode size={14} /> {lang === "hi" ? "फ़ोन कैमरे से स्कैन करें" : "Scan with Phone Camera"}
            </p>
          </div>

          <div className="url-copy-box">
            <span className="url-text">{phoneUrl}</span>
            <button className="btn-copy" onClick={copyUrl}>
              {copied ? <Check size={16} color="#16a34a" /> : <Copy size={16} />}
              {copied ? (lang === "hi" ? "कॉपी हो गया!" : "Copied!") : (lang === "hi" ? "कॉपी करें" : "Copy Link")}
            </button>
          </div>

          {isLocal && (
            <div className="ip-edit-row">
              <label htmlFor="local-ip-input">
                <Wifi size={14} /> {lang === "hi" ? "लैपटॉप का वाई-फ़ाई IP:" : "Laptop Wi-Fi IP:"}
              </label>
              <div className="ip-input-wrap">
                <input
                  id="local-ip-input"
                  type="text"
                  value={ip}
                  onChange={(e) => setIp(e.target.value.trim())}
                  placeholder="e.g. 192.168.1.29"
                />
              </div>
            </div>
          )}

          <div className="mobile-instructions">
            <h4>{lang === "hi" ? "फ़ोन पर शुरू करने के 3 आसान कदम:" : "3 Fast Steps to Connect:"}</h4>
            <ol>
              <li>
                <strong>{lang === "hi" ? "एक ही वाई-फ़ाई:" : "Same Wi-Fi:"}</strong>{" "}
                {lang === "hi"
                  ? "फ़ोन और लैपटॉप एक ही वाई-फ़ाई नेटवर्क से जुड़े होने चाहिए।"
                  : "Ensure your phone is on the same Wi-Fi network as this laptop."}
              </li>
              <li>
                <strong>{lang === "hi" ? "कैमरा खोलें:" : "Scan QR:"}</strong>{" "}
                {lang === "hi"
                  ? "फ़ोन का कैमरा खोलकर ऊपर दिए गए QR कोड को स्कैन करें।"
                  : "Open your iPhone or Android camera and point it at the QR code above."}
              </li>
              <li>
                <strong>{lang === "hi" ? "होम स्क्रीन पर जोड़ें:" : "Add to Home Screen:"}</strong>{" "}
                {lang === "hi"
                  ? "ब्राउज़र में 'Add to Home Screen' दबाएं ताकि यह एक असली ऐप की तरह फ़ुल-स्क्रीन चले।"
                  : "Tap 'Add to Home Screen' in Safari or Chrome for a full-screen, native app experience."}
              </li>
            </ol>
          </div>

          <div className="cellular-tip">
            <Globe size={16} />
            <div>
              <strong>{lang === "hi" ? "सड़क पर 4G/5G डेटा पर चलाना है?" : "Riding outdoors on 4G/5G cellular data?"}</strong>
              <p>
                {lang === "hi"
                  ? "टर्मिनल में 'npm run tunnel' चलाएं ताकि एक सुरक्षित पब्लिक लिंक मिले जो बाहर कहीं भी खुले।"
                  : "Run 'npm run tunnel' in the frontend to get an instant public HTTPS link that works anywhere on the road."}
              </p>
            </div>
          </div>
        </div>
      ) : (
        <div className="mobile-installed-view">
          <div className="pwa-hero">
            <div className="pwa-icon-large">
              <img src="/icon-192.png" alt="ScooterCross Icon" width="64" height="64" style={{ borderRadius: 16 }} />
            </div>
            <h3>Can My Scooter Cross?</h3>
            <p>
              {lang === "hi"
                ? "स्कूटर के लिए सुरक्षित रास्ता, बारिश की चेतावनी और लाइव पानी भराव रिपोर्ट।"
                : "Waterlogged road avoidance, vehicle safety verdict, and live flood navigation."}
            </p>
          </div>

          {deferredPrompt && !installed && (
            <button className="btn primary lg full-width" onClick={promptInstall}>
              <Smartphone size={20} /> {lang === "hi" ? "होम स्क्रीन पर इंस्टॉल करें" : "Install App to Home Screen"}
            </button>
          )}

          {isIos && (
            <div className="ios-install-guide">
              <h4>
                <Share size={18} /> {lang === "hi" ? "iPhone पर ऐप इंस्टॉल कैसे करें:" : "How to install on iPhone:"}
              </h4>
              <div className="guide-step">
                <span className="step-num">1</span>
                <span>{lang === "hi" ? "Safari में नीचे 'Share' बटन पर टैप करें (वर्ग और तीर वाला आइकन)।" : "Tap the Share button at the bottom of Safari (the square with an arrow)."}</span>
              </div>
              <div className="guide-step">
                <span className="step-num">2</span>
                <span>{lang === "hi" ? "नीचे स्क्रॉल करके 'Add to Home Screen (+)' चुनें।" : "Scroll down and tap 'Add to Home Screen (+)'."}</span>
              </div>
              <div className="guide-step">
                <span className="step-num">3</span>
                <span>{lang === "hi" ? "ऊपर दाएं कोने में 'Add' दबाएं। ऐप आपकी होम स्क्रीन पर आ जाएगी!" : "Tap 'Add' in the top right. ScooterCross is now installed on your phone!"}</span>
              </div>
            </div>
          )}

          <div className="mobile-features-grid">
            <div className="feature-card">
              <span className="feat-emoji">🧭</span>
              <strong>{lang === "hi" ? "टर्न-बाय-टर्न" : "Turn-by-Turn"}</strong>
              <p>{lang === "hi" ? "स्कूटर चलाते समय लाइव दिशा-निर्देश" : "Live directions while riding"}</p>
            </div>
            <div className="feature-card">
              <span className="feat-emoji">📸</span>
              <strong>{lang === "hi" ? "कैमरा रिपोर्टिंग" : "Camera Upload"}</strong>
              <p>{lang === "hi" ? "1-क्लिक में पानी की गहराई जाँचें" : "1-tap photo flood check"}</p>
            </div>
            <div className="feature-card">
              <span className="feat-emoji">⚡</span>
              <strong>{lang === "hi" ? "ऑफ़लाइन मैप" : "Offline Ready"}</strong>
              <p>{lang === "hi" ? "नेटवर्क धीमा होने पर भी मैप लोड" : "Caches route and rain data"}</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
