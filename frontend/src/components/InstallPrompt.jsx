import { useEffect, useState } from "react";

function InstallPrompt() {
  const [installEvent, setInstallEvent] = useState(null);
  const [installed, setInstalled] = useState(false);
  const [showHelp, setShowHelp] = useState(false);

  useEffect(() => {
    const onPrompt = (event) => {
      event.preventDefault();
      setInstallEvent(event);
    };
    const onInstalled = () => {
      setInstalled(true);
      setInstallEvent(null);
    };
    window.addEventListener("beforeinstallprompt", onPrompt);
    window.addEventListener("appinstalled", onInstalled);
    return () => {
      window.removeEventListener("beforeinstallprompt", onPrompt);
      window.removeEventListener("appinstalled", onInstalled);
    };
  }, []);

  async function install() {
    if (!installEvent) return;
    await installEvent.prompt();
    setInstallEvent(null);
  }

  if (installed) return <p className="install-note" role="status">MediMate is installed on this device.</p>;
  return (
    <aside className="install-help" aria-label="Install MediMate">
      {installEvent && <button className="secondary-button" onClick={install} type="button">Install MediMate</button>}
      <button className="text-button" onClick={() => setShowHelp((open) => !open)} type="button" aria-expanded={showHelp}>Add to your home screen</button>
      {showHelp && <p className="install-note">Android: open the browser menu and choose <strong>Install app</strong> or <strong>Add to Home screen</strong>. iPhone: in Safari, tap <strong>Share</strong>, then <strong>Add to Home Screen</strong>.</p>}
    </aside>
  );
}

export default InstallPrompt;
