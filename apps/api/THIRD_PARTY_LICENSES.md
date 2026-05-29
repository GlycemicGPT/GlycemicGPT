# Third-Party Licenses

The GlycemicGPT API backend uses the following MIT-licensed runtime
dependencies for diabetes-device integration. This file exists to credit the
upstream authors as required by the MIT license. Both libraries are consumed
as published packages (no code is copied or modified); the official sources are
listed below.

## Diabetes-device integrations

### tconnectsync

- Repository: https://github.com/jwoglom/tconnectsync
- License: MIT
- Copyright: James Woglom

Python library for syncing Tandem t:slim X2 / Mobi pump data with Tandem's
t:connect cloud (`TandemSourceApi`). Used by `apps/api/src/services/tandem_sync.py`
to fetch pump history (boluses, basal, Control-IQ corrections, settings) on a
schedule. Consumed via `pyproject.toml` as `tconnectsync>=2.3.0`.

### pydexcom

- Repository: https://github.com/gagebenne/pydexcom
- License: MIT
- Copyright: Gage Benne

Python library for fetching glucose data from Dexcom's cloud using the user's
own Dexcom account credentials. Used by `apps/api/src/services/dexcom_sync.py`
on a polling schedule. Consumed via `pyproject.toml` as `pydexcom>=0.2.0`.

## Derived specifications (no code copied)

### xDrip+ — CareLink CarePartner / Connect follower

- Repository: https://github.com/NightscoutFoundation/xDrip
  (`app/src/main/java/com/eveningoutpost/dexdrip/cgm/carelinkfollow`)
- License: GNU GPL-3.0 (the same license as this project)

The Medtronic CareLink **CarePartner (Connect)** autonomous-sync feature
(`apps/api/src/services/integrations/medtronic/connect_*.py`) was implemented
independently in Python, but the wire-level specification it conforms to — the
`display/message` endpoint shape, the `RecentData`/`Marker`/`SensorGlucose`
field semantics, and the device-vs-server clock-skew time-correction algorithm
— was learned from xDrip+'s `carelinkfollow` package. xDrip+ is GPL-3.0, which
is license-compatible with this GPL-3.0 project. **No xDrip source code is
copied or vendored;** we credit the xDrip+ / CareLink-follower authors for the
reverse-engineering work the specification rests on, and this project remains
GPL-3.0 accordingly.

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
