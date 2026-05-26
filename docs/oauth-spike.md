# Spike: Claude Max OAuth on the EC2 box

Research date: 2026-05-26. Sources cited inline.

## Goal

Replace `ANTHROPIC_API_KEY` (billed at API rates) on the EC2 worker with credentials tied to my personal Claude Max subscription, so cron-driven agents draw from the Max allowance instead of API credit.

## TL;DR

The situation changed substantially since the issue was filed. Anthropic now ships an official, supported headless-auth path:

```
claude setup-token        # walks an interactive OAuth flow, prints a 1-year token
export CLAUDE_CODE_OAUTH_TOKEN=...
```

This is the intended replacement for `ANTHROPIC_API_KEY` when the user wants the request to bill against a Pro/Max plan instead of API credits. It works on a headless Linux box. Source: official authentication docs ([code.claude.com/docs/en/authentication](https://code.claude.com/docs/en/authentication)).

**But** — there's a calendar trap. Starting **June 15, 2026**, Anthropic splits subscription billing into two buckets:

- **Interactive bucket**: `claude` in a TTY/IDE — keeps drawing from normal Max usage limits.
- **Agent SDK bucket**: `claude -p`, Agent SDK calls, GitHub Actions, "third-party apps that authenticate with your Claude subscription". Gets a separate monthly credit pool: $100/mo on Max 5x, $200/mo on Max 20x.

Cron-driven `claude -p` invocations on EC2 will fall into bucket #2, so the Max plan effectively gives this project a fixed monthly Agent SDK credit instead of the full Max allowance. Above that, it cuts off (or rolls to overage depending on plan setup) — same economic behaviour as a metered API key with a budget cap, just denominated in subscription credit instead of dollars. Sources: [Tygart Media writeup](https://tygartmedia.com/claude-agent-sdk-dual-bucket-billing-june-2026/), notice in the official auth doc.

**Recommendation**: switch to `CLAUDE_CODE_OAUTH_TOKEN` now via `claude setup-token`. It's simple, supported, and removes the API-key spend immediately. After June 15 the savings shrink to "we get $100-200/mo of free Agent SDK usage on top of whatever Max gives me personally", which is still better than paying API rates from zero, but plan for that ceiling. Do **not** copy `~/.claude/.credentials.json` from a laptop to the box — that path is fragile and arguably violates ToS.

## What this issue originally asked about (now superseded)

The issue listed three options:

- **(a)** Run `claude /login` interactively over SSH once, persist `~/.claude/.credentials.json`, document refresh cadence.
- **(b)** SSH-port-forward the OAuth callback from the operator's laptop to the box's localhost during login.
- **(c)** Wait for / advocate for an official device-code flow.

These were the right framing in 2025. In 2026 the answer is **(d): use `claude setup-token` + `CLAUDE_CODE_OAUTH_TOKEN`**, which didn't exist when the issue was written. It is essentially an Anthropic-blessed version of (a) that sidesteps the credential-file copying and refresh-token rotation headaches. I still cover (a)–(c) below for completeness.

## How Claude Code auth works today (May 2026)

From the [official authentication doc](https://code.claude.com/docs/en/authentication):

**Credential storage**
- macOS: encrypted Keychain (inaccessible over SSH — exit code 36 `errSecInteractionNotAllowed`, see issue [#44028](https://github.com/anthropics/claude-code/issues/44028)).
- Linux: `~/.claude/.credentials.json` with file mode `0600`.
- Windows: `%USERPROFILE%\.claude\.credentials.json`.

**Precedence order** when multiple credentials are present:
1. Cloud provider creds (Bedrock / Vertex / Foundry).
2. `ANTHROPIC_AUTH_TOKEN` (bearer-token gateway).
3. `ANTHROPIC_API_KEY` (X-Api-Key — direct API billing).
4. `apiKeyHelper` script output.
5. `CLAUDE_CODE_OAUTH_TOKEN` (long-lived OAuth, subscription-backed).
6. Subscription OAuth creds from `/login` (the `.credentials.json` file).

Important: `apiKeyHelper`, `ANTHROPIC_API_KEY`, and `ANTHROPIC_AUTH_TOKEN` only apply to terminal CLI sessions.

**Device-code flow (RFC 8628)**: still **not implemented**. Tracked in open issue [#22992](https://github.com/anthropics/claude-code/issues/22992) (filed Feb 2026, no Anthropic response, no milestone). Related doc/CI request [#7100](https://github.com/anthropics/claude-code/issues/7100) was **closed as "not planned"** — Anthropic's de-facto answer was the `setup-token` route.

**OAuth-over-SSH paste-code fallback**: the standard `claude` login flow now has a fallback for environments where the local callback server isn't reachable (WSL2, SSH, containers). The browser displays a code that you paste back into the terminal at the `Paste code here if prompted` prompt. This is documented in the auth doc and is the cleanest way to do interactive option (a) over SSH without port forwarding. It still requires a human to drive the browser.

## Options for this project

### Option D (NEW, recommended): `claude setup-token` → `CLAUDE_CODE_OAUTH_TOKEN`

The Anthropic-blessed headless path.

**How it works**
1. On any machine with a browser (your laptop is fine — does **not** need to be the EC2 box), run `claude setup-token`.
2. It walks you through the OAuth consent flow against your Max account and prints a token to stdout. The token is **not** stored anywhere by the command — you copy it.
3. Stash it in SSM Parameter Store (`anthropic/oauth-token`, `SecureString`).
4. `terraform/user_data.sh` fetches it on boot like it currently fetches `ANTHROPIC_API_KEY`, exports it as `CLAUDE_CODE_OAUTH_TOKEN` in the worker env.
5. Rotate yearly. Anthropic states the token is valid for one year.

**Pros**
- Single env var, no credential files to babysit.
- Officially supported. Anthropic explicitly calls out "CI pipelines and scripts where browser login isn't available" as the use case.
- Survives reboots, AMI swaps, scaling — no per-instance interactive step.
- No refresh-token rotation race condition (see issue [#25609](https://github.com/anthropics/claude-code/issues/25609)) because there's no rolling refresh on the box.
- Drops API spend to zero up to the Agent SDK credit cap.

**Cons / caveats**
- After 2026-06-15, non-interactive `claude -p` use bills against the Agent SDK credit bucket ($100 on Max 5x, $200 on Max 20x per month), not the broad Max usage limit. We need a budget alert.
- Token is scoped to inference only — can't establish Remote Control sessions. Not an issue for cron-driven `-p` use.
- Bare mode (`claude --bare`) **does not read** `CLAUDE_CODE_OAUTH_TOKEN`. If we ever switch to bare, we'd need `ANTHROPIC_API_KEY` or `apiKeyHelper`.
- One-year expiry needs a calendar reminder. Pure operational toil, but small.

### Option A: copy `~/.claude/.credentials.json` to the box

Log in on laptop, scp the credentials file to `/home/ec2-user/.claude/.credentials.json`, hope it refreshes itself.

**Why I'm rejecting this**
- The credentials file contains a rotating refresh token. Every refresh issues a new token and invalidates the previous one. There's a known race condition when multiple sessions share the file (issue [#25609](https://github.com/anthropics/claude-code/issues/25609), [#48786](https://github.com/anthropics/claude-code/issues/48786)). If my laptop's Claude session refreshes while the EC2 one is also refreshing, one of them gets logged out.
- Multiple posts and at least one ToS analysis ([autonomee.ai](https://autonomee.ai/blog/claude-code-terms-of-service-explained/)) explicitly flag copying `.credentials.json` to another machine as "token extraction" that violates Anthropic's terms. The position is debatable, but `setup-token` exists specifically so I don't have to find out.
- The access token observed lifetime is short (~24h). Need to keep the box online and the refresh working continuously.

### Option B: SSH port-forward the OAuth callback during login

`ssh -R 8080:localhost:8080 ec2-user@box`, run `claude /login` on the box, browser on laptop redirects to laptop:8080, which forwards to box:8080.

**Why I'm rejecting this**
- Works in principle, but the modern `claude /login` flow already has a paste-code fallback for exactly this situation — port forwarding is unnecessary friction.
- Even if the login succeeds, you still end up with the same `~/.credentials.json` rotation problem from Option A.
- The setup is fiddly enough that I'll forget how to do it next year when the cred file expires.

### Option C: wait for device-code flow

The feature request ([#22992](https://github.com/anthropics/claude-code/issues/22992)) is open with no Anthropic response. The doc-request issue ([#7100](https://github.com/anthropics/claude-code/issues/7100)) was closed "not planned", which strongly suggests `setup-token` **is** Anthropic's answer here. Waiting buys nothing.

### Option E: stay on `ANTHROPIC_API_KEY`

Status quo. Predictable, no operational surprises, billed at API rates from the first token. Worth keeping as the fallback when the Max Agent SDK credit is exhausted (see "Hybrid" below).

## Recommendation

**Switch the EC2 worker to `CLAUDE_CODE_OAUTH_TOKEN` (Option D).** Concretely:

1. Run `claude setup-token` locally on my laptop with my Max account.
2. Store the resulting token in SSM at `/claws/anthropic/oauth-token` (SecureString).
3. Update `terraform/user_data.sh`:
   - Fetch `anthropic/oauth-token`.
   - Export as `CLAUDE_CODE_OAUTH_TOKEN` in the worker environment (the same place `ANTHROPIC_API_KEY` is currently exported).
   - Stop exporting `ANTHROPIC_API_KEY` so the precedence rules kick over to the OAuth token (the API key beats the OAuth token if both are present).
4. Verify with `claude /status` that the active auth is the subscription, not API key.
5. Add a calendar reminder for 2027-05 to re-run `setup-token` before the one-year expiry.
6. After June 15, 2026: monitor Agent SDK credit consumption. If we exhaust it, fall back to API key for the remainder of the month rather than running out of capacity mid-task.

**Hybrid fallback (post-2026-06-15)**: keep the API key in SSM. If the project's monthly Agent SDK credit runs out, an `apiKeyHelper` script can fall back to the API key. Easier alternative: keep both env vars set and the API key will win — useful if Agent SDK credit is exhausted but breaks the subscription billing. Cleanest: a tiny helper script that checks the date / a cached "exhausted" flag and emits the right credential. Defer this until we actually see the consumption pattern.

## Risks

- **Agent SDK credit cap (post-June 15, 2026)**: Max 5x gives $100/mo, Max 20x gives $200/mo, of Agent SDK credit. Heavy poller use could blow through it. Need cost telemetry. The savings vs API key are real but bounded.
- **Token expiry**: 1 year. If I forget to rotate, the worker silently fails. Mitigation: calendar reminder + alarm on auth failures in the worker logs.
- **Bare mode incompatibility**: don't use `claude --bare` from the worker (it won't read the OAuth token).
- **Refresh-token race conditions**: avoided by `setup-token`'s long-lived token model — this is the main reason I prefer it over copying `.credentials.json`.
- **ToS gray area for unattended use of a personal subscription**: Anthropic's Feb 2026 docs update introduced the phrase "ordinary, individual usage" for subscription limits. There's no explicit prohibition on cron/headless use, and they shipped `setup-token` partly for this case, but it's ambiguous enough that if this project grows beyond solo use I should reread the consumer terms and consider moving to API billing under the Commercial Terms.
- **Multi-device limits**: each `setup-token` call is a separate token; the doc doesn't mention any device cap. Not a concern at our scale.
- **Single point of failure**: if the token is compromised, an attacker can burn my Max allowance until I revoke. The token sits in SSM under IAM, same blast radius as the current API key. No regression.

## Unknowns / things I couldn't confirm

- Exact behaviour of `CLAUDE_CODE_OAUTH_TOKEN` after the June 15 dual-bucket split: the Tygart Media writeup says "subscription-authenticated requests move to the separate credit bucket regardless of authentication method", but I didn't find that statement in primary Anthropic docs. The notice in the official auth doc covers `claude -p` and Agent SDK explicitly, which is what we use, so the practical outcome is the same.
- Whether the token can be revoked from the Claude.ai dashboard. Not documented. Assume "logout from everywhere" would do it.
- Whether Anthropic will eventually ship RFC 8628 device-code flow. Issue #22992 is open with no response. Doesn't matter operationally since `setup-token` already solves the headless case.

## Follow-up work

Concrete next issue (created as part of this spike): wire `CLAUDE_CODE_OAUTH_TOKEN` into `terraform/user_data.sh` and remove the `ANTHROPIC_API_KEY` export path on the worker. See linked follow-up.
