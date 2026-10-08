# Third-party notices

The response-counter algorithm in `src/codex_insights/accounting/token_accounting.py` was ported with reference to [TiboTattle](https://github.com/adamallcock/tibotattle), commit `297b12ef`, `providers/codex/log-parser.js`. It handles inherited baselines, repeated snapshots, counter resets and interleaved updates.

## TiboTattle — MIT License

Copyright (c) 2026 Adam Allcock

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

## Runtime dependencies

Chart.js (MIT) is bundled in the UI; its license notice is retained in the generated JavaScript. Python packaging retains the installed dependency metadata and licenses for pywebview (BSD-3-Clause), pythonnet (MIT), clr-loader (MIT), bottle (MIT), proxy-tools (BSD), watchdog (Apache-2.0), tzlocal (MIT), tzdata (Apache-2.0; IANA public-domain database), cffi (MIT), pycparser (BSD-3-Clause), and typing-extensions (PSF). Python is distributed under the PSF license. Build tools are not application features. Dependency versions are resolved by the lockfiles and release environment.

This project is independent of OpenAI. Codex and OpenAI are trademarks of their respective owners.
