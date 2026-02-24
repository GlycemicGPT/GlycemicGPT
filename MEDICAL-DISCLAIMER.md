# Medical Disclaimer

## Regulatory Status

This software has **not** been cleared, approved, or certified by any regulatory authority worldwide, including but not limited to:

- The U.S. Food and Drug Administration (FDA)
- EU Notified Bodies (no CE marking under MDR 2017/745)
- Health Canada
- Australia's Therapeutic Goods Administration (TGA)
- Any equivalent national regulatory authority

## Not a Medical Device

**This software is NOT a medical device.** It is experimental open-source software provided for educational and informational purposes only. No individual, organization, or entity associated with this project is the "manufacturer" of a medical device under any regulatory framework.

GlycemicGPT does not control any medical devices. It reads data from insulin pumps and continuous glucose monitors (CGMs), displays that data, and provides AI-generated text suggestions. These suggestions are not medical advice and must not be treated as such.

## Health Data Processing

This software processes health data including:

- Continuous glucose monitor (CGM) readings
- Insulin pump telemetry (basal rates, bolus history, insulin on board)
- Pump hardware status (battery, reservoir levels)
- User-configured therapy parameters (target glucose ranges, insulin ratios)

Users are responsible for understanding the privacy and security implications of their deployment. The self-hosted architecture means users control where their data resides.

When using the BYOAI (Bring Your Own AI) feature, glucose data context is sent to the configured AI provider (Anthropic, OpenAI, Ollama, or a self-hosted endpoint). Users should review their AI provider's data handling policies.

## AI Limitations

AI-generated suggestions in this software are produced by large language models (LLMs) that are known to:

- **Hallucinate** -- generate plausible-sounding but incorrect information
- **Misinterpret data** -- draw incorrect conclusions from glucose readings
- **Provide outdated information** -- not reflect the latest medical guidelines
- **Lack context** -- not understand your complete medical history, comorbidities, or current medications

All AI-generated content in this software is labeled as suggestions, not medical advice. Never act on AI suggestions without consulting your healthcare team.

## Critical Warnings

1. **Do not replace professional medical care.** Always consult with your endocrinologist, diabetes educator, or healthcare provider before making any changes to your diabetes management.

2. **Verify all suggestions.** Any insulin dosing, carb ratio, or correction factor suggestions must be verified with your healthcare team before use.

3. **Use extreme caution.** Incorrect diabetes management can result in severe hypoglycemia, diabetic ketoacidosis (DKA), or other life-threatening conditions.

4. **If you experience a diabetes emergency, contact your healthcare provider or emergency services immediately.** Do not rely on this software for emergency medical guidance.

## Future Pump Control Features

Pump control capabilities (insulin delivery commands) are not included in pre-built releases of this software. If such features are implemented in the future:

- They will be available only by building from source code
- They will require explicit user opt-in and acknowledgment of risks
- They will be subject to additional safety validation pipelines
- Users who build from source assume full responsibility as the "manufacturer" of their personal build

## LIMITATION OF LIABILITY

THE AUTHORS, CONTRIBUTORS, AND MAINTAINERS OF THIS SOFTWARE PROVIDE IT "AS IS" WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, AND NONINFRINGEMENT.

IN NO EVENT SHALL THE AUTHORS, CONTRIBUTORS, OR MAINTAINERS BE LIABLE FOR ANY CLAIM, DAMAGES, OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT, OR OTHERWISE, ARISING FROM, OUT OF, OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

THIS INCLUDES BUT IS NOT LIMITED TO ANY DAMAGES, INJURIES, OR ADVERSE HEALTH OUTCOMES RESULTING FROM THE USE OF THIS SOFTWARE. BY USING GLYCEMICGPT, YOU ACKNOWLEDGE THAT:

- You are using this software entirely at your own risk
- You will not rely solely on AI-generated suggestions for medical decisions
- You understand that AI can and will make errors
- You will maintain regular care with qualified healthcare professionals
- You accept full responsibility for any decisions made based on this software's output
- No individual or entity associated with this project is liable for medical outcomes

## License Warranty Disclaimer

This software is licensed under the GNU General Public License v3.0 (GPL-3.0). Per Sections 15-17 of the GPL-3.0:

- **Section 15:** THERE IS NO WARRANTY FOR THE PROGRAM, TO THE EXTENT PERMITTED BY APPLICABLE LAW. THE ENTIRE RISK AS TO THE QUALITY AND PERFORMANCE OF THE PROGRAM IS WITH YOU.
- **Section 16:** IN NO EVENT UNLESS REQUIRED BY APPLICABLE LAW OR AGREED TO IN WRITING WILL ANY COPYRIGHT HOLDER, OR ANY OTHER PARTY WHO MODIFIES AND/OR CONVEYS THE PROGRAM AS PERMITTED ABOVE, BE LIABLE TO YOU FOR DAMAGES.
- **Section 17:** If the disclaimer of warranty and limitation of liability provided above cannot be given local legal effect according to their terms, reviewing courts shall apply local law that most closely approximates an absolute waiver of all civil liability in connection with the Program.

See the [LICENSE](LICENSE) file for the complete GPL-3.0 text.

**Jurisdictional note:** Limitation of liability clauses for personal injury may be unenforceable in some jurisdictions, including under EU consumer protection law, UK consumer rights legislation, and Australian consumer law. The build-from-source distribution model, where the individual user is the "manufacturer" of their personal build, is the primary risk mitigation strategy. This disclaimer does not constitute legal advice.
