# Credits & licenses

[Русская версия](ru/credits.md) · [← Back to README](../README.md)

## Access to the Aqara S1E

S1E Panel could only be built because others first found a way into the panel. Two community projects published how to reach the S1E's service console; S1E Panel's installer relies on that access, and the [installation guide](installation.md) sends you to both. Equal thanks to both authors.

- **oopuuu** — [AqaraS1E-Custom-GUI](https://github.com/oopuuu/AqaraS1E-Custom-GUI), a custom GUI and Home Assistant integration for the Aqara S1E. Its guide describes the UART wiring, stopping the U-Boot bootloader and booting the stock kernel into a root shell with `init=/bin/sh`. The README states the MIT license.
- **niceboygithub** — [AqaraSmartSwitchS1E](https://github.com/niceboygithub/AqaraSmartSwitchS1E), resources for the Aqara S1E and a Home Assistant integration for its stock firmware. Its notes describe opening the panel, the UART pads (with a pinout photo), stopping U-Boot, including on panels made after July 2023, and booting with `init=/bin/sh`. Apache-2.0.

S1E Panel does not copy their code, photos or texts; it links to them.

## Software in the firmware

Components compiled into or shipped with S1E Panel. Their license texts are included in every firmware package (`licenses/`).

| Project | Used for | License |
| --- | --- | --- |
| [LVGL](https://github.com/lvgl/lvgl) 9.4 | The whole graphical interface, on the panel and in the browser preview | MIT |
| [TJpgDec](http://elm-chan.org/fsw/tjpgd/) (part of LVGL) | Decoding photos and camera frames | ChaN's permissive license |
| [libwebsockets](https://github.com/warmcat/libwebsockets) 4.3 | HTTPS and WebSocket server and client | MIT |
| [Mbed TLS](https://github.com/Mbed-TLS/mbedtls) 3.6 | TLS, certificates, update signature checks | Apache-2.0 OR GPL-2.0-or-later |
| [nlohmann/json](https://github.com/nlohmann/json) 3.11 | JSON in configuration, API and messages | MIT |
| [YAJL](https://github.com/lloyd/yajl) 2.1 | Streaming JSON parsing | ISC |
| [Noto Sans](https://github.com/notofonts/noto-fonts) | Interface font | SIL Open Font License 1.1 |
| [Material Design Icons](https://github.com/Templarian/MaterialDesign) 7.4.47 by Pictogrammers | Icons on cards and in the editor | Pictogrammers Free License (icons and font: Apache-2.0) |
| [certifi](https://github.com/certifi/python-certifi) CA bundle | Trusted certificates for downloading updates from GitHub | MPL-2.0 |
| [tz database](https://www.iana.org/time-zones) (via Python [tzdata](https://github.com/python/tzdata)) | Time zones | Public domain |
| [Moon Phase and Libration, 2026](https://svs.gsfc.nasa.gov/5587), NASA's Scientific Visualization Studio | The Moon screensaver: 24 photos of one lunation | Public domain (NASA imagery) |
| Start-up animation by [Andy Fitzsimon](https://codepen.io/andyfitz/pen/LzgJPq) | The house animation after start, redrawn natively in LVGL | MIT |

## Web editor

| Project | Used for | License |
| --- | --- | --- |
| [React](https://github.com/facebook/react) 19 (with `react-dom`, `scheduler`) | Editor interface | MIT |
| [Lucide](https://github.com/lucide-icons/lucide) (`lucide-react`) | Editor icons | ISC |
| [Emscripten](https://github.com/emscripten-core/emscripten) runtime | Running the panel's interface code in the browser (WebAssembly) | MIT / University of Illinois NCSA |

## Tools used to build it

Not shipped, but S1E Panel is built with [Zig](https://ziglang.org) (cross-compiler for the panel), [CMake](https://cmake.org), [Ninja](https://ninja-build.org), [Emscripten](https://emscripten.org), [Vite](https://vite.dev), [TypeScript](https://www.typescriptlang.org) and Python with [Pillow](https://python-pillow.org), [pyserial](https://github.com/pyserial/pyserial) and [cryptography](https://github.com/pyca/cryptography).

## Home Assistant side

The [S1E Panel integration](https://github.com/alexshemr/ha-s1e-panel) (MIT) is installed with [HACS](https://hacs.xyz) and runs inside [Home Assistant](https://www.home-assistant.io). The 3D printer card works with printers added to Home Assistant by [ha-bambulab](https://github.com/greghesp/ha-bambulab).

## Assets and references

- The weather background (`courtyard`) is an original image generated for this project; weather particles, sky and day/night tinting are drawn by S1E Panel.
- [flutter_weather_bg](https://github.com/xiaweizi/flutter_weather_bg) by **xiaweizi** (MIT), animated weather backgrounds for Flutter, served as a visual reference for S1E Panel's weather scenes. Its code is not included: the scenes are drawn natively with LVGL.
- Card pictures in this documentation are rendered by S1E Panel's own renderer.

## S1E Panel

S1E Panel's own code is licensed under the [MIT License](../LICENSE).

Aqara is a trademark of Lumi United Technology Co., Ltd. S1E Panel is not affiliated with, endorsed or supported by Aqara or Lumi United Technology. The factory firmware is not distributed by this project.
