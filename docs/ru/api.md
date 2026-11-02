# Локальный API

[English version](../../API.md) · [← К README](../../README.ru.md)

Панель отдаёт HTTPS на порту **8443** с самоподписанным сертификатом. Закрепите его отпечаток SHA-256 (`certificate_sha256` из `/api/v1/info`) вместо того, чтобы отключать проверку сертификата.

Все запросы, кроме `/api/v1/info` и сопряжения, требуют сопряжённого клиента: браузер получает cookie с флагами Secure и HttpOnly, остальные клиенты — отзываемый ключ Bearer. Сопряжение всегда требует подтверждения на экране панели. Учётные данные никогда не передаются в URL.

## Сопряжение

| Запрос | Тело / ответ |
| --- | --- |
| `GET /api/v1/info` | Открыто: `device_id`, `certificate_sha256`, `language`, `bridge_supported`. Без данных о доме. |
| `POST /api/v1/pair` | `{"name":"Мой скрипт","kind":"browser"}`. Панель включает экран с запросом; ответ — `id` запроса и четырёхзначное `match`, которое показывает и панель. Необязательный `"code"` — шестизначный код из **Настройки → Сопряжение**. |
| `GET /api/v1/pair/{id}` | Опрашивайте, пока панель не подтвердит; одноразовый ответ содержит ключ клиента. |
| `GET /api/v1/clients` | Сопряжённые клиенты, без секретов |
| `POST /api/v1/clients/revoke` | `{"id":"..."}` |

Панель также объявляет себя через mDNS как `_s1e-panel._tcp.local.` со своим идентификатором и отпечатком сертификата.

## Состояние и управление

| Запрос | Тело / ответ |
| --- | --- |
| `GET /api/v1/status` | Версия, связь с Home Assistant, экран, сущности на панели, метрики |
| `POST /api/v1/commands` | `{"entity_id":"light.kitchen","action":"turn_on","data":{"brightness":128}}`. `local.relay1`–`local.relay3` переключают реле панели. |
| `PUT /api/v1/screen` | `{"on":true,"brightness":60}` — яркость 1–100 |
| `GET` / `PUT /api/v1/screensaver` | `{"selected":"weather","options":["clock","sensors","weather","photo","moon","shuffle"]}`; PUT принимает `{"selected":"sensors"}` |
| `WS /api/v1/events` | Изменения статуса, конфигурации и состояний |

## Уведомления

`POST /api/v1/notifications`

```json
{"id":"rain","title":"Завтра дождь","text":"Возьмите зонт","icon":"mdi:umbrella","type":"info","priority":"normal","duration":10,"ttl":300}
```

- `type`: `info`, `success`, `warning`, `error`. `priority: "high"` прерывает текущий экран; обычное сообщение ждёт заставки.
- `duration` — сколько сообщение висит на экране (1–3600 с), `ttl` — сколько остаётся актуальным (1–86400 с).
- `id` (1–128 символов `A-Z a-z 0-9 _ . : -`) заменяет прежнее сообщение с тем же `id`.
- `weather` (элемент прогноза Home Assistant) и `background` (`auto`, `weather`, `plain`) рисуют погодное сообщение. `weather.parts` — до четырёх `{"label","condition","temperature","precipitation_probability","night"}` — добавляет ряд, например утро, день и вечер.
- `image: {"jpeg": "<base64>"}` добавляет фото: baseline JPEG до 480 × 360 и 512 КБ. Действие интеграции `s1e_panel.show_message` заполняет его снимком с камеры само.

`DELETE /api/v1/notifications/{id}` убирает одно сообщение; `DELETE /api/v1/notifications` — все.

## Конфигурация

`GET /api/v1/config` возвращает конфигурацию с ревизией (страницы, карточки, заставки, экран, реле). `PUT /api/v1/config` принимает `{"expected_revision":12,"config":{...}}` и отвечает HTTP 409, если кто-то успел изменить её раньше. Карточки стоят на сетке 8 × 8 (`x`, `y`, `w`, `h`); `GET /api/v1/templates` перечисляет типы карточек и их размеры. Секреты и фотографии в конфигурацию не входят.

## Обновления

| Запрос | Тело / ответ |
| --- | --- |
| `GET /api/v1/updates` | Слоты, прогресс и последний выпуск на GitHub |
| `POST /api/v1/updates/check` · `/download` | Проверить или скачать последний выпуск из этого репозитория (HTTP 202) |
| `POST /api/v1/updates/uploads` | `{"size":14289479}` — начать загрузку `.s1e`; затем `PUT /uploads/{id}` частями до 64 КиБ и `POST /uploads/{id}/finish` |
| `POST /api/v1/updates/activate` | `{"id":"..."}` — установить проверенный пакет; если он не запустится как следует, панель откатится сама |
