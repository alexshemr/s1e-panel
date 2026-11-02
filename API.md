# Local API

[Русская версия](docs/ru/api.md) · [← Back to README](README.md)

The panel serves HTTPS on port **8443** with a self-signed certificate. Pin its SHA-256 fingerprint (`certificate_sha256` from `/api/v1/info`) instead of turning certificate checks off.

Every endpoint except `/api/v1/info` and pairing needs a paired client: a browser gets a Secure, HttpOnly cookie; other clients get a revocable Bearer key. Pairing always needs a confirmation on the panel's screen. Credentials never go into URLs.

## Pairing

| Request | Body / result |
| --- | --- |
| `GET /api/v1/info` | Public: `device_id`, `certificate_sha256`, `language`, `bridge_supported`. No household data. |
| `POST /api/v1/pair` | `{"name":"My script","kind":"browser"}`. The panel lights up with the request; returns a request `id` and a four-digit `match` shown on the panel too. Optional `"code"` — the six-digit code from **Settings → Pair a device**. |
| `GET /api/v1/pair/{id}` | Poll until the panel approves; the one-time answer carries the client key. |
| `GET /api/v1/clients` | Paired clients, without secrets |
| `POST /api/v1/clients/revoke` | `{"id":"..."}` |

The panel is also announced over mDNS as `_s1e-panel._tcp.local.` with its id and certificate fingerprint.

## State and control

| Request | Body / result |
| --- | --- |
| `GET /api/v1/status` | Version, Home Assistant connection, screen, entities on the panel, metrics |
| `POST /api/v1/commands` | `{"entity_id":"light.kitchen","action":"turn_on","data":{"brightness":128}}`. `local.relay1`–`local.relay3` switch the panel's relays. |
| `PUT /api/v1/screen` | `{"on":true,"brightness":60}` — brightness 1–100 |
| `GET` / `PUT /api/v1/screensaver` | `{"selected":"weather","options":["clock","sensors","weather","photo","moon","shuffle"]}`; PUT takes `{"selected":"sensors"}` |
| `WS /api/v1/events` | Status, configuration and state changes |

## Notifications

`POST /api/v1/notifications`

```json
{"id":"rain","title":"Rain tomorrow","text":"Take an umbrella","icon":"mdi:umbrella","type":"info","priority":"normal","duration":10,"ttl":300}
```

- `type`: `info`, `success`, `warning`, `error`. `priority: "high"` interrupts the current screen; a normal message waits for the screensaver.
- `duration` is how long it stays on screen (1–3600 s), `ttl` how long it stays relevant (1–86400 s).
- `id` (1–128 characters `A-Z a-z 0-9 _ . : -`) replaces an earlier message with the same id.
- `weather` (a Home Assistant forecast item) and `background` (`auto`, `weather`, `plain`) draw a weather message. `weather.parts` — up to four `{"label","condition","temperature","precipitation_probability","night"}` — adds a row such as morning, day and evening.
- `image: {"jpeg": "<base64>"}` adds a photo: a baseline JPEG up to 480 × 360 and 512 KB. The integration's `s1e_panel.show_message` fills it from a camera for you.

`DELETE /api/v1/notifications/{id}` removes one message; `DELETE /api/v1/notifications` removes all.

## Configuration

`GET /api/v1/config` returns the versioned configuration (pages, cards, screensaver, screen, relays). `PUT /api/v1/config` takes `{"expected_revision":12,"config":{...}}` and answers HTTP 409 if someone else changed it first. Cards sit on an 8 × 8 grid (`x`, `y`, `w`, `h`); `GET /api/v1/templates` lists the card types and their sizes. Secrets and photos are not part of the configuration.

## Updates

| Request | Body / result |
| --- | --- |
| `GET /api/v1/updates` | Slots, progress, and the latest GitHub release |
| `POST /api/v1/updates/check` · `/download` | Check or download the latest release from this repository (HTTP 202) |
| `POST /api/v1/updates/uploads` | `{"size":14289479}` — start uploading a `.s1e`; then `PUT /uploads/{id}` in chunks up to 64 KiB and `POST /uploads/{id}/finish` |
| `POST /api/v1/updates/activate` | `{"id":"..."}` — install a verified package; the panel rolls back by itself if it does not start cleanly |
