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
schedule, and by `apps/api/src/services/tandem_upload.py` for OAuth token
acquisition during the cloud-upload path. Consumed via `pyproject.toml` as
`tconnectsync>=2.3.0`.

### pydexcom

- Repository: https://github.com/gagebenne/pydexcom
- License: MIT
- Copyright: Gage Benne

Python library for fetching glucose data from Dexcom's cloud using the user's
own Dexcom account credentials. Used by `apps/api/src/services/dexcom_sync.py`
on a polling schedule. Consumed via `pyproject.toml` as `pydexcom>=0.2.0`.

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
