# Благодарности и лицензии

[English version](../credits.md) · [← К README](../../README.ru.md)

## Доступ к Aqara S1E

S1E Panel удалось сделать только потому, что другие сначала нашли путь внутрь панели.

### oopuuu — AqaraS1E-Custom-GUI

**[github.com/oopuuu/AqaraS1E-Custom-GUI](https://github.com/oopuuu/AqaraS1E-Custom-GUI)** — собственный нативный интерфейс и интеграция Home Assistant для Aqara S1E, автор **oopuuu**.

Его руководство описывает весь путь в систему S1E: подключение сервисной консоли (UART), остановку загрузчика U-Boot и загрузку заводского ядра в root-оболочку заменой `init=/linuxrc` на `init=/bin/sh`. Установщик S1E Panel использует именно этот доступ к консоли, а [руководство по установке](installation.md) отправляет вас к инструкциям oopuuu. В README проекта указана лицензия MIT; S1E Panel не копирует его код, фотографии и тексты — только ссылается на них.

### Также спасибо

- **niceboygithub** — [AqaraSmartSwitchS1E](https://github.com/niceboygithub/AqaraSmartSwitchS1E) (Apache-2.0), собрание материалов по Aqara S1E. Руководство по установке ссылается на его фото с распиновкой UART и заметки о загрузчике.

## Программы в прошивке

Компоненты, которые собраны в S1E Panel или поставляются с ней. Тексты их лицензий входят в каждый пакет прошивки (`licenses/`).

| Проект | Для чего | Лицензия |
| --- | --- | --- |
| [LVGL](https://github.com/lvgl/lvgl) 9.4 | Весь графический интерфейс — на панели и в предпросмотре браузера | MIT |
| [TJpgDec](http://elm-chan.org/fsw/tjpgd/) (входит в LVGL) | Декодирование фотографий и кадров камер | Свободная лицензия ChaN |
| [libwebsockets](https://github.com/warmcat/libwebsockets) 4.3 | HTTPS- и WebSocket-сервер и клиент | MIT |
| [Mbed TLS](https://github.com/Mbed-TLS/mbedtls) 3.6 | TLS, сертификаты, проверка подписи обновлений | Apache-2.0 OR GPL-2.0-or-later |
| [nlohmann/json](https://github.com/nlohmann/json) 3.11 | JSON в конфигурации, API и сообщениях | MIT |
| [YAJL](https://github.com/lloyd/yajl) 2.1 | Потоковый разбор JSON | ISC |
| [Noto Sans](https://github.com/notofonts/noto-fonts) | Шрифт интерфейса | SIL Open Font License 1.1 |
| [Material Design Icons](https://github.com/Templarian/MaterialDesign) 7.4.47 от Pictogrammers | Иконки на карточках и в редакторе | Pictogrammers Free License (иконки и шрифт: Apache-2.0) |
| Набор корневых сертификатов [certifi](https://github.com/certifi/python-certifi) | Доверенные сертификаты для загрузки обновлений с GitHub | MPL-2.0 |
| [База часовых поясов tz](https://www.iana.org/time-zones) (через Python [tzdata](https://github.com/python/tzdata)) | Часовые пояса | Общественное достояние |
| Анимация запуска [Andy Fitzsimon](https://codepen.io/andyfitz/pen/LzgJPq) | Анимация домика после запуска, перерисованная нативно на LVGL | MIT |

## Веб-редактор

| Проект | Для чего | Лицензия |
| --- | --- | --- |
| [React](https://github.com/facebook/react) 19 (с `react-dom`, `scheduler`) | Интерфейс редактора | MIT |
| [Lucide](https://github.com/lucide-icons/lucide) (`lucide-react`) | Иконки редактора | ISC |
| Среда выполнения [Emscripten](https://github.com/emscripten-core/emscripten) | Запуск кода интерфейса панели в браузере (WebAssembly) | MIT / University of Illinois NCSA |

## Инструменты сборки

Не поставляются, но S1E Panel собирается с помощью [Zig](https://ziglang.org) (кросс-компилятор для панели), [CMake](https://cmake.org), [Ninja](https://ninja-build.org), [Emscripten](https://emscripten.org), [Vite](https://vite.dev), [TypeScript](https://www.typescriptlang.org) и Python с [Pillow](https://python-pillow.org), [pyserial](https://github.com/pyserial/pyserial) и [cryptography](https://github.com/pyca/cryptography).

## Со стороны Home Assistant

[Интеграция S1E Panel](https://github.com/alexshemr/ha-s1e-panel) (MIT) устанавливается через [HACS](https://hacs.xyz) и работает внутри [Home Assistant](https://www.home-assistant.io). Карточка 3D-принтера работает с принтерами, добавленными в Home Assistant через [ha-bambulab](https://github.com/greghesp/ha-bambulab).

## Изображения

- Фон погоды (`courtyard`) — оригинальное изображение, созданное для этого проекта; частицы погоды, небо и смену дня и ночи рисует S1E Panel.
- Изображения карточек в этой документации отрисованы собственным рендерером S1E Panel.

## S1E Panel

Собственный код S1E Panel распространяется по [лицензии MIT](../../LICENSE).

Aqara — товарный знак Lumi United Technology Co., Ltd. S1E Panel не связана с Aqara или Lumi United Technology и не одобрена и не поддерживается ими. Заводская прошивка этим проектом не распространяется.
