# Third-Party Licenses

## Tandem BLE Protocol Implementation

The Bluetooth Low Energy protocol implementation in this application is informed
by research and reverse-engineering work from the following MIT-licensed projects:

### pumpX2

- Repository: https://github.com/jwoglom/pumpX2
- License: MIT
- Copyright: James Woglom

Java library implementing a reverse-engineered Bluetooth protocol for Tandem
insulin pumps. Our Kotlin implementation is based on studying this protocol
documentation and message format. No code is imported or used as a runtime
dependency.

### controlX2

- Repository: https://github.com/jwoglom/controlX2
- License: MIT
- Copyright: James Woglom

Android + Wear OS reference application for Tandem insulin pumps. Architecture
patterns for BLE service management and pump pairing were studied from this
project. No code is imported or used as a runtime dependency.

---

MIT License

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

---

## Medtronic MiniMed BLE Protocol Implementation (OpenMinimed)

Unlike the Tandem implementation above (an independent reimplementation that
imports no upstream code), the Medtronic MiniMed 700-series read-only driver is
a **direct vendor / port** of the OpenMinimed project. OpenMinimed's SAKE
handshake is vendored as a **runtime dependency** (compiled into the app), and
its read-only readers are ported line-for-line into Kotlin — not merely studied
as a reference. This is possible because OpenMinimed is GPL-3.0 and GlycemicGPT
is itself GPL-3.0, so the licenses are compatible and copyleft propagation is a
non-issue.

The driver is used **with the explicit permission of the OpenMinimed author**
(palmarci / Pál Marci), who relicensed the work to **GPL-3.0** for this purpose.
Upstream copyright notices and GPL-3.0 headers are retained verbatim in every
vendored and ported file; in-source headers in
`plugins/shipped/medtronic/` cite the specific upstream source file each port is
derived from.

### OpenMinimed

- Organization: https://github.com/OpenMinimed
- License: GPL-3.0
- Copyright: palmarci (Pál Marci) and contributors — drfubar, Morten Fyhn
  Amundsen, Stenium. Original `medtronic-bt-decrypt` proof-of-concept by
  @planiitis.

The four repositories this driver is built from:

| Repository | Role in this app |
|---|---|
| [PythonSake](https://github.com/OpenMinimed/PythonSake) | Reference implementation of the 6-stage SAKE symmetric authenticated key exchange. |
| [PythonPumpConnector](https://github.com/OpenMinimed/PythonPumpConnector) | Authoritative read-only reader logic (Linux/Python). The CGM, IDD status, history, device-info, and battery readers are **ported to Kotlin** from this project. |
| [JavaSake](https://github.com/OpenMinimed/JavaSake) | Production-grade SAKE handshake for the JVM/Android. **Vendored verbatim** as a runtime dependency (package `org.openminimed.sake`) and driven through `MedtronicSakeSession`. |
| [JavaPumpConnector](https://github.com/OpenMinimed/JavaPumpConnector) | Android BLE peripheral scaffolding (permissions, advertising). Informed the connection-manager structure; no data readers exist upstream. |

The Android/JVM ports of JavaSake and JavaPumpConnector are maintained under
[jlengelbrecht](https://github.com/jlengelbrecht) (the GlycemicGPT project lead).

The firmware-derived SAKE key material that the handshake depends on is published
upstream by OpenMinimed under the same GPL-3.0 license; it is vendored as-is and
introduces no new secret.

---

GPL-3.0 License

The OpenMinimed-derived code above, like GlycemicGPT as a whole, is licensed
under the GNU General Public License, version 3. The full license text ships at
the repository root in [`LICENSE`](../../LICENSE). In short, you may use, study,
share, and modify this software, provided that derivative works are distributed
under the same license and that copyright and license notices are preserved.

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR PURPOSE. See the GNU General Public License for more details.
