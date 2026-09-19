# Source and design provenance

## Jev Ultrafast

The indexed action table, speculative operation/target questions, local execution, and independent completion check were inspired by Browser Use's Jev Ultrafast. This Python simulator implementation was written independently; it does not bundle the upstream browser executor or inspector.

Reviewed source: [Browser Use / Jev Ultrafast, revision 1231850a0bf1a0c0341fe408ef1668dbbfdfac46](https://github.com/browser-use/jev-ultrafast/tree/1231850a0bf1a0c0341fe408ef1668dbbfdfac46).

Reviewed on 2026-09-19. Upstream license: MIT, Copyright (c) 2026 Browser Use. Its notice is reproduced below for attribution. AXe is invoked as an independently installed executable and is not redistributed here.

> MIT License
>
> Copyright (c) 2026 Browser Use
>
> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all
> copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
> SOFTWARE.

## Appllama design guidance

Daybreak's implementation uses the design principles in the [Appllama app-design skill](https://github.com/Appllama/appllama-skills/blob/dd5caaec3d5d50ad7fc0324da238119c6b7c3707/skills/appllama-app-design-skill/SKILL.md), reviewed together with the [Appllama usage skill](https://github.com/Appllama/appllama-skills/blob/dd5caaec3d5d50ad7fc0324da238119c6b7c3707/skills/appllama-usage/SKILL.md) at revision `dd5caaec3d5d50ad7fc0324da238119c6b7c3707` on 2026-09-19.

The existing UIKit stack uses the design skill's explicit existing-stack override. Applied guidance covers native controls, platform typography, consistent color and shape rules, navigation, and simulator review. The Appllama MCP was unavailable; no access to its design library or MCP research pass is claimed. Appllama's name is used for attribution, and no Appllama logos, watermarks, or library media are redistributed.

The pinned repository's [MIT license](https://github.com/Appllama/appllama-skills/blob/dd5caaec3d5d50ad7fc0324da238119c6b7c3707/LICENSE) is reproduced below:

> MIT License
>
> Copyright (c) 2026 Antmind Ventures Private Limited (appllama.io)
>
> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all
> copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
> SOFTWARE.

## API references

- [Vercel evaluation API](https://vercel.com/docs/ai-gateway/modalities/evaluation)
- [Vercel OIDC authentication](https://vercel.com/docs/ai-gateway/authentication-and-byok/oidc)
- [TypeSafe state format](https://docs.typesafe.ai/concepts/state)
