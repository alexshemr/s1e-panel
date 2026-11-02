# Troubleshooting

[Русская версия](ru/troubleshooting.md) · [← Back to README](../README.md)

Problems during the first installation are covered in the [installation guide](installation.md#45-if-something-goes-wrong).

## The panel is not on Wi-Fi

- On the panel: pull down → **Settings → Wi-Fi**. The status, address and signal strength are shown at the top.
- Enter the network name exactly (it is case-sensitive) and a WPA/WPA2 password of 8–63 characters, then **Connect**.
- A weak signal gives a slow or unstable connection; move the access point closer or add one.

## I cannot open the editor

- Use **https** and the port: `https://<panel-ip>:8443`. The address is in **Settings → Wi-Fi** or **Settings → Pair a device**.
- The browser warning about the certificate is expected: the panel uses its own self-signed certificate. Continue to the site.
- The computer or phone must be on a network that can reach the panel (guest Wi-Fi networks often cannot).

## Pairing does not finish

- The request waits two minutes for **Allow** on the panel. If the panel did not light up, check that the browser reached `https://<panel-ip>:8443`, then request access again.
- Closing the request with × on the panel leaves it unanswered; request access again to see it.

## Home Assistant does not find the panel

- Discovery uses mDNS (IPv4) on the local network. Across VLANs or with mDNS blocked on the router, use an mDNS repeater or add the integration manually: **Settings → Devices & services → Add integration → S1E Panel**, address `https://<panel-ip>:8443`.
- To pair again, add the integration and tap **Allow** on the panel.
- Requirements: Home Assistant 2026.10.1 or newer and the latest S1E Panel integration from HACS.

## Cards show "unavailable" or do not react

- Check the connection: the panel shows when Home Assistant is offline (**Settings → Home Assistant**). The integration's diagnostics in Home Assistant show the same from the other side.
- The entity itself may be unavailable in Home Assistant: check it under **Settings → Entities**.
- If you renamed or replaced a device in Home Assistant, its `entity_id` may have changed: bind the card to the new entity in the editor.
- A command that Home Assistant does not confirm is rolled back on the card: the card shows the device's real state.

## A device mode or control is missing on a card

- Cards show only what the entity reports: a lamp without colour support has no colour control.
- Card settings can hide controls and modes: open the card in the editor → **Card settings** and check what is shown.
- Some controls appear only on larger card sizes; try a larger size.

## The screen stays dark or too dim

- Touch the screen: it may be in the screensaver or the scheduled sleep.
- Check **Scheduled sleep** and **Then turn off** in the screen settings, and whether a Home Assistant automation turns the **Screen** off.
- Brightness: pull down from the top edge and use the slider.

## An update failed

- The panel returns to the previous version by itself when a new one does not start cleanly; your settings come back with it. Try again later or install the `.s1e` file from [Releases](https://github.com/alexshemr/s1e-panel/releases) in the editor.
- Downloading from GitHub needs internet access and a correct clock: the panel takes its time from Home Assistant, so connect Home Assistant first.

## The panel does not start at all

- If S1E Panel cannot start, the factory system starts instead (the boot arguments fall back to it).
- As a last resort, the service console used for the installation is the recovery path. [Open an issue](https://github.com/alexshemr/s1e-panel/issues) with what you see on the screen and on the console.

## Reporting a problem

[Open an issue](https://github.com/alexshemr/s1e-panel/issues) with:
- the firmware version (**Settings → Panel update**) and the integration version;
- what you did and what happened;
- for installation problems, the folder `s1e-install-logs/<time>` made by the installer (it contains no passwords).
